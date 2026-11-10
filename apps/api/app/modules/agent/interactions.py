"""Durable HITL interactions (Phase 8)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import AgentInteraction, AgentInteractionResponse, AgentRun, User
from app.models.enums import (
    AgentInteractionRisk,
    AgentInteractionStatus,
    AgentInteractionType,
    AgentRunStatus,
    AuditEventType,
)
from app.modules.agent.state_machine import parse_status


def _now() -> datetime:
    return datetime.now(UTC)


async def load_owned_interaction(
    assignment_id: UUID,
    run_id: UUID,
    interaction_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> tuple[AgentInteraction, AgentRun]:
    from sqlalchemy.orm import selectinload

    from app.modules.agent.service import load_owned_run

    run = await load_owned_run(assignment_id, run_id, user_id, db)
    stmt = (
        select(AgentInteraction)
        .options(selectinload(AgentInteraction.responses))
        .where(AgentInteraction.id == interaction_id, AgentInteraction.run_id == run.id)
    )
    interaction = (await db.scalars(stmt)).first()
    if interaction is None or interaction.assignment_id != assignment_id:
        raise AppError(404, "AGENT_INTERACTION_NOT_FOUND", "Interaction not found.")
    return interaction, run


async def get_interaction_with_responses(
    db: AsyncSession, interaction_id: UUID
) -> AgentInteraction | None:
    """Fetch one interaction with its decision history eager-loaded.

    Serialising ``responses`` lazily under asyncio raises ``MissingGreenlet``,
    so every path that validates an interaction into a response model reads it
    through here instead of holding a bare identity-mapped row.
    """
    from sqlalchemy.orm import selectinload

    stmt = (
        select(AgentInteraction)
        .options(selectinload(AgentInteraction.responses))
        .where(AgentInteraction.id == interaction_id)
    )
    return (await db.scalars(stmt)).first()


async def create_interaction(
    db: AsyncSession,
    run: AgentRun,
    assignment_id: UUID,
    workspace_id: UUID,
    *,
    interaction_type: AgentInteractionType,
    risk: AgentInteractionRisk,
    priority: str,
    title: str,
    prompt: str,
    context: str | None,
    options: list[dict[str, Any]] | None,
    operation_binding: dict[str, Any],
    ui: dict[str, Any],
    task_id: UUID | None,
    checkpoint_id: UUID | None,
    owner_id: UUID | None,
    expires_at: datetime | None,
    metadata_json: dict[str, Any],
) -> AgentInteraction:
    if operation_binding is None:
        operation_binding = {}
    if ui is None:
        ui = {}
    if metadata_json is None:
        metadata_json = {}

    interaction = AgentInteraction(
        run_id=run.id,
        assignment_id=assignment_id,
        workspace_id=workspace_id,
        task_id=task_id,
        checkpoint_id=checkpoint_id,
        owner_id=owner_id,
        interaction_type=interaction_type.value,
        status=AgentInteractionStatus.PENDING.value,
        risk=risk.value,
        priority=priority,
        title=title[:240],
        prompt=prompt[:4000],
        context=context[:4000] if context else None,
        options=options,
        operation_binding=operation_binding,
        ui=ui,
        version=1,
        expires_at=expires_at,
        metadata_json=metadata_json,
    )
    db.add(interaction)
    await db.flush()

    from app.models.enums import AgentEventType
    from app.modules.agent.service import _append_event

    await _append_event(
        db,
        run,
        AgentEventType.INTERACTION_REQUESTED,
        f"The agent needs your input: {title[:200]}",
        metadata={
            "interaction_id": str(interaction.id),
            "interaction_type": interaction_type.value,
            "risk": risk.value,
        },
        task_id=task_id,
    )
    return interaction


async def list_interactions(
    db: AsyncSession,
    run: AgentRun,
    status_filter: AgentInteractionStatus | None = None,
    *,
    limit: int = 100,
) -> list[AgentInteraction]:
    from sqlalchemy.orm import selectinload

    # Expired proposals must show as EXPIRED rather than silently pending
    # forever, so the sweep runs before the read. The security property
    # (an expired interaction can never authorise) is enforced separately at
    # response time and does not depend on this sweep.
    await expire_stale_interactions(db)
    stmt = (
        select(AgentInteraction)
        .options(selectinload(AgentInteraction.responses))
        .where(AgentInteraction.run_id == run.id)
    )
    if status_filter is not None:
        stmt = stmt.where(AgentInteraction.status == status_filter.value)
    stmt = stmt.order_by(AgentInteraction.requested_at.asc()).limit(limit)
    res = await db.scalars(stmt)
    return list(res.all())


async def get_interaction(db: AsyncSession, interaction: AgentInteraction) -> AgentInteraction:
    # refresh
    await db.refresh(interaction)
    return interaction


def _coerce_aware(value: datetime | None) -> datetime | None:
    """SQLite stores datetimes naive; normalise for comparison against ``now``."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def respond_to_interaction(
    db: AsyncSession,
    interaction: AgentInteraction,
    run: AgentRun,
    user: User,
    *,
    action: str,
    payload: dict[str, Any],
    rationale: str | None,
    artifacts: list[dict[str, Any]] | None,
    diff: dict[str, Any] | None,
) -> AgentInteraction:
    from app.models.enums import AgentEventType
    from app.modules.agent.service import RunClaimLost, _append_event, _audit_run, _set_status

    now = _now()
    expires = _coerce_aware(interaction.expires_at)
    if expires and expires <= now:
        interaction.status = AgentInteractionStatus.EXPIRED.value
        interaction.resolved_at = now
        await db.flush()
        await _append_event(
            db,
            run,
            AgentEventType.INTERACTION_EXPIRED,
            "This request expired without an answer; the run stays stopped.",
            metadata={"interaction_id": str(interaction.id)},
            task_id=interaction.task_id,
        )
        raise AppError(409, "AGENT_INTERACTION_EXPIRED", "This interaction has expired.")

    if interaction.status not in {
        AgentInteractionStatus.PENDING.value,
        AgentInteractionStatus.SUBMITTED.value,
    }:
        raise AppError(
            409,
            "AGENT_INTERACTION_ALREADY_RESOLVED",
            "This interaction has already been resolved.",
            {"status": interaction.status},
        )

    action_l = (action or "").strip().lower()
    if action_l not in {
        "approve",
        "accepted",
        "accept",
        "reject",
        "rejected",
        "revise",
        "submit",
        "answer",
    }:
        raise AppError(422, "AGENT_INTERACTION_INVALID_ACTION", "Unsupported action.")

    # Determine outcome
    if action_l in {"approve", "accepted", "accept"}:
        new_status = AgentInteractionStatus.ACCEPTED.value
        resp_status = "ACCEPTED"
    elif action_l in {"reject", "rejected"}:
        new_status = AgentInteractionStatus.REJECTED.value
        resp_status = "REJECTED"
    else:  # revise/submit/answer treated as submitted; still requires revalidation
        new_status = AgentInteractionStatus.SUBMITTED.value
        resp_status = "SUBMITTED"

    # Create immutable response
    resp_count = len(interaction.responses) if interaction.responses else 0
    resp = AgentInteractionResponse(
        interaction_id=interaction.id,
        run_id=run.id,
        responder_id=user.id,
        version=resp_count + 1,
        status=resp_status,
        response_type=action_l,
        payload=payload or {},
        rationale=rationale[:2000] if rationale else None,
        artifacts=artifacts,
        diff=diff,
        operation_binding_snapshot=dict(interaction.operation_binding or {}),
    )
    db.add(resp)
    interaction.responses.append(resp)
    await db.flush()

    resumed = False
    interaction.status = new_status
    if new_status in {AgentInteractionStatus.ACCEPTED.value, AgentInteractionStatus.REJECTED.value}:
        interaction.resolved_at = now
        # Only an accepted decision continues the run, and only from the two
        # waiting states. A BLOCKED run is behind an unresolved wall (a failed
        # task, a missing dependency): accepting an unrelated interaction must
        # not bypass it. Resuming a blocked run is ``resume_run``'s job, which
        # verifies the wall is actually gone before the run moves.
        cur = parse_status(run.status)
        if new_status == AgentInteractionStatus.ACCEPTED.value and cur in {
            AgentRunStatus.WAITING_FOR_USER,
            AgentRunStatus.PAUSED,
        }:
            try:
                await _set_status(db, run, AgentRunStatus.RUNNING)
            except RunClaimLost as exc:
                raise AppError(
                    409,
                    "AGENT_RUN_STATE_CHANGED",
                    "This run changed state while your decision was being recorded. "
                    "Refresh and check its current status.",
                ) from exc
            resumed = True
    await db.flush()

    await _append_event(
        db,
        run,
        AgentEventType.INTERACTION_RESPONDED,
        {
            AgentInteractionStatus.ACCEPTED.value: "You approved the request.",
            AgentInteractionStatus.REJECTED.value: "You rejected the request.",
        }.get(new_status, "You submitted a response."),
        metadata={"interaction_id": str(interaction.id), "action": action_l},
        task_id=interaction.task_id,
    )
    if resumed:
        await _append_event(
            db,
            run,
            AgentEventType.RUN_RESUMED,
            "You answered, so the run is continuing.",
            metadata={"interaction_id": str(interaction.id)},
        )
        await _audit_run(
            db,
            run,
            user,
            AuditEventType.AGENT_RUN_RESUMED,
            entity_type="agent_interaction",
            entity_id=interaction.id,
            metadata={"action": action_l},
        )
    await _audit_run(
        db,
        run,
        user,
        AuditEventType.AGENT_INTERACTION_RESOLVED,
        entity_type="agent_interaction",
        entity_id=interaction.id,
        metadata={"action": action_l, "status": new_status},
    )
    return interaction


