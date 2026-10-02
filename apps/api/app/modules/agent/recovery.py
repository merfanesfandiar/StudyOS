"""Recovery for runs that outlived the process executing them.

An agent run is not a database transaction. Between the commit that records a
step and the commit that records its outcome, the process can die, be
restarted, or be rolled back to a restored backup. A run left in ``STARTING`` or
``RUNNING`` therefore does not mean work is happening -- it means a worker
stopped reporting, and the database cannot tell the difference on its own.

This module closes that gap, and it does so conservatively:

* A stale run is **paused, never resumed automatically.** Resuming would mean
  re-entering a loop whose last partial step may already have written a draft,
  charged a model, or produced an artifact. Asking a student to press resume is
  cheap; silently duplicating a half-finished paid step is not.
* A pending checkpoint older than its TTL is **expired, not answered.** An
  unanswered question blocks the run; an expired one releases it. Expiry says
  "nobody replied in time", which is a true statement about the absence of an
  answer.
* Recovery is idempotent. Running it twice finds nothing the second time.

Recovery runs without a requesting user, so its audit rows carry
``user_id=None``: the actor was the runtime, not a person.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.entities import AgentCheckpoint, AgentEvent, AgentRun, Assignment
from app.models.enums import (
    AgentCheckpointStatus,
    AgentEventType,
    AgentRunStatus,
    AuditEventType,
)
from app.modules.agent.state_machine import assert_transition, parse_status
from app.services.events import record_audit

logger = logging.getLogger(__name__)

#: Statuses a recovery sweep may reclaim. Everything else is either finished or
#: legitimately waiting on a person, and must be left exactly as it is.
RECOVERABLE_STATUSES = (AgentRunStatus.STARTING, AgentRunStatus.RUNNING)

INTERRUPTED_STARTING = "The worker stopped before this run began. Resume it when you are ready."
INTERRUPTED_RUNNING = (
    "The worker stopped reporting while this run was in progress. Resume it when you are ready."
)
CHECKPOINT_EXPIRED = "Nobody answered this question in time, so the run moved on."


@dataclass(frozen=True)
class RecoveryReport:
    """What one sweep changed, so a caller can log or assert on it."""

    runs_paused: int = 0
    checkpoints_expired: int = 0
    run_ids: list[UUID] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.runs_paused or self.checkpoints_expired)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runs_paused": self.runs_paused,
            "checkpoints_expired": self.checkpoints_expired,
            "run_ids": [str(rid) for rid in self.run_ids],
        }


def stale_before(timeout_seconds: float, *, now: datetime | None = None) -> datetime:
    """The heartbeat cutoff: anything older than this is presumed abandoned."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    return (now or datetime.now(UTC)) - timedelta(seconds=timeout_seconds)


async def find_stale_runs(
    db: AsyncSession,
    timeout_seconds: float,
    *,
    now: datetime | None = None,
    assignment_id: UUID | None = None,
) -> list[AgentRun]:
    """Find runs whose worker has not reported inside the heartbeat window.

    A run with no heartbeat at all is treated as stale once it is older than the
    window by creation time, so a crash between creation and first heartbeat is
    still reclaimed.

    ``assignment_id`` narrows the sweep to one assignment. It is not an
    optimisation: a sweep triggered by one student's request must not be able to
    pause another student's run, so scoping is what keeps this call safe to
    expose over HTTP.
    """
    cutoff = stale_before(timeout_seconds, now=now)
    stmt = (
        select(AgentRun)
        .where(AgentRun.status.in_([s.value for s in RECOVERABLE_STATUSES]))
        .where(
            (AgentRun.heartbeat_at.is_(None) & (AgentRun.created_at < cutoff))
            | (AgentRun.heartbeat_at.is_not(None) & (AgentRun.heartbeat_at < cutoff))
        )
        .order_by(AgentRun.created_at)
    )
    if assignment_id is not None:
        stmt = stmt.where(AgentRun.assignment_id == assignment_id)
    return list(await db.scalars(stmt))


