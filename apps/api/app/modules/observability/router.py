"""Phase 9 observability endpoints: structured events, timeline, usage, provenance.

Every route resolves ownership through the same ``load_owned_run`` path the rest
of the agent module uses, so an observability id belonging to another student is
indistinguishable from one that does not exist. These are additive read
endpoints; nothing here mutates run state.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_workspace
from app.core.errors import AppError
from app.db.session import get_db
from app.models import AgentArtifact, AgentEvent, User, Workspace, WorkspaceMember
from app.models.enums import WorkspaceRole
from app.modules.agent import service
from app.modules.observability import signals

router = APIRouter(prefix="/api/v1/assignments", tags=["observability"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


def _serialize_event(event: AgentEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "summary": event.summary,
        "metadata_json": event.metadata_json or {},
        "task_id": str(event.task_id) if event.task_id else None,
        "execution_id": str(event.execution_id) if event.execution_id else None,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "severity": event.severity,
        "source_component": event.source_component,
        "outcome": event.outcome,
        "duration_ms": event.duration_ms,
        "schema_version": event.schema_version,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.get(
    "/{assignment_id}/agent/runs/{run_id}/events",
    summary="The structured, correlatable event stream for one run",
)
async def run_events(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: int | None = Query(default=None),
) -> dict[str, Any]:
    """Cursor-paged events, ordered by the run-local sequence.

    The cursor is the last sequence read, so a client reconnecting after a page
    reload continues where it stopped without re-reading history.
    """
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    stmt = select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.sequence.asc())
    if cursor is not None:
        stmt = stmt.where(AgentEvent.sequence > cursor)
    # Fetch one extra row so the cursor is only advertised when a further page
    # actually exists; an empty page back is a bug, not a protocol boundary.
    rows = list((await db.scalars(stmt.limit(limit + 1))).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].sequence if rows and has_more else None
    return {
        "run_id": str(run.id),
        "items": [_serialize_event(e) for e in rows],
        "next_cursor": next_cursor,
    }


@router.get(
    "/{assignment_id}/agent/runs/{run_id}/timeline",
    summary="The user-facing timeline: what happened, in order",
)
async def run_timeline(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    rows = (
        await db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence.asc())
            .limit(limit)
        )
    ).all()
    return {"run_id": str(run.id), "items": [_serialize_event(e) for e in rows]}


@router.get(
    "/{assignment_id}/agent/runs/{run_id}/usage",
    summary="Token usage and estimated cost for one run",
)
async def run_usage(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> dict[str, Any]:
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    usage = run.token_usage or {}
    return {
        "run_id": str(run.id),
        "estimated_cost": float(run.estimated_cost) if run.estimated_cost is not None else None,
        "token_usage": usage,
        "iterations": run.iteration_count,
        "model": run.model,
        "model_tier": run.model_tier,
        "usage_available": bool(usage.get("total_tokens")),
        "cost_source": "provider_estimate" if float(run.estimated_cost or 0) else "unavailable",
        "pricing_version": "2026-10",
    }


@router.get(
    "/{assignment_id}/agent/runs/{run_id}/artifacts/{artifact_id}/provenance",
    summary="Where an artifact came from: the events that produced it",
)
async def artifact_provenance(
    assignment_id: UUID,
    run_id: UUID,
    artifact_id: UUID,
    user: CurrentUser,
    db: Db,
) -> dict[str, Any]:
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    artifact = await db.get(AgentArtifact, artifact_id)
    if artifact is None or artifact.run_id != run.id:
        raise AppError(404, "AGENT_ARTIFACT_NOT_FOUND", "Artifact not found.")

    rows = (
        await db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence.asc())
            # Only events mentioning this artifact are used; the run's full
            # ordered stream is available from the events endpoint, which
            # takes a limit. One bounded scan is enough.
            .limit(2000)
        )
    ).all()
    related = [
        e
        for e in rows
        if (e.metadata_json or {}).get("artifact_id") == str(artifact.id)
        or e.task_id == artifact.task_id
    ]
    return {
        "artifact_id": str(artifact.id),
        "run_id": str(run.id),
        "task_id": str(artifact.task_id) if artifact.task_id else None,
        "revision": artifact.revision,
        "artifact_type": artifact.artifact_type,
        "ownership": artifact.ownership,
        "worker_name": artifact.worker_name,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "events": [
            {
                "id": str(e.id),
                "sequence": e.sequence,
                "event_type": e.event_type,
                "summary": e.summary,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in related
        ],
    }


# ---------------------------------------------------------------------------
# Operator signals. There is no global admin role in this product, so the
# operator surface is scoped to a workspace and restricted to its owner: the
# strongest authority that exists. Signals never cross workspace boundaries.
# ---------------------------------------------------------------------------


async def _require_workspace_owner(workspace: Workspace, user: User, db: AsyncSession) -> None:
    membership = await db.scalar(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if membership != WorkspaceRole.OWNER.value:
        raise AppError(
            403,
            "WORKSPACE_OWNER_REQUIRED",
            "Only the workspace owner can read operational signals.",
        )


@router.get(
    "/{assignment_id}/agent/runs/{run_id}/signals",
    summary="Operational signals for one run's workspace (owner only)",
)
async def run_signals_endpoint(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    workspace: CurrentWorkspace,
    db: Db,
) -> dict[str, Any]:
    """Stalled-run, failure-burst and cost signals, scoped to the caller's workspace."""
    await _require_workspace_owner(workspace, user, db)
    await service.load_owned_run(assignment_id, run_id, user.id, db)
    return await signals.workspace_signals(db, workspace.id)
