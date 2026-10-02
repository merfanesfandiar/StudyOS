"""The agent runtime service: lifecycle, execution loop and persistence.

This is where the pieces meet. The rules it exists to enforce:

* **A run works an approved plan, and only that.** A run binds the exact plan
  version at creation, so "what was I supposed to do" stays answerable even after
  the plan is regenerated.
* **The loop is bounded.** Every iteration checks the iteration, cost and artifact
  budgets *before* doing work, so a bad run stops with an explanation instead of
  discovering its cost later.
* **One run, one writer.** :func:`_lock_run` takes a row lock and bumps
  ``lock_version``; a step that finds its version superseded knows it lost a race
  and stops rather than double-writing.
* **Every step is recorded before it is acted on.** Events, decisions and
  executions are persisted in the same transaction as the state change they
  describe, so a crash can never leave the activity feed disagreeing with the
  run's status.
* **Failures are classified, not stringly-compared.** The category decides
  whether a retry is permitted at all.

The provider is injected. In production it is whatever ``ModelRouter`` selects;
in tests it is the mock, which makes the whole loop exercisable offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai import LLMError, LLMTimeoutError
from app.ai.errors import LLMUnavailableError
from app.ai.prompts.agent import build_decision_request, build_execution_request
from app.ai.provider import LLMProvider, LLMResponse
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import logger
from app.models import (
    AcademicWorkPlan,
    AgentArtifact,
    AgentCheckpoint,
    AgentDecision,
    AgentEvent,
    AgentRun,
    AgentTaskExecution,
    Assignment,
    PlanTask,
    PlanTaskDependency,
    PlanTaskRequirement,
    User,
    WorkspaceMember,
)
from app.models.enums import (
    AcademicTaskStatus,
    AgentAction,
    AgentArtifactStatus,
    AgentArtifactType,
    AgentCheckpointStatus,
    AgentCheckpointType,
    AgentEventType,
    AgentExecutionStatus,
    AgentFailureCategory,
    AgentRunMode,
    AgentRunStatus,
    AuditEventType,
    ComplexityLevel,
)
from app.modules.agent.context import AgentContext, assemble_context
from app.modules.agent.decisions import (
    DecisionContext,
    DecisionRejected,
    TaskView,
    parse_decision,
    validate_permissions,
    validate_semantics,
)
from app.modules.agent.executors import (
    ArtifactDraft,
    ExecutionRequest,
    ExecutionResult,
    ExecutorRegistry,
    artifact_type_for_task,
    parse_execution_output,
)
from app.modules.agent.limits import (
    AgentLimits,
    BudgetExceeded,
    assert_artifact_budget,
    assert_cost_budget,
    assert_iteration_budget,
    may_retry,
)
from app.modules.agent.ml import PredictorRegistry, advise
from app.modules.agent.selection import (
    Selection,
    TaskNode,
    approval_required_keys,
    build_nodes,
    progress,
    select_next_task,
)
from app.modules.agent.state_machine import (
    AWAITING_PERSON,
    RESUMABLE_STATUSES,
    TERMINAL_STATUSES,
    assert_transition,
    parse_status,
)
from app.modules.agent.tools import DEFAULT_TOOLS, ToolRegistry
from app.modules.assignments.service import load_owned_assignment
from app.modules.planning import service as planning_service
from app.modules.planning.complexity import ComplexityScore
from app.services.events import record_audit

settings = get_settings()

#: Drafts one task may accumulate in a single run before the runtime stops and
#: asks the student. Two is enough for "first pass, then fix what I found"; past
#: that, another pass is usually a sign the task is under-specified rather than
#: that the model is getting closer.
MAX_REVISIONS_PER_TASK = 2


# ---------------------------------------------------------------------------
# Outcome of one step
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """What one loop iteration did.

    Returned rather than logged so the caller (the HTTP layer, or a test) can see
    exactly how far a run got without reading the event stream.
    """

    #: ``ADVANCED`` means the loop should iterate again; every other value is a
    #: stop condition with its own reason.
    kind: str
    run_status: AgentRunStatus
    detail: str = ""
    task_key: str | None = None
    artifact_id: UUID | None = None
    checkpoint_id: UUID | None = None
    decision_action: AgentAction | None = None


#: Categories worth retrying. Everything else is either a student problem or a
#: bug, and retrying a bug just burns the budget three times.
RETRYABLE: frozenset[AgentFailureCategory] = frozenset(
    {
        AgentFailureCategory.TRANSIENT_PROVIDER,
        AgentFailureCategory.RATE_LIMITED,
        AgentFailureCategory.VALIDATION_ERROR,
    }
)


def run_idempotency_key(assignment_id: UUID, plan_id: UUID | None, key: str | None) -> str:
    """Deterministic key for a start request.

    A client-supplied key is folded together with the plan version so the same
    key against a *different* plan is a different run — otherwise re-running a
    regenerated plan would be silently ignored as a duplicate.
    """
    payload = f"{assignment_id}:{plan_id}:{key or 'default'}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


# ---------------------------------------------------------------------------
# Loading and ownership
# ---------------------------------------------------------------------------


async def load_owned_run(
    assignment_id: UUID, run_id: UUID, user_id: UUID, db: AsyncSession
) -> AgentRun:
    """Load a run the caller owns, or 404.

    404 rather than 403, matching every other load path in the product: a run id
    belonging to someone else must not be distinguishable from one that does not
    exist.
    """
    result = await db.execute(
        select(AgentRun)
        .join(Assignment, Assignment.id == AgentRun.assignment_id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Assignment.workspace_id)
        .where(
            AgentRun.id == run_id,
            AgentRun.assignment_id == assignment_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise AppError(404, "AGENT_RUN_NOT_FOUND", "Agent run not found.")
    return run


async def latest_run(assignment_id: UUID, db: AsyncSession) -> AgentRun | None:
    stmt = (
        select(AgentRun)
        .where(AgentRun.assignment_id == assignment_id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    return cast("AgentRun | None", await db.scalar(stmt))


async def recent_runs(assignment_id: UUID, db: AsyncSession, *, limit: int = 20) -> list[AgentRun]:
    """An assignment's runs, newest first, with their collections loaded.

    A list view does not need the per-task detail rows, so it avoids the queries
    ``load_run_detail`` makes. The summary still carries progress and the pending
    checkpoint, because those are what a list has to show to be useful.
    """
    stmt = (
        select(AgentRun)
        .where(AgentRun.assignment_id == assignment_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
        .options(*RUN_LOADERS)
    )
    return list(await db.scalars(stmt))


async def load_run_summary(run: AgentRun, db: AsyncSession) -> Any:
    """The part of a run a list view needs: no per-task detail rows.

    Returns the response model rather than a dict so the list endpoint's declared
    type is checked here instead of by the client.
    """
    from app.schemas.agent import AgentProgressResponse, AgentRunResponse

    status = parse_status(run.status)
    pending = next(
        (c for c in run.checkpoints if c.status == AgentCheckpointStatus.PENDING.value),
        None,
    )
    counts = None
    if run.plan_id is not None:
        plan = await db.get(AcademicWorkPlan, run.plan_id)
        if plan is not None:
            counts = progress(await _task_nodes(db, plan))
    payload = AgentRunResponse(
        id=run.id,
        assignment_id=run.assignment_id,
        plan_id=run.plan_id,
        plan_version=run.plan_version,
        status=status,
        mode=AgentRunMode(run.mode),
        paused_reason=run.paused_reason,
        error_code=run.error_code,
        error_message=run.error_message,
        error_category=AgentFailureCategory(run.error_category) if run.error_category else None,
        model=run.model,
        model_tier=run.model_tier,
        routing_reason=run.routing_reason,
        iteration_count=run.iteration_count,
        max_iterations=run.max_iterations,
        max_cost=float(run.max_cost),
        estimated_cost=float(run.estimated_cost),
        token_usage=run.token_usage,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
        updated_at=run.updated_at,
        progress=AgentProgressResponse(**counts) if counts else None,
        awaiting_checkpoint_id=pending.id if pending else None,
        can_resume=status in RESUMABLE_STATUSES,
        can_retry=status is AgentRunStatus.FAILED,
    )
    return payload


async def active_run(assignment_id: UUID, db: AsyncSession) -> AgentRun | None:
    """A run that currently owns the assignment, if any.

    Exactly one may exist. Two live runs against one plan would race on task
    status, so starting a second is refused rather than reconciled.
    """
    live = (AgentRunStatus.RUNNING.value, AgentRunStatus.STARTING.value)
    waiting = (
        AgentRunStatus.WAITING_FOR_USER.value,
        AgentRunStatus.PAUSED.value,
        AgentRunStatus.BLOCKED.value,
    )
    stmt = (
        select(AgentRun)
        .where(
            AgentRun.assignment_id == assignment_id,
            AgentRun.status.in_([*live, *waiting]),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    return cast("AgentRun | None", await db.scalar(stmt))


async def count_runs(assignment_id: UUID, db: AsyncSession) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.assignment_id == assignment_id)
        )
    ) or 0


async def find_idempotent_run(assignment_id: UUID, key: str, db: AsyncSession) -> AgentRun | None:
    stmt = select(AgentRun).where(
        AgentRun.assignment_id == assignment_id, AgentRun.idempotency_key == key
    )
    return cast("AgentRun | None", await db.scalar(stmt))


# ---------------------------------------------------------------------------
# Plan loading
# ---------------------------------------------------------------------------


async def _require_approved_plan(assignment_id: UUID, db: AsyncSession) -> AcademicWorkPlan:
    """Return the assignment's approved plan, or explain what is missing.

    An agent needs an approved plan. This is the single most important guard in
    the module: without it the agent would be improvising a schedule, which is
    exactly the thing Phase 4 exists to prevent.
    """
    plan = await planning_service.approved_plan(assignment_id, db)
    if plan is None:
        raise AppError(
            409,
            "AGENT_NO_APPROVED_PLAN",
            "Approve a plan before starting an agent run.",
            {"hint": "The agent executes a plan you reviewed and approved."},
        )
    if plan.is_stale:
        raise AppError(
            409,
            "AGENT_PLAN_STALE",
            "This plan is out of date because the assignment analysis changed.",
            {"hint": "Regenerate and approve a current plan first."},
        )
    return plan


async def _assignment_for_plan(plan: AcademicWorkPlan, db: AsyncSession) -> Assignment:
    assignment = await db.get(Assignment, plan.assignment_id)
    if assignment is None:  # pragma: no cover - FK guarantees the row exists
        raise AppError(409, "AGENT_ASSIGNMENT_MISSING", "The plan's assignment is missing.")
    return assignment


async def _task_nodes(db: AsyncSession, plan: AcademicWorkPlan) -> tuple[TaskNode, ...]:
    """Load the plan's tasks and dependency edges as a schedulable graph."""
    tasks = list(
        await db.scalars(
            select(PlanTask).where(PlanTask.plan_id == plan.id).order_by(PlanTask.position)
        )
    )
    edges = list(
        await db.execute(
            select(PlanTaskDependency.predecessor_id, PlanTaskDependency.successor_id).where(
                PlanTaskDependency.plan_id == plan.id
            )
        )
    )
    by_id = {t.id: t.key for t in tasks}
    predecessors: dict[str, list[str]] = {t.key: [] for t in tasks}
    for predecessor_id, successor_id in edges:
        predecessor = by_id.get(predecessor_id)
        successor = by_id.get(successor_id)
        if predecessor and successor:
            predecessors[successor].append(predecessor)
    return build_nodes(
        [
            TaskNode(
                key=t.key,
                status=t.status,
                priority=t.priority,
                position=t.position,
                type=t.type,
            )
            for t in tasks
        ],
        predecessors=predecessors,
    )


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