async def _append_event(
    db: AsyncSession,
    run: AgentRun,
    event_type: AgentEventType,
    summary: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append a recovery event without going through the service lock.

    Recovery holds no run lock: it is by definition the only writer, because the
    writer it is replacing is gone. ``lock_version`` still advances so the
    sequence number keeps moving forward.
    """
    run.lock_version = (run.lock_version or 0) + 1
    db.add(
        AgentEvent(
            run_id=run.id,
            sequence=run.lock_version,
            event_type=event_type.value,
            summary=summary[:500],
            metadata_json=dict(metadata or {}),
        )
    )
    await db.flush()


async def _audit(
    db: AsyncSession,
    run: AgentRun,
    event_type: Any,
    *,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    workspace_id = await db.scalar(
        select(Assignment.workspace_id).where(Assignment.id == run.assignment_id)
    )
    await record_audit(
        db,
        user_id=None,
        workspace_id=workspace_id,
        assignment_id=run.assignment_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
    )


async def pause_stale_run(db: AsyncSession, run: AgentRun, *, reason: str) -> bool:
    """Pause one stale run. Returns ``False`` if it was no longer reclaimable.

    The status is re-read and re-validated rather than assumed, so a race with a
    worker that came back to life cannot be turned into an illegal transition.
    """
    current = parse_status(run.status)
    if current not in RECOVERABLE_STATUSES:
        return False

    assert_transition(current, AgentRunStatus.PAUSED)
    reason_text = reason[:300]
    run.paused_reason = reason_text
    run.status = AgentRunStatus.PAUSED.value
    await _append_event(
        db,
        run,
        AgentEventType.RUN_RECOVERED,
        reason_text,
        metadata={"from_status": current.value, "heartbeat_at": _iso(run.heartbeat_at)},
    )
    await _audit(
        db,
        run,
        AuditEventType.AGENT_RUN_PAUSED,
        entity_type="agent_run",
        entity_id=run.id,
        metadata={"recovered_from": current.value},
    )
    await db.flush()
    logger.warning("agent_run_recovered run_id=%s from=%s", run.id, current.value)
    return True


async def expire_checkpoints(
    db: AsyncSession,
    ttl_seconds: float,
    *,
    now: datetime | None = None,
    assignment_id: UUID | None = None,
) -> list[AgentCheckpoint]:
    """Expire pending checkpoints past their TTL so runs are not stuck forever.

    A pending checkpoint with no student behind it is indistinguishable from an
    unanswered one, and an unanswered one must not hold a run open forever.

    ``assignment_id`` keeps a caller-scoped sweep inside the assignment it owns.
    """
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(seconds=ttl_seconds)
    stmt = (
        select(AgentCheckpoint)
        .where(AgentCheckpoint.status == AgentCheckpointStatus.PENDING.value)
        .where(AgentCheckpoint.requested_at < cutoff)
        .order_by(AgentCheckpoint.requested_at)
    )
    if assignment_id is not None:
        # A checkpoint is scoped through the run that raised it: there is no
        # assignment column of its own to filter on.
        stmt = stmt.join(AgentRun, AgentRun.id == AgentCheckpoint.run_id).where(
            AgentRun.assignment_id == assignment_id
        )
    expired = list(await db.scalars(stmt))
    for checkpoint in expired:
        checkpoint.status = AgentCheckpointStatus.EXPIRED.value
        checkpoint.resolved_at = moment
        checkpoint.response = CHECKPOINT_EXPIRED
    if expired:
        await db.flush()
        logger.warning("agent_checkpoints_expired count=%s", len(expired))
    return expired


async def recover_stale_runs(
    db: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
    assignment_id: UUID | None = None,
) -> RecoveryReport:
    """Run one recovery sweep. Safe to call on every boot and on a timer.

    Omit ``assignment_id`` for the whole-database sweep that a scheduler or boot
    hook performs. Pass it when the sweep is triggered by a user, so the blast
    radius of that request is the one assignment the caller owns.
    """
    moment = now or datetime.now(UTC)
    paused: list[UUID] = []
    for run in await find_stale_runs(
        db, settings.agent_heartbeat_timeout_seconds, now=moment, assignment_id=assignment_id
    ):
        reason = (
            INTERRUPTED_STARTING
            if parse_status(run.status) is AgentRunStatus.STARTING
            else INTERRUPTED_RUNNING
        )
        if await pause_stale_run(db, run, reason=reason):
            paused.append(run.id)

    expired = await expire_checkpoints(
        db, settings.agent_checkpoint_ttl_seconds, now=moment, assignment_id=assignment_id
    )
    return RecoveryReport(runs_paused=len(paused), checkpoints_expired=len(expired), run_ids=paused)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
