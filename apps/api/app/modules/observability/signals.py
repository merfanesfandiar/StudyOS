"""Phase 9 operational signals: stalled runs, failure bursts, cost outliers.

These are lightweight database queries, not a streaming anomaly pipeline. The
product deliberately has no Kafka/OTel/Sentry-style infrastructure, so every
signal is computed from the same ``agent_events`` and ``agent_runs`` tables the
rest of the observability module reads, at request time. Thresholds are plain
module constants; an operator deployment can override them in settings later
without changing the shape of the output.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentEvent, AgentRun, Assignment
from app.models.enums import AgentRunStatus

#: A RUNNING run whose newest event is older than this is considered stalled.
STALL_THRESHOLD_MINUTES = 15

#: More FAILED-severity events than this inside a workspace window is a burst.
FAILURE_BURST_WINDOW_MINUTES = 60
FAILURE_BURST_THRESHOLD = 10

#: A run whose estimated cost exceeds this is flagged for review.
COST_OUTLIER_THRESHOLD = 5.0

_RUNNING = {AgentRunStatus.RUNNING.value}


def _naive_cutoff(minutes: int) -> datetime:
    """A cutoff stored the way this database stores timestamps.

    SQLite keeps datetimes naive; comparing an aware cutoff against naive
    stored values makes Python (and SQLite) disagree. Always hand SQL a naive
    UTC timestamp and re-attach UTC when reading values back.
    """
    return (datetime.now(UTC) - timedelta(minutes=minutes)).replace(tzinfo=None)


async def stalled_runs(db: AsyncSession, workspace_id: UUID) -> list[dict[str, Any]]:
    """Running runs with no fresh events: the likely stuck ones.

    A stalled run is defined operationally rather than metaphysically: it is in
    RUNNING, but its newest event is older than the stall threshold. Runs with
    no events at all use the run's own creation time, so a run that starts and
    silently dies is still caught.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=STALL_THRESHOLD_MINUTES)
    latest = (
        select(AgentEvent.run_id, func.max(AgentEvent.created_at).label("last_at"))
        .group_by(AgentEvent.run_id)
        .subquery()
    )
    stmt = (
        select(AgentRun, latest.c.last_at)
        .outerjoin(latest, latest.c.run_id == AgentRun.id)
        .join(Assignment, Assignment.id == AgentRun.assignment_id)
        .where(
            Assignment.workspace_id == workspace_id,
            AgentRun.status.in_(_RUNNING),
        )
    )
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for run, last_at in (await db.execute(stmt)).all():
        reference = last_at or run.created_at
        if reference is None:
            continue
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        if reference < cutoff:
            out.append(
                {
                    "run_id": str(run.id),
                    "assignment_id": str(run.assignment_id),
                    "status": run.status,
                    "last_event_at": reference.isoformat(),
                    "stalled_minutes": int((now - reference).total_seconds() // 60),
                    "signal": "STALLED_RUN",
                }
            )
    return out


async def failure_bursts(db: AsyncSession, workspace_id: UUID) -> list[dict[str, Any]]:
    """Runs with an abnormal cluster of FAILED events in the recent window."""
    cutoff = _naive_cutoff(FAILURE_BURST_WINDOW_MINUTES)
    stmt = (
        select(AgentEvent.run_id, func.count().label("failures"))
        .join(AgentRun, AgentRun.id == AgentEvent.run_id)
        .join(Assignment, Assignment.id == AgentRun.assignment_id)
        .where(
            Assignment.workspace_id == workspace_id,
            AgentEvent.severity == "ERROR",
            AgentEvent.created_at >= cutoff,
        )
        .group_by(AgentEvent.run_id)
        .having(func.count() >= FAILURE_BURST_THRESHOLD)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "run_id": str(run_id),
            "failures": count,
            "window_minutes": FAILURE_BURST_WINDOW_MINUTES,
            "signal": "FAILURE_BURST",
        }
        for run_id, count in rows
    ]


async def cost_outliers(db: AsyncSession, workspace_id: UUID) -> list[dict[str, Any]]:
    """Runs whose accumulated estimated cost crosses the review threshold."""
    stmt = (
        select(AgentRun)
        .join(Assignment, Assignment.id == AgentRun.assignment_id)
        .where(
            Assignment.workspace_id == workspace_id,
            AgentRun.estimated_cost.is_not(None),
            AgentRun.estimated_cost >= COST_OUTLIER_THRESHOLD,
        )
        .order_by(desc(AgentRun.estimated_cost))
        .limit(50)
    )
    return [
        {
            "run_id": str(run.id),
            "estimated_cost": float(run.estimated_cost),
            "status": run.status,
            "threshold": COST_OUTLIER_THRESHOLD,
            "signal": "COST_OUTLIER",
        }
        for run in (await db.scalars(stmt)).all()
    ]


async def workspace_signals(db: AsyncSession, workspace_id: UUID) -> dict[str, Any]:
    """All signals for one workspace, in one response."""
    return {
        "workspace_id": str(workspace_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "stalled_runs": await stalled_runs(db, workspace_id),
        "failure_bursts": await failure_bursts(db, workspace_id),
        "cost_outliers": await cost_outliers(db, workspace_id),
    }