async def _workspace_for(db: AsyncSession, run: AgentRun) -> UUID | None:
    stmt = select(Assignment.workspace_id).where(Assignment.id == run.assignment_id)
    return cast("UUID | None", await db.scalar(stmt))


async def _audit_run(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    event_type: AuditEventType,
    *,
    entity_type: str,
    entity_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record an audited step of a run, resolving the workspace from the assignment.

    Kept as one helper so every agent audit row carries the same fields; an audit
    trail with gaps in it answers fewer questions than having none would.
    """
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=await _workspace_for(db, run),
        assignment_id=run.assignment_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id if entity_id is not None else run.id,
        metadata=metadata,
    )


async def _append_event(
    db: AsyncSession,
    run: AgentRun,
    event_type: AgentEventType,
    summary: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    task_id: UUID | None = None,
    execution_id: UUID | None = None,
) -> AgentEvent:
    """Append one user-safe event.

    Every append advances the run's version and uses it as the sequence, so the
    numbers are dense, strictly increasing and unique per run. The run row is
    locked for the duration of a step, so one writer at a time; the unique
    constraint on ``(run_id, sequence)`` is the backstop that turns a lost race
    into a loud failure instead of an event log that silently disagrees with
    itself.
    """
    run.lock_version = (run.lock_version or 0) + 1
    event = AgentEvent(
        run_id=run.id,
        sequence=run.lock_version,
        event_type=event_type.value,
        summary=summary[:500],
        metadata_json=dict(metadata or {}),
        task_id=task_id,
        execution_id=execution_id,
    )
    db.add(event)
    await db.flush()
    return event


# ---------------------------------------------------------------------------
# Run creation
# ---------------------------------------------------------------------------


async def create_run(
    assignment_id: UUID,
    user: User,
    db: AsyncSession,
    *,
    mode: AgentRunMode = AgentRunMode.SUPERVISED,
    max_cost: float | None = None,
    idempotency_key: str | None = None,
) -> AgentRun:
    """Create a run over the assignment's approved plan.

    Creation does not execute. The run is created ``CREATED`` and the caller
    decides whether to start it, so "I set up a run" and "the agent started
    working" are separate, auditable events.
    """
    await load_owned_assignment(assignment_id, user.id, db)
    plan = await _require_approved_plan(assignment_id, db)

    key = run_idempotency_key(assignment_id, plan.id, idempotency_key)
    existing = await find_idempotent_run(assignment_id, key, db)
    if existing is not None:
        return existing

    live = await active_run(assignment_id, db)
    if live is not None:
        raise AppError(
            409,
            "AGENT_RUN_ACTIVE",
            "There is already a run in progress for this assignment.",
            {"run_id": str(live.id), "status": live.status},
        )

    limits = AgentLimits.from_settings(settings)
    ceiling = Decimal(str(settings.agent_max_cost_per_run))
    if max_cost is not None:
        requested = Decimal(str(max_cost))
        if requested > ceiling:
            raise AppError(
                422,
                "AGENT_COST_LIMIT_TOO_HIGH",
                f"The cost ceiling for one run is {ceiling}.",
                {"max_allowed": float(ceiling), "requested": float(requested)},
            )
        ceiling = requested

    run = AgentRun(
        assignment_id=assignment_id,
        plan_id=plan.id,
        # Frozen now. If the plan is regenerated later, this run still refers to
        # the schedule the student actually agreed to.
        plan_version=plan.version,
        status=AgentRunStatus.CREATED.value,
        mode=mode.value,
        max_iterations=limits.max_iterations,
        max_cost=ceiling,
        estimated_cost=Decimal("0"),
        idempotency_key=key,
        triggered_by_id=user.id,
    )
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Lost a race with a concurrent identical start. Return the winner rather
        # than 500-ing on a request that was valid.
        await db.rollback()
        winner = await find_idempotent_run(assignment_id, key, db)
        if winner is None:
            raise AppError(409, "AGENT_RUN_CONFLICT", "Could not start a run right now.") from exc
        return winner

    await _append_event(
        db,
        run,
        AgentEventType.RUN_CREATED,
        f"Agent run created in {mode.value.lower()} mode.",
        metadata={"plan_id": str(plan.id), "plan_version": plan.version, "mode": mode.value},
    )
    workspace_id = await db.scalar(
        select(Assignment.workspace_id).where(Assignment.id == assignment_id)
    )
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=workspace_id,
        assignment_id=assignment_id,
        event_type=AuditEventType.AGENT_RUN_CREATED,
        entity_type="agent_run",
        entity_id=run.id,
        metadata={"plan_version": plan.version, "mode": mode.value},
    )
    await db.flush()
    return run


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def _limits_for(run: AgentRun) -> AgentLimits:
    """Rebuild the run's own budget.

    From the run row rather than from settings: a run's limits are the ones it
    started with, so a config reload cannot change a run's rules mid-flight.
    """
    return AgentLimits(
        max_iterations=run.max_iterations,
        max_task_attempts=settings.agent_max_task_attempts,
        max_consecutive_failures=settings.agent_max_consecutive_failures,
        max_cost_per_run=Decimal(str(run.max_cost)),
        max_cost_per_step=Decimal(str(settings.agent_max_cost_per_step)),
        step_timeout_seconds=settings.agent_step_timeout_seconds,
        max_artifacts=settings.agent_max_artifacts,
        retry_backoff_seconds=settings.agent_retry_backoff_seconds,
        checkpoint_ttl_seconds=settings.agent_checkpoint_ttl_seconds,
        decision_token_ratio=settings.agent_decision_token_ratio,
    )


def _set_status(run: AgentRun, target: AgentRunStatus, *, reason: str | None = None) -> None:
    """Move a run, rejecting anything not in the table."""
    current = parse_status(run.status)
    assert_transition(current, target)
    run.status = target.value
    if target in TERMINAL_STATUSES and run.completed_at is None:
        run.completed_at = datetime.now(UTC)
    if reason is not None:
        run.paused_reason = reason[:300]
    elif target in {AgentRunStatus.RUNNING, AgentRunStatus.STARTING}:
        run.paused_reason = None
        run.error_code = None
        run.error_message = None
        run.error_category = None


async def _lock_run(run: AgentRun, db: AsyncSession) -> AgentRun:
    """Claim the run for writing.

    ``SELECT ... FOR UPDATE`` plus a ``lock_version`` bump gives one writer at a
    time and a way to detect that a writer was superseded. SQLite has no row
    locks, so the version bump is what actually carries the guarantee there; on
    PostgreSQL both do.
    """
    await db.execute(select(AgentRun.id).where(AgentRun.id == run.id).with_for_update())
    run.lock_version = (run.lock_version or 0) + 1
    run.heartbeat_at = datetime.now(UTC)
    await db.flush()
    return run


async def start_run(run: AgentRun, user: User, db: AsyncSession) -> AgentRun:
    """Start a created run."""
    _set_status(run, AgentRunStatus.STARTING)
    run.started_at = run.started_at or datetime.now(UTC)
    await _append_event(
        db, run, AgentEventType.RUN_STARTED, "Agent run started.", metadata={"mode": run.mode}
    )
    await _audit_run(db, run, user, AuditEventType.AGENT_RUN_STARTED, entity_type="agent_run")
    await db.flush()
    return run


async def pause_run(run: AgentRun, user: User, db: AsyncSession, *, reason: str) -> AgentRun:
    _set_status(run, AgentRunStatus.PAUSED, reason=reason)
    await _append_event(db, run, AgentEventType.RUN_PAUSED, reason, metadata={"reason": reason})
    await _audit_run(
        db,
        run,
        user,
        AuditEventType.AGENT_RUN_PAUSED,
        entity_type="agent_run",
        metadata={"reason": reason},
    )
    await db.flush()
    return run


async def resume_run(
    run: AgentRun, user: User, db: AsyncSession, *, note: str | None = None
) -> AgentRun:
    """Resume a paused, waiting or blocked run.

    A blocked run additionally requires that its wall is actually resolved, which
    is why this cannot simply set the status: "I fixed it" has to be checked
    against the graph rather than taken on trust.
    """
    status = parse_status(run.status)
    if status == AgentRunStatus.BLOCKED:
        await _assert_block_resolved(run, db)

    _set_status(run, AgentRunStatus.RUNNING)
    run.heartbeat_at = datetime.now(UTC)
    await _append_event(
        db,
        run,
        AgentEventType.RUN_RESUMED,
        "Agent run resumed.",
        metadata={"from_status": status.value, "note": note}
        if note
        else {"from_status": status.value},
    )
    await _audit_run(
        db,
        run,
        user,
        AuditEventType.AGENT_RUN_RESUMED,
        entity_type="agent_run",
        metadata={"from_status": status.value},
    )
    await db.flush()
    return run


async def _assert_block_resolved(run: AgentRun, db: AsyncSession) -> None:
    """Refuse to resume a blocked run whose cause is still present.

    Without this, "resume" would be a way to make the agent push through a wall
    it already reported it could not pass.
    """
    if run.plan_id is None:
        return
    plan = await db.get(AcademicWorkPlan, run.plan_id)
    if plan is None:
        raise AppError(409, "AGENT_PLAN_MISSING", "This run's plan no longer exists.")
    nodes = await _task_nodes(db, plan)
    if any(n.status == AcademicTaskStatus.BLOCKED.value for n in nodes):
        blocked = ", ".join(
            sorted(n.key for n in nodes if n.status == AcademicTaskStatus.BLOCKED.value)
        )
        raise AppError(
            409,
            "AGENT_STILL_BLOCKED",
            f"These tasks are still blocked: {blocked}.",
            {
                "blocked_tasks": [
                    n.key for n in nodes if n.status == AcademicTaskStatus.BLOCKED.value
                ]
            },
        )


async def cancel_run(
    run: AgentRun, user: User, db: AsyncSession, *, reason: str = "Cancelled by the student."
) -> AgentRun:
    """Cancel a run. Permitted from any non-terminal state, including waiting."""
    _set_status(run, AgentRunStatus.CANCELLED, reason=reason)
    # A pending checkpoint belongs to a run that no longer exists; leaving it
    # pending would show the student a question that will never be answered.
    await _resolve_open_checkpoints(
        db,
        run,
        user,
        resolution="The run was cancelled.",
        status_value=AgentCheckpointStatus.CANCELLED,
    )
    await _append_event(db, run, AgentEventType.RUN_CANCELLED, reason, metadata={"reason": reason})
    await _audit_run(
        db,
        run,
        user,
        AuditEventType.AGENT_RUN_CANCELLED,
        entity_type="agent_run",
        metadata={"reason": reason},
    )
    await db.flush()
    return run


async def _resolve_open_checkpoints(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    *,
    resolution: str,
    status_value: AgentCheckpointStatus = AgentCheckpointStatus.RESOLVED,
) -> list[AgentCheckpoint]:
    rows = list(
        await db.scalars(
            select(AgentCheckpoint).where(
                AgentCheckpoint.run_id == run.id,
                AgentCheckpoint.status == AgentCheckpointStatus.PENDING.value,
            )
        )
    )
    for row in rows:
        row.status = status_value.value
        row.response = resolution
        row.resolved_at = datetime.now(UTC)
        row.resolved_by_id = user.id
    if rows:
        await db.flush()
    return rows


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


async def _persist_artifact(
    db: AsyncSession,
    run: AgentRun,
    task: PlanTask | None,
    *,
    title: str,
    artifact_type: AgentArtifactType,
    content: str,
    metadata: Mapping[str, Any] | None = None,
    deliverable_key: str | None = None,
    user: User | None = None,
) -> AgentArtifact:
    """Persist an artifact, superseding any previous revision.

    Revisions accumulate rather than overwrite, because "what the run produced"
    and "what the student asked for instead" are different things and a plan that
    silently drops the first is not reviewable.
    """
    task_id = task.id if task else None
    revision = 1
    if task_id is not None:
        latest = await db.scalar(
            select(func.max(AgentArtifact.revision)).where(
                AgentArtifact.run_id == run.id, AgentArtifact.task_id == task_id
            )
        )
        revision = int(latest or 0) + 1
        previous = list(
            await db.scalars(
                select(AgentArtifact).where(
                    AgentArtifact.run_id == run.id,
                    AgentArtifact.task_id == task_id,
                    AgentArtifact.revision == revision - 1,
                )
            )
        )
        for old in previous:
            old.status = AgentArtifactStatus.SUPERSEDED.value

    artifact = AgentArtifact(
        run_id=run.id,
        task_id=task_id,
        title=title[:240],
        artifact_type=artifact_type.value,
        status=AgentArtifactStatus.DRAFT.value,
        content=content,
        metadata_json=dict(metadata or {}),
        revision=revision,
        deliverable_key=deliverable_key,
        created_by_id=user.id if user else run.triggered_by_id,
    )
    db.add(artifact)
    await db.flush()
    await _append_event(
        db,
        run,
        AgentEventType.ARTIFACT_CREATED,
        f"Created {artifact_type.value.lower().replace('_', ' ')} “{title[:120]}”.",
        metadata={"artifact_id": str(artifact.id), "revision": revision},
        task_id=task_id,
    )
    return artifact


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


async def _create_checkpoint(
    db: AsyncSession,
    run: AgentRun,
    *,
    question: str,
    checkpoint_type: AgentCheckpointType,
    task: PlanTask | None = None,
    context: str | None = None,
    options: Sequence[str] | None = None,
) -> AgentCheckpoint:
    """Persist a checkpoint and stop the run.

    The checkpoint is written in the same transaction as the status change, so a
    crash cannot produce a run that says "waiting for you" with no question, or a
    question with no run waiting on it.
    """
    limits = _limits_for(run)
    checkpoint = AgentCheckpoint(
        run_id=run.id,
        task_id=task.id if task else None,
        checkpoint_type=checkpoint_type.value,
        status=AgentCheckpointStatus.PENDING.value,
        question=question[:4_000],
        context=context[:4_000] if context else None,
        options=list(options) if options else None,
        expires_at=datetime.now(UTC) + timedelta(seconds=limits.checkpoint_ttl_seconds),
    )
    db.add(checkpoint)
    await db.flush()
    await _append_event(
        db,
        run,
        AgentEventType.CHECKPOINT_REQUESTED,
        f"Waiting for you: {question[:200]}",
        metadata={
            "checkpoint_id": str(checkpoint.id),
            "checkpoint_type": checkpoint_type.value,
            "options": list(options) if options else None,
        },
        task_id=checkpoint.task_id,
    )
    _set_status(
        run,
        AgentRunStatus.WAITING_FOR_USER,
        reason=f"{checkpoint_type.value.lower()}: {question[:200]}",
    )
    return checkpoint


async def pending_checkpoint(run: AgentRun, db: AsyncSession) -> AgentCheckpoint | None:
    stmt = (
        select(AgentCheckpoint)
        .where(
            AgentCheckpoint.run_id == run.id,
            AgentCheckpoint.status == AgentCheckpointStatus.PENDING.value,
        )
        .order_by(AgentCheckpoint.requested_at.desc())
        .limit(1)
    )
    return cast("AgentCheckpoint | None", await db.scalar(stmt))


async def resolve_checkpoint(
    checkpoint: AgentCheckpoint,
    run: AgentRun,
    user: User,
    db: AsyncSession,
    *,
    response: str | None = None,
    selected_option: str | None = None,
    approved: bool | None = None,
    retry: bool = False,
) -> AgentCheckpoint:
    """Resolve a checkpoint from the student's answer.

    The selected option is validated against what was actually offered. A client
    that submits an option the checkpoint never offered is either stale or wrong,
    and accepting it would put an unvetted value into the next context.
    """
    if checkpoint.status != AgentCheckpointStatus.PENDING.value:
        raise AppError(
            409,
            "AGENT_CHECKPOINT_ALREADY_RESOLVED",
            "This question has already been answered.",
            {"status": checkpoint.status},
        )
    if checkpoint.options and selected_option and selected_option not in checkpoint.options:
        raise AppError(
            422,
            "AGENT_CHECKPOINT_OPTION_UNKNOWN",
            "That option was not offered for this question.",
            {"available": checkpoint.options},
        )
    if checkpoint.checkpoint_type in {
        AgentCheckpointType.CLARIFICATION.value,
        AgentCheckpointType.MISSING_INFORMATION.value,
    } and not (response or selected_option):
        raise AppError(
            422,
            "AGENT_CHECKPOINT_ANSWER_REQUIRED",
            "This question needs an answer before the run can continue.",
        )
    if (
        checkpoint.checkpoint_type
        in {
            AgentCheckpointType.APPROVAL.value,
            AgentCheckpointType.REVIEW.value,
        }
        and approved is None
    ):
        raise AppError(
            422,
            "AGENT_CHECKPOINT_DECISION_REQUIRED",
            "Approve or reject so the run knows what to do next.",
        )

    checkpoint.status = AgentCheckpointStatus.RESOLVED.value
    checkpoint.response = response or selected_option or ("approved" if approved else "rejected")
    checkpoint.resolved_at = datetime.now(UTC)
    checkpoint.resolved_by_id = user.id
    await db.flush()

    await _append_event(
        db,
        run,
        AgentEventType.CHECKPOINT_RESOLVED,
        "You answered the agent's question.",
        metadata={
            "checkpoint_id": str(checkpoint.id),
            "approved": approved,
            "retry": retry,
        },
        task_id=checkpoint.task_id,
    )
    await _audit_run(
        db,
        run,
        user,
        AuditEventType.AGENT_CHECKPOINT_RESOLVED,
        entity_type="agent_checkpoint",
        entity_id=checkpoint.id,
        metadata={"approved": approved, "retry": retry},
    )

    # Answering the question is what unblocks the run. Without this the run stays
    # WAITING_FOR_USER forever: the question is resolved, but nothing is left
    # telling the runtime it may proceed, so the student's answer does nothing.
    if parse_status(run.status) is AgentRunStatus.WAITING_FOR_USER:
        _set_status(run, AgentRunStatus.RUNNING, reason=None)
        await _append_event(
            db,
            run,
            AgentEventType.RUN_RESUMED,
            "You answered the question, so the run is continuing.",
            metadata={"checkpoint_id": str(checkpoint.id), "retry": retry},
        )
        await _audit_run(
            db,
            run,
            user,
            AuditEventType.AGENT_RUN_RESUMED,
            entity_type="agent_run",
            metadata={"after_checkpoint": str(checkpoint.id)},
        )
    await db.flush()
    return checkpoint


# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Routing:
    model: str
    tier: str
    reason: str
    provider: LLMProvider | None


async def _route(
    db: AsyncSession,
    run: AgentRun,
    *,
    complexity_hint: str = "",
) -> _Routing:
    """Choose a model for this run and return a provider bound to it.

    The decision goes through the Phase 4 ``ModelRouter`` rather than picking a
    model here, so an agent run obeys exactly the same routing rules as analysis
    and planning. The one difference is that agent steps are run-scoped: a run
    that starts on the efficient tier stays there unless the router says
    otherwise, because switching mid-run would make the cost history unreadable.
    """
    from app.ai import build_llm_provider
    from app.ai.registry import ModelRegistry, ModelRouter

    complexity = ComplexityScore(level=_complexity_for(run), score=1.0, factors=[complexity_hint])
    registry = ModelRegistry(settings)
    selection = ModelRouter(registry).select(complexity)

    run.model = selection.model
    run.model_tier = selection.tier.value
    run.routing_reason = selection.reason[:300]

    provider: LLMProvider | None = None
    try:
        provider = build_llm_provider(settings, model=selection.model)
    except LLMUnavailableError:
        # A provider that cannot be built is not a routing failure. The run keeps
        # its routing decision and the step fails with a category the retry
        # policy understands, which is more informative than refusing to start.
        logger.warning("agent_provider_unavailable", extra={"model": selection.model})

    await _append_event(
        db,
        run,
        AgentEventType.MODEL_SELECTED,
        f"Using the {selection.tier.value.lower()} model for this step.",
        metadata={
            "model": selection.model,
            "tier": selection.tier.value,
            "reason": selection.reason,
            "confidence": selection.confidence,
        },
    )
    return _Routing(
        model=selection.model,
        tier=selection.tier.value,
        reason=selection.reason,
        provider=provider,
    )


def _complexity_for(run: AgentRun) -> ComplexityLevel:
    """Agent steps are treated as medium complexity by default.

    Deliberately conservative and uniform. Per-step complexity would need the
    task graph and the remaining budget, and getting it subtly wrong means either
    paying for the advanced tier on trivial steps or dropping requirements on hard
    ones. Phase 5 prefers the boring middle, and the ``complexity_hint`` is
    recorded as a routing factor so the decision stays auditable.
    """
    return ComplexityLevel.MEDIUM


# ---------------------------------------------------------------------------
# The execution loop
# ---------------------------------------------------------------------------


async def execute_run(
    run: AgentRun,
    user: User,
    db: AsyncSession,
    *,
    provider: LLMProvider | None = None,
    tools: ToolRegistry | None = None,
    executors: ExecutorRegistry | None = None,
    predictors: PredictorRegistry | None = None,
    max_steps: int | None = None,
) -> StepOutcome:
    """Drive a run until it stops.

    Runs steps inline and in one transaction per step, so a crash mid-run leaves a
    consistent database and a recoverable state. A background worker would be the
    natural next step, but doing it inline keeps the ordering guarantee simple:
    a step's persistence completes before the next one starts.

    ``max_steps`` bounds this call without touching the run's own budget, which is
    what lets a test drive a partial run and a later call continue it.
    """
    tool_registry = tools or DEFAULT_TOOLS
    executor_registry = executors or ExecutorRegistry()
    predictor_registry = predictors or PredictorRegistry()

    status = parse_status(run.status)
    if status in TERMINAL_STATUSES:
        raise AppError(409, "AGENT_RUN_FINISHED", "This run has already finished.")
    if status == AgentRunStatus.CREATED:
        _set_status(run, AgentRunStatus.STARTING)
        run.started_at = run.started_at or datetime.now(UTC)
    elif status in AWAITING_PERSON or status == AgentRunStatus.BLOCKED:
        raise AppError(
            409,
            "AGENT_RUN_NOT_RUNNABLE",
            "This run is waiting on you and cannot advance until you respond.",
            {"status": run.status, "paused_reason": run.paused_reason},
        )

    await _lock_run(run, db)
    # Re-entering a run that is already going is normal — a resumed step, or a
    # checkpoint answered moments ago. The state machine has no RUNNING -> RUNNING
    # edge on purpose, so treat that as the no-op it is instead of a contradiction.
    if status is not AgentRunStatus.RUNNING:
        _set_status(run, AgentRunStatus.RUNNING)

    if run.plan_id is None:
        return await _fail_run(
            db,
            run,
            user,
            code="AGENT_PLAN_MISSING",
            message="This run's plan no longer exists.",
            category=AgentFailureCategory.SYSTEM_ERROR,
        )

    plan = await db.get(AcademicWorkPlan, run.plan_id)
    if plan is None:
        return await _fail_run(
            db,
            run,
            user,
            code="AGENT_PLAN_MISSING",
            message="This run's plan no longer exists.",
            category=AgentFailureCategory.SYSTEM_ERROR,
        )
    assignment = await _assignment_for_plan(plan, db)

    limits = _limits_for(run)
    steps = max_steps if max_steps is not None else limits.max_iterations
    routing: _Routing | None = None
    if provider is not None:
        routing = _Routing(
            model="injected", tier="EFFICIENT", reason="Injected provider", provider=provider
        )

    for _ in range(steps):
        if parse_status(run.status) in TERMINAL_STATUSES | AWAITING_PERSON:
            break
        try:
            assert_iteration_budget(limits, run.iteration_count)
        except BudgetExceeded as exc:
            return await _fail_run(
                db,
                run,
                user,
                code=exc.code,
                message=exc.message,
                category=exc.category,
            )

        await _lock_run(run, db)
        run.iteration_count += 1

        nodes = await _task_nodes(db, plan)
        selection = select_next_task(nodes)
        if selection.task is None:
            return await _finish_run(
                db, run, user, selection, nodes, complete=not _has_unfinished(nodes)
            )

        advisory = advise(
            predictor_registry.features(nodes),
            selection=selection,
            executable=frozenset(selection.runnable_keys),
        )
        if advisory.suggestion is not None:
            # Recorded whether it was applied or discarded. A predictor that is
            # routinely overruled is a fact worth seeing, and one that is
            # routinely followed is a fact worth auditing.
            logger.info(
                "agent_prediction",
                extra={
                    "run_id": str(run.id),
                    "suggestion": advisory.suggestion,
                    "applied": advisory.applied,
                },
            )
        node = selection.task
        task = await _task_by_key(db, plan.id, node.key)

        if routing is None:
            routing = await _route(db, run, complexity_hint=node.type)
        active_provider = routing.provider or provider

        outcome = await _run_step(
            db,
            run,
            user,
            plan,
            assignment,
            task,
            node,
            nodes,
            active_provider,
            tool_registry,
            executor_registry,
            limits,
        )
        if outcome.kind != "ADVANCED":
            await db.commit()
            return outcome

    # Out of steps with work still to do. The loop knows it stopped, so it must
    # say so rather than leaving the run claiming to be RUNNING with no worker
    # behind it -- that state is indistinguishable from a crashed one until the
    # heartbeat expires, and a student watching it would wait for nothing.
    if parse_status(run.status) is AgentRunStatus.RUNNING:
        await _pause_run_internal(
            run,
            user,
            db,
            reason=(
                f"Paused after using the whole step budget ({run.max_iterations}). "
                "Resume to continue."
            ),
        )
    await db.commit()
    return StepOutcome(
        kind="STEP_LIMIT",
        run_status=parse_status(run.status),
        detail="Stopped after using the whole step budget.",
    )


async def _task_by_key(db: AsyncSession, plan_id: UUID, key: str) -> PlanTask | None:
    stmt = select(PlanTask).where(PlanTask.plan_id == plan_id, PlanTask.key == key)
    return cast("PlanTask | None", await db.scalar(stmt))


def _has_unfinished(nodes: Sequence[TaskNode]) -> bool:
    return any(
        n.status not in {AcademicTaskStatus.COMPLETED.value, AcademicTaskStatus.SKIPPED.value}
        for n in nodes
    )


async def _run_step(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    plan: AcademicWorkPlan,
    assignment: Assignment,
    task: PlanTask | None,
    node: TaskNode,
    nodes: Sequence[TaskNode],
    provider: LLMProvider | None,
    tools: ToolRegistry,
    executors: ExecutorRegistry,
    limits: AgentLimits,
) -> StepOutcome:
    """One iteration: select, build context, decide, act, record."""
    await _append_event(
        db,
        run,
        AgentEventType.TASK_SELECTED,
        f"Selected task {node.key}.",
        metadata={
            "task_key": node.key,
            "title": task.title if task else None,
            "priority": node.priority,
            "type": node.type,
        },
    )

    context = await _build_context(db, run, plan, assignment, task, node)
    await _append_event(
        db,
        run,
        AgentEventType.CONTEXT_BUILT,
        f"Assembled {context.total_chars} characters of context.",
        metadata={
            "chars": context.total_chars,
            "truncated": context.truncated,
            "digest": context.digest(),
        },
    )

    attempt = await _attempt_number(db, run, task)
    executor_kind = executors.executor_for_task(node.type)
    execution = AgentTaskExecution(
        run_id=run.id,
        task_id=task.id if task else uuid4(),
        task_key=node.key,
        attempt=attempt,
        status=AgentExecutionStatus.FAILED.value,
        executor=executor_kind.value,
        started_at=datetime.now(UTC),
    )
    db.add(execution)
    await db.flush()

    if task is not None and task.status == AcademicTaskStatus.PENDING.value:
        task.status = AcademicTaskStatus.IN_PROGRESS.value

    await _append_event(
        db,
        run,
        AgentEventType.TASK_STARTED,
        f"Working on {node.key} (attempt {attempt}).",
        metadata={"task_key": node.key, "attempt": attempt, "executor": executor_kind.value},
        task_id=task.id if task else None,
        execution_id=execution.id,
    )

    # ---- decide -------------------------------------------------------
    decision_raw: str
    if provider is None:
        decision_raw = json.dumps(
            {
                "action": AgentAction.MARK_BLOCKED.value,
                "task_key": node.key,
                "reason": "No model provider is configured for this deployment.",
                "confidence": 1.0,
                "blocked_reason": "No provider is available.",
            }
        )
    else:
        try:
            assert_cost_budget(
                limits,
                Decimal(str(run.estimated_cost)),
                Decimal(str(settings.agent_max_cost_per_step)) / 2,
            )
            response = await asyncio.wait_for(
                provider.complete(build_decision_request(context, registry=tools)),
                timeout=limits.step_timeout_seconds,
            )
            decision_raw = response.content
            execution.model = response.model
            execution.token_usage = response.usage.as_dict()
            _charge_run(run, response)
        except TimeoutError:
            return await _record_step_failure(
                db,
                run,
                user,
                execution,
                task,
                node,
                code="AGENT_STEP_TIMEOUT",
                message="The model did not respond in time.",
                category=AgentFailureCategory.TRANSIENT_PROVIDER,
            )
        except (LLMUnavailableError, LLMError) as exc:
            return await _record_step_failure(
                db,
                run,
                user,
                execution,
                task,
                node,
                code=getattr(exc, "code", "AGENT_PROVIDER_ERROR"),
                message=getattr(exc, "message", str(exc)),
                category=(
                    AgentFailureCategory.TRANSIENT_PROVIDER
                    if not isinstance(exc, LLMTimeoutError)
                    else AgentFailureCategory.TRANSIENT_PROVIDER
                ),
            )
        except BudgetExceeded as exc:
            return await _fail_run(
                db, run, user, code=exc.code, message=exc.message, category=exc.category
            )

    # ---- validate -----------------------------------------------------
    approval_keys = approval_required_keys(nodes)
    decision_ctx = DecisionContext(
        run_id=run.id,
        mode=AgentRunMode(run.mode),
        executable_task_keys=frozenset(select_next_task(nodes).runnable_keys),
        tasks={
            n.key: TaskView(
                key=n.key,
                status=n.status,
                position=n.position,
                depends_on=n.depends_on,
                acceptance_criteria=(),
            )
            for n in nodes
        },
        artifact_ids=frozenset(
            str(row)
            for row in await db.scalars(
                select(AgentArtifact.id).where(AgentArtifact.run_id == run.id)
            )
        ),
        approval_required_keys=approval_keys,
    )
    try:
        decision = parse_decision(decision_raw)
        validate_semantics(decision, decision_ctx)
        validate_permissions(decision, decision_ctx)
    except DecisionRejected as rejection:
        return await _record_step_failure(
            db,
            run,
            user,
            execution,
            task,
            node,
            code=rejection.code,
            message=rejection.message,
            category=AgentFailureCategory.VALIDATION_ERROR,
            validation_errors=rejection.errors,
            detail=f"rejected at the {rejection.layer} layer",
        )

    decision_row = AgentDecision(
        run_id=run.id,
        iteration=run.iteration_count,
        action=decision.action.value,
        reason=decision.reason,
        expected_output=decision.expected_output,
        confidence=decision.confidence,
        model=execution.model,
        model_tier=run.model_tier,
        payload={
            "task_key": decision.task_key,
            "artifact_type": decision.artifact_type.value if decision.artifact_type else None,
            "artifact_id": decision.artifact_id,
            "question": decision.question,
            "blocked_reason": decision.blocked_reason,
            "layer": "validated",
        },
    )
    db.add(decision_row)
    await db.flush()
    await _append_event(
        db,
        run,
        AgentEventType.DECISION_RECORDED,
        f"Decided to {decision.action.value.lower().replace('_', ' ')}.",
        metadata={"action": decision.action.value, "confidence": decision.confidence},
        task_id=task.id if task else None,
        execution_id=execution.id,
    )

    return await _apply_decision(
        db,
        run,
        user,
        plan,
        task,
        node,
        execution,
        decision,
        decision_row,
        context,
        provider,
        tools,
        executors,
        limits,
    )


async def _build_context(
    db: AsyncSession,
    run: AgentRun,
    plan: AcademicWorkPlan,
    assignment: Assignment,
    task: PlanTask | None,
    node: TaskNode,
) -> AgentContext:
    """Assemble the bounded context for this step.

    Pulls requirements, constraints and prior artifacts from the plan and this
    run so a task carries what it needs without re-reading the whole assignment.
    """
    requirement_links = (
        list(
            await db.scalars(
                select(PlanTaskRequirement).where(
                    PlanTaskRequirement.task_id == (task.id if task else None)
                )
            )
        )
        if task is not None
        else []
    )
    dependencies = (
        list(
            await db.scalars(
                select(PlanTaskDependency).where(
                    PlanTaskDependency.plan_id == plan.id,
                    PlanTaskDependency.successor_id == (task.id if task else None),
                )
            )
        )
        if task is not None
        else []
    )

    predecessor_titles: dict[str, str] = {}
    if dependencies:
        ids = [d.predecessor_id for d in dependencies]
        for row in await db.scalars(select(PlanTask).where(PlanTask.id.in_(ids))):
            predecessor_titles[row.key] = row.title

    prior_artifacts = [
        (a.title, a.content[:4_000])
        for a in await db.scalars(
            select(AgentArtifact)
            .where(AgentArtifact.run_id == run.id)
            .order_by(AgentArtifact.revision)
        )
        if task is None or a.task_id is None or a.task_id == task.id
    ]

    return assemble_context(
        run_id=run.id,
        task_key=node.key,
        task_title=task.title if task else node.key,
        task_description=task.description if task else "",
        task_type=node.type,
        acceptance_criteria=tuple(task.acceptance_criteria) if task else (),
        dependencies=[(key, title) for key, title in predecessor_titles.items()],
        requirements=[(link.requirement_key, "") for link in requirement_links],
        constraints=[],
        prior_artifacts=prior_artifacts,
        assignment_title=assignment.title,
        plan_title=plan.title,
        max_chars=settings.agent_max_context_chars,
    )


async def _attempt_number(db: AsyncSession, run: AgentRun, task: PlanTask | None) -> int:
    """Next attempt number for a task in this run.

    Derived from stored attempts rather than a counter column, so a restart cannot
    reset it and reuse attempt 1.
    """
    if task is None:
        return 1
    highest = await db.scalar(
        select(func.max(AgentTaskExecution.attempt)).where(
            AgentTaskExecution.run_id == run.id,
            AgentTaskExecution.task_id == task.id,
        )
    )
    return int(highest or 0) + 1


async def _record_step_failure(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    execution: AgentTaskExecution,
    task: PlanTask | None,
    node: TaskNode,
    *,
    code: str,
    message: str,
    category: AgentFailureCategory,
    validation_errors: list[dict[str, Any]] | None = None,
    detail: str | None = None,
) -> StepOutcome:
    """Persist a failed attempt and decide whether to retry it."""
    started = execution.started_at
    execution.status = AgentExecutionStatus.FAILED.value
    execution.failure_category = category.value
    execution.error_code = code
    execution.error_message = message[:4_000]
    execution.validation_errors = validation_errors
    execution.completed_at = datetime.now(UTC)
    if started is not None:
        execution.duration_ms = int((execution.completed_at - started).total_seconds() * 1000)
    await db.flush()

    await _append_event(
        db,
        run,
        AgentEventType.TASK_FAILED,
        f"Attempt {execution.attempt} at {node.key} failed: {message[:200]}",
        metadata={
            "task_key": node.key,
            "attempt": execution.attempt,
            "category": category.value,
            "code": code,
            "detail": detail,
        },
        task_id=task.id if task else None,
        execution_id=execution.id,
    )

    limits = _limits_for(run)
    consecutive = await _consecutive_failures(db, run)
    if may_retry(limits, execution.attempt, consecutive):
        if task is not None:
            task.status = AcademicTaskStatus.PENDING.value
        await _append_event(
            db,
            run,
            AgentEventType.TASK_RETRIED,
            f"Retrying {node.key}.",
            metadata={"task_key": node.key, "next_attempt": execution.attempt + 1},
            task_id=task.id if task else None,
        )
        return StepOutcome(kind="ADVANCED", run_status=AgentRunStatus.RUNNING, task_key=node.key)

    if task is not None:
        task.status = AcademicTaskStatus.BLOCKED.value
    _set_status(run, AgentRunStatus.BLOCKED, reason=f"{node.key}: {message[:200]}")
    await _append_event(
        db,
        run,
        AgentEventType.TASK_BLOCKED,
        f"{node.key} is blocked: {message[:200]}",
        metadata={"task_key": node.key, "category": category.value},
        task_id=task.id if task else None,
    )
    await db.flush()
    return StepOutcome(
        kind="BLOCKED",
        run_status=AgentRunStatus.BLOCKED,
        detail=message,
        task_key=node.key,
    )


async def _consecutive_failures(db: AsyncSession, run: AgentRun) -> int:
    """How many attempts in a row have failed, ignoring successes.

    Counted from the execution ledger rather than kept on the run row so it is
    correct after a crash that lost the counter.
    """
    rows = list(
        await db.scalars(
            select(AgentTaskExecution.status)
            .where(AgentTaskExecution.run_id == run.id)
            .order_by(AgentTaskExecution.started_at.desc())
            .limit(settings.agent_max_consecutive_failures + 1)
        )
    )
    streak = 0
    for status in rows:
        if status in {
            AgentExecutionStatus.SUCCESS.value,
            AgentExecutionStatus.PARTIAL_SUCCESS.value,
        }:
            break
        streak += 1
    return streak


async def _apply_decision(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    plan: AcademicWorkPlan,
    task: PlanTask | None,
    node: TaskNode,
    execution: AgentTaskExecution,
    decision: Any,
    decision_row: AgentDecision,
    context: AgentContext,
    provider: LLMProvider | None,
    tools: ToolRegistry,
    executors: ExecutorRegistry,
    limits: AgentLimits,
) -> StepOutcome:
    """Act on a validated decision."""
    action = decision.action

    if action == AgentAction.PAUSE_RUN:
        await _pause_run_internal(run, user, db, reason=decision.reason)
        return StepOutcome(
            kind="PAUSED",
            run_status=AgentRunStatus.PAUSED,
            detail=decision.reason,
            decision_action=action,
        )

    if action in {AgentAction.ASK_USER, AgentAction.REQUEST_APPROVAL}:
        checkpoint_type = decision.checkpoint_type or (
            AgentCheckpointType.APPROVAL
            if action == AgentAction.REQUEST_APPROVAL
            else AgentCheckpointType.CLARIFICATION
        )
        await _close_execution(
            db, execution, AgentExecutionStatus.NEEDS_USER_INPUT, decision.reason
        )
        checkpoint = await _create_checkpoint(
            db,
            run,
            question=decision.question or decision.reason,
            checkpoint_type=checkpoint_type,
            task=task,
            context=decision.expected_output,
            options=decision.checkpoint_options,
        )
        decision_row.outcome = "WAITING_FOR_USER"
        await db.flush()
        return StepOutcome(
            kind="WAITING",
            run_status=AgentRunStatus.WAITING_FOR_USER,
            detail=decision.reason,
            checkpoint_id=checkpoint.id,
            decision_action=action,
            task_key=node.key,
        )

    if action == AgentAction.MARK_BLOCKED:
        await _close_execution(db, execution, AgentExecutionStatus.BLOCKED, decision.reason)
        if task is not None:
            task.status = AcademicTaskStatus.BLOCKED.value
        reason = decision.blocked_reason or decision.reason
        _set_status(run, AgentRunStatus.BLOCKED, reason=f"{node.key}: {reason[:200]}")
        decision_row.outcome = "BLOCKED"
        await _append_event(
            db,
            run,
            AgentEventType.TASK_BLOCKED,
            f"{node.key} is blocked: {reason[:200]}",
            metadata={"task_key": node.key, "reason": reason},
            task_id=task.id if task else None,
            execution_id=execution.id,
        )
        await db.flush()
        return StepOutcome(
            kind="BLOCKED",
            run_status=AgentRunStatus.BLOCKED,
            detail=reason,
            decision_action=action,
            task_key=node.key,
        )

    if action == AgentAction.RETRY_TASK:
        return await _record_step_failure(
            db,
            run,
            user,
            execution,
            task,
            node,
            code="AGENT_RETRY_REQUESTED",
            message=decision.reason,
            category=AgentFailureCategory.TRANSIENT_PROVIDER,
            detail="the agent asked for another attempt",
        )

    if action == AgentAction.COMPLETE_TASK:
        # Completion is a bookkeeping step, not a unit of work. Running the
        # executor here would mint a second draft for a task that already has one,
        # so the artifact count would report progress that never happened.
        await _close_execution(db, execution, AgentExecutionStatus.SUCCESS, decision.reason)
        decision_row.outcome = "TASK_COMPLETED"
        if task is not None:
            task.status = AcademicTaskStatus.COMPLETED.value
            await _append_event(
                db,
                run,
                AgentEventType.TASK_COMPLETED,
                f"Completed {node.key}.",
                metadata={"task_key": node.key},
                task_id=task.id,
                execution_id=execution.id,
            )
            await _audit_run(
                db,
                run,
                user,
                AuditEventType.AGENT_TASK_COMPLETED,
                entity_type="plan_task",
                entity_id=task.id,
                metadata={"task_key": node.key},
            )
        await db.flush()
        return StepOutcome(
            kind="ADVANCED",
            run_status=AgentRunStatus.RUNNING,
            detail=decision.reason,
            task_key=node.key,
            decision_action=action,
        )

    if action in {
        AgentAction.EXECUTE_TASK,
        AgentAction.CREATE_ARTIFACT,
        AgentAction.UPDATE_ARTIFACT,
    }:
        # Every action that produces work goes through the executor. The decision
        # may choose the artifact's title and type, but never its body: model text
        # is untrusted input, and a draft is a claim the executor stands behind.
        return await _execute_and_finish(
            db,
            run,
            user,
            task,
            node,
            execution,
            decision,
            decision_row,
            context,
            provider,
            executors,
            limits,
            complete=False,
            title=decision.artifact_title,
            artifact_type=decision.artifact_type,
        )

    # REVIEW_RESULT: record the observation and let the loop continue.
    await _close_execution(db, execution, AgentExecutionStatus.PARTIAL_SUCCESS, decision.reason)
    decision_row.outcome = "REVIEWED"
    await db.flush()
    return StepOutcome(
        kind="ADVANCED",
        run_status=AgentRunStatus.RUNNING,
        detail=decision.reason,
        decision_action=action,
        task_key=node.key,
    )


async def _artifact_revisions(db: AsyncSession, run: AgentRun, task: PlanTask | None) -> int:
    """How many drafts this run has already produced for one task."""
    if task is None:
        return 0
    total = await db.scalar(
        select(func.count())
        .select_from(AgentArtifact)
        .where(AgentArtifact.run_id == run.id, AgentArtifact.task_id == task.id)
    )
    return int(total or 0)


def _charge_run(run: AgentRun, response: LLMResponse) -> None:
    """Add one provider call's usage to the run's totals.

    Charged from what the provider actually reports rather than from a fraction of
    the configured limit. A budget checked against estimated numbers is a budget
    that stops being believed the first time it is wrong, and a run that claims a
    cost it did not incur cannot be audited afterwards.
    """
    totals = dict(run.token_usage or {})
    for key, value in response.usage.as_dict().items():
        totals[key] = int(totals.get(key, 0)) + int(value)
    run.token_usage = totals
    if response.estimated_cost:
        run.estimated_cost = Decimal(str(run.estimated_cost)) + Decimal(
            str(response.estimated_cost)
        )


async def _close_execution(
    db: AsyncSession,
    execution: AgentTaskExecution,
    status: AgentExecutionStatus,
    reason: str,
) -> None:
    """Finish an execution row, accounting for its cost and duration."""
    execution.status = status.value
    execution.summary = reason[:1_000]
    execution.completed_at = datetime.now(UTC)
    if execution.started_at is not None:
        execution.duration_ms = int(
            (execution.completed_at - execution.started_at).total_seconds() * 1000
        )
    await db.flush()


async def _execute_and_finish(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    task: PlanTask | None,
    node: TaskNode,
    execution: AgentTaskExecution,
    decision: Any,
    decision_row: AgentDecision,
    context: AgentContext,
    provider: LLMProvider | None,
    executors: ExecutorRegistry,
    limits: AgentLimits,
    *,
    complete: bool,
    title: str | None = None,
    artifact_type: AgentArtifactType | None = None,
) -> StepOutcome:
    """Run the executor and record what it produced."""
    kind = executors.executor_for_task(node.type)
    execution.executor = kind.value

    if provider is None:
        result = await executors.get(kind).execute(
            ExecutionRequest(
                run_id=run.id,
                task_id=execution.task_id,
                task_key=node.key,
                task_type=node.type,
                task_title=task.title if task else node.key,
                task_description=task.description if task else "",
                acceptance_criteria=tuple(task.acceptance_criteria) if task else (),
                attempt=execution.attempt,
            )
        )
    else:
        try:
            response = await asyncio.wait_for(
                provider.complete(
                    build_execution_request(
                        context,
                        task_title=task.title if task else node.key,
                        task_type=node.type,
                    )
                ),
                timeout=limits.step_timeout_seconds,
            )
            payload = parse_execution_output(response.content)
            # A provider asked for work product may answer with JSON or with prose.
            # Both are usable: the prose *is* the work product, so it becomes the
            # artifact body rather than being discarded as unparseable. Returning
            # nothing here would silently end every provider-driven run with zero
            # artifacts, which is the product's actual output.
            content = str(payload.get("content") or "").strip() or response.content.strip()
            result = ExecutionResult(
                status=AgentExecutionStatus.SUCCESS,
                summary=str(payload.get("summary") or f"Produced work for {node.key}."),
                output=payload,
                artifact=ArtifactDraft(
                    title=task.title if task else node.key,
                    artifact_type=artifact_type or artifact_type_for_task(node.type),
                    content=content,
                ),
            )
            execution.model = response.model
            execution.token_usage = response.usage.as_dict()
            _charge_run(run, response)
        except (TimeoutError, LLMError):
            return await _record_step_failure(
                db,
                run,
                user,
                execution,
                task,
                node,
                code="AGENT_EXECUTION_PROVIDER_ERROR",
                message="The model failed while producing the work product.",
                category=AgentFailureCategory.TRANSIENT_PROVIDER,
            )

    if not result.succeeded:
        await _close_execution(db, execution, result.status, result.summary)
        decision_row.outcome = "EXECUTION_FAILED"
        return await _record_step_failure(
            db,
            run,
            user,
            execution,
            task,
            node,
            code=result.error_code or "AGENT_EXECUTION_FAILED",
            message=result.summary,
            category=result.failure_category or AgentFailureCategory.SYSTEM_ERROR,
        )

    artifact_id: UUID | None = None
    if result.artifact is not None:
        # A model that keeps drafting without ever completing the task is
        # spinning, not working. Revisions accumulate so nothing is lost, but
        # spending the whole step budget on one task would quietly cost the
        # student real money for no additional value. After the cap, ask.
        existing = await _artifact_revisions(db, run, task)
        if existing >= MAX_REVISIONS_PER_TASK:
            await _close_execution(db, execution, AgentExecutionStatus.SUCCESS, result.summary)
            decision_row.outcome = "REVISION_LIMIT_REACHED"
            await _create_checkpoint(
                db,
                run,
                checkpoint_type=AgentCheckpointType.REVIEW,
                task=task,
                question=(
                    f"I have drafted {node.key} {existing} times without finishing it. "
                    "Would you like me to keep revising, move on, or stop?"
                ),
                context=(
                    "Repeated drafting usually means the task is missing information "
                    "rather than that another pass will fix it."
                ),
                options=["Keep revising", "Move on and leave the draft", "Stop this run"],
            )
            await db.flush()
            return StepOutcome(
                kind="WAITING",
                run_status=AgentRunStatus.WAITING_FOR_USER,
                detail=f"{node.key} has been drafted {existing} times.",
                task_key=node.key,
                decision_action=decision.action,
            )
        try:
            assert_artifact_budget(
                limits,
                await db.scalar(
                    select(func.count())
                    .select_from(AgentArtifact)
                    .where(AgentArtifact.run_id == run.id)
                )
                or 0,
            )
            artifact = await _persist_artifact(
                db,
                run,
                task,
                title=title or result.artifact.title,
                artifact_type=artifact_type or result.artifact.artifact_type,
                content=result.artifact.content,
                metadata=result.artifact.metadata,
                deliverable_key=result.artifact.deliverable_key,
                user=user,
            )
            artifact_id = artifact.id
        except BudgetExceeded as exc:
            return await _fail_run(
                db, run, user, code=exc.code, message=exc.message, category=exc.category
            )

    await _close_execution(db, execution, AgentExecutionStatus.SUCCESS, result.summary)
    execution.output = result.output

    if complete and task is not None:
        task.status = AcademicTaskStatus.COMPLETED.value
        decision_row.outcome = "TASK_COMPLETED"
        await _append_event(
            db,
            run,
            AgentEventType.TASK_COMPLETED,
            f"Completed {node.key}.",
            metadata={
                "task_key": node.key,
                "artifact_id": str(artifact_id) if artifact_id else None,
            },
            task_id=task.id,
            execution_id=execution.id,
        )
        await _audit_run(
            db,
            run,
            user,
            AuditEventType.AGENT_TASK_COMPLETED,
            entity_type="plan_task",
            entity_id=task.id,
            metadata={"task_key": node.key},
        )
    else:
        decision_row.outcome = "TASK_EXECUTED"

    await db.flush()
    return StepOutcome(
        kind="ADVANCED",
        run_status=AgentRunStatus.RUNNING,
        detail=result.summary,
        task_key=node.key,
        artifact_id=artifact_id,
        decision_action=decision.action,
    )


# ---------------------------------------------------------------------------
# Terminal transitions
# ---------------------------------------------------------------------------


async def _fail_run(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    *,
    code: str,
    message: str,
    category: AgentFailureCategory,
) -> StepOutcome:
    """Fail a run with an explanation a student can act on.

    Pending checkpoints are closed, because a failed run will never answer them
    and a question that will never be answered is worse than no question.
    """
    run.error_code = code
    run.error_message = message[:4_000]
    run.error_category = category.value
    _set_status(run, AgentRunStatus.FAILED, reason=message[:200])
    if run.started_at is not None:
        run.duration_ms = int((datetime.now(UTC) - run.started_at).total_seconds() * 1000)
    await _resolve_open_checkpoints(
        db, run, user, resolution="The run failed before this was answered."
    )
    await _append_event(
        db,
        run,
        AgentEventType.RUN_FAILED,
        message[:400],
        metadata={"code": code, "category": category.value},
    )
    await _audit_run(
        db,
        run,
        user,
        AuditEventType.AGENT_RUN_FAILED,
        entity_type="agent_run",
        metadata={"code": code, "category": category.value},
    )
    await db.flush()
    return StepOutcome(kind="FAILED", run_status=AgentRunStatus.FAILED, detail=message)


async def _pause_run_internal(
    run: AgentRun, user: User, db: AsyncSession, *, reason: str
) -> AgentRun:
    _set_status(run, AgentRunStatus.PAUSED, reason=reason)
    await _append_event(db, run, AgentEventType.RUN_PAUSED, reason, metadata={"reason": reason})
    await _audit_run(
        db,
        run,
        user,
        AuditEventType.AGENT_RUN_PAUSED,
        entity_type="agent_run",
        metadata={"reason": reason},
    )
    await db.flush()
    return run


async def _finish_run(
    db: AsyncSession,
    run: AgentRun,
    user: User,
    selection: Selection,
    nodes: Sequence[TaskNode],
    *,
    complete: bool,
) -> StepOutcome:
    """Complete or block a run depending on whether work actually remains."""
    counts = progress(nodes)
    if complete:
        _set_status(run, AgentRunStatus.COMPLETED, reason=None)
        if run.started_at is not None:
            run.duration_ms = int((datetime.now(UTC) - run.started_at).total_seconds() * 1000)
        if run.plan_id is not None:
            plan = await db.get(AcademicWorkPlan, run.plan_id)
            if plan is not None and plan.status in {
                "IN_PROGRESS",
                "APPROVED",
                "DRAFT",
                "READY_FOR_REVIEW",
            }:
                from app.models.enums import PlanStatus

                plan.status = PlanStatus.COMPLETED.value
        await _append_event(
            db,
            run,
            AgentEventType.RUN_COMPLETED,
            f"Completed {counts['completed']} of {counts['total']} tasks.",
            metadata=counts,
        )
        await _audit_run(
            db,
            run,
            user,
            AuditEventType.AGENT_RUN_COMPLETED,
            entity_type="agent_run",
            metadata=counts,
        )
        await db.flush()
        return StepOutcome(
            kind="COMPLETED",
            run_status=AgentRunStatus.COMPLETED,
            detail=f"Completed {counts['completed']} tasks.",
        )

    reason = selection.blocked_reason or "No task is executable."
    _set_status(run, AgentRunStatus.BLOCKED, reason=reason[:200])
    await _append_event(db, run, AgentEventType.TASK_BLOCKED, reason[:400], metadata=counts)
    await db.flush()
    return StepOutcome(kind="BLOCKED", run_status=AgentRunStatus.BLOCKED, detail=reason)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


async def load_run_detail(run: AgentRun, db: AsyncSession) -> dict[str, Any]:
    """Assemble everything the workspace needs in a fixed number of queries."""
    from app.schemas.agent import (
        AgentArtifactResponse,
        AgentCheckpointResponse,
        AgentDecisionResponse,
        AgentEventResponse,
        AgentExecutionResponse,
        AgentTaskResponse,
    )

    tasks: list[AgentTaskResponse] = []
    nodes: tuple[TaskNode, ...] = ()
    if run.plan_id is not None:
        plan = await db.get(AcademicWorkPlan, run.plan_id)
        if plan is not None:
            nodes = await _task_nodes(db, plan)
        approval_keys = approval_required_keys(nodes)
        for node in nodes:
            row = await _task_by_key(db, run.plan_id, node.key)
            if row is None:
                continue
            rows = list(
                await db.scalars(
                    select(AgentTaskExecution)
                    .where(
                        AgentTaskExecution.run_id == run.id,
                        AgentTaskExecution.task_id == row.id,
                    )
                    .order_by(AgentTaskExecution.attempt)
                )
            )
            latest = rows[-1] if rows else None
            artifact_ids = [a.id for a in run.artifacts if a.task_id == row.id]
            tasks.append(
                AgentTaskResponse(
                    id=row.id,
                    key=row.key,
                    title=row.title,
                    type=row.type,
                    status=row.status,
                    priority=row.priority,
                    position=row.position,
                    attempted=bool(rows),
                    attempts=len(rows),
                    last_status=latest.status if latest else None,
                    last_summary=latest.summary if latest else None,
                    artifact_ids=artifact_ids,
                    can_auto_complete=row.key not in approval_keys,
                )
            )

    executions = [
        AgentExecutionResponse.model_validate(row)
        for row in sorted(
            await db.scalars(
                select(AgentTaskExecution)
                .where(AgentTaskExecution.run_id == run.id)
                .order_by(AgentTaskExecution.started_at)
            ),
            key=lambda r: r.started_at,
        )
    ]
    artifacts = [AgentArtifactResponse.model_validate(a) for a in run.artifacts]
    checkpoints = [
        AgentCheckpointResponse.model_validate(c)
        for c in sorted(run.checkpoints, key=lambda c: c.requested_at)
    ]
    events = [
        AgentEventResponse.model_validate(e)
        for e in sorted(run.events, key=lambda e: (e.sequence, e.created_at))
    ]
    decisions = [
        AgentDecisionResponse.model_validate(d)
        for d in sorted(run.decisions, key=lambda d: d.iteration)
    ]

    status = parse_status(run.status)
    pending = await pending_checkpoint(run, db)
    counts = progress(nodes) if nodes else None

    return {
        "id": run.id,
        "assignment_id": run.assignment_id,
        "plan_id": run.plan_id,
        "plan_version": run.plan_version,
        "status": status,
        "mode": run.mode,
        "paused_reason": run.paused_reason,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "error_category": run.error_category,
        "model": run.model,
        "model_tier": run.model_tier,
        "routing_reason": run.routing_reason,
        "iteration_count": run.iteration_count,
        "max_iterations": run.max_iterations,
        "max_cost": float(run.max_cost),
        "estimated_cost": float(run.estimated_cost),
        "token_usage": run.token_usage,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_ms": run.duration_ms,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "progress": counts,
        "awaiting_checkpoint_id": pending.id if pending else None,
        "can_resume": status
        in {AgentRunStatus.PAUSED, AgentRunStatus.WAITING_FOR_USER, AgentRunStatus.BLOCKED},
        "can_retry": status == AgentRunStatus.FAILED,
        "tasks": tasks,
        "executions": executions,
        "artifacts": artifacts,
        "checkpoints": checkpoints,
        "events": events,
        "decisions": decisions,
        "context_provenance": [],
    }


RUN_LOADERS = (
    selectinload(AgentRun.executions),
    selectinload(AgentRun.artifacts),
    selectinload(AgentRun.checkpoints),
    selectinload(AgentRun.events),
    selectinload(AgentRun.decisions),
)


async def load_run_with_details(
    assignment_id: UUID, run_id: UUID, user_id: UUID, db: AsyncSession
) -> AgentRun:
    """Load a run with the collections the detail response needs."""
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.assignment_id == assignment_id)
        .options(*RUN_LOADERS)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise AppError(404, "AGENT_RUN_NOT_FOUND", "Agent run not found.")
    return run