async def cancel_interaction(
    db: AsyncSession,
    interaction: AgentInteraction,
    *,
    reason: str | None,
) -> AgentInteraction:
    from app.models.enums import AgentEventType
    from app.modules.agent.service import _append_event

    now = _now()
    resolved_cancel_block = {
        AgentInteractionStatus.ACCEPTED.value,
        AgentInteractionStatus.REJECTED.value,
        AgentInteractionStatus.EXPIRED.value,
    }
    if interaction.status in resolved_cancel_block:
        raise AppError(
            409, "AGENT_INTERACTION_CANNOT_CANCEL", "Cannot cancel a resolved interaction."
        )
    interaction.status = AgentInteractionStatus.CANCELLED.value
    interaction.cancelled_at = now
    interaction.cancel_reason = (reason or "Cancelled")[:500]
    await db.flush()
    run = await db.get(AgentRun, interaction.run_id)
    if run is not None:
        await _append_event(
            db,
            run,
            AgentEventType.INTERACTION_CANCELLED,
            "The request was withdrawn; the proposed operation will not run.",
            metadata={"interaction_id": str(interaction.id)},
            task_id=interaction.task_id,
        )
    return interaction


async def expire_stale_interactions(db: AsyncSession) -> int:
    from app.models.enums import AgentEventType
    from app.modules.agent.service import _append_event

    now = _now()
    stmt = select(AgentInteraction).where(
        AgentInteraction.status.in_(
            [AgentInteractionStatus.PENDING.value, AgentInteractionStatus.SUBMITTED.value]
        ),
        AgentInteraction.expires_at.is_not(None),
        AgentInteraction.expires_at <= now,
    )
    res = await db.scalars(stmt)
    count = 0
    for inter in res.all():
        inter.status = AgentInteractionStatus.EXPIRED.value
        inter.resolved_at = now
        run = await db.get(AgentRun, inter.run_id)
        if run is not None:
            await _append_event(
                db,
                run,
                AgentEventType.INTERACTION_EXPIRED,
                "A pending request expired without an answer.",
                metadata={"interaction_id": str(inter.id)},
                task_id=inter.task_id,
            )
        count += 1
    await db.flush()
    return count
