"""Application service for the Academic Planning Engine.

This module owns the things a plan needs to be trustworthy over time:

* **Versioning.** A plan is never overwritten. Regeneration creates a new version
  and the previous one stays readable, so "what did I approve" always has an
  answer.
* **Human review.** A plan is a draft until a person approves it. Approval is
  recorded with who and when, and an approved plan becomes immutable — the way to
  change it is to regenerate, which leaves a trail.
* **Partial regeneration.** Re-planning must not destroy work the student did by
  hand. Tasks marked ``is_user_authored`` are carried across, and the sections
  that actually changed are recorded on the new version.
* **Staleness.** When the analysis moves, plans built on the old one are marked
  stale rather than silently reused.

Authoritative specification and analysis tables are read-only from here. This
module only ever writes planning tables.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import (
    AcademicWorkPlan,
    Assignment,
    AssignmentAnalysis,
    PlanMilestone,
    PlanningPreference,
    PlanningRun,
    PlanTask,
    PlanTaskDeliverable,
    PlanTaskDependency,
    PlanTaskRequirement,
)
from app.models.enums import (
    AcademicTaskPriority,
    AcademicTaskStatus,
    AcademicTaskType,
    ComplexityLevel,
    EffortLevel,
    GuidanceLevel,
    ModelTier,
    PlanningRunStatus,
    PlanningStyle,
    PlanStatus,
    PlanTrigger,
)
from app.modules.planning.graph import (
    PlanGraphError,
    ValidatedGraph,
    validate_edited_graph,
)
from app.modules.planning.planner import (
    PlanningPreferences,
    build_planning_preferences,
)
from app.schemas.analysis import PlanningContractResponse
from app.schemas.planning import (
    MilestoneResponse,
    PlannedTask,
    PlannerOutput,
    PlanRiskResponse,
    PlanSummaryResponse,
    ScheduleRiskResponse,
    TaskResponse,
    VerificationPointResponse,
    WorkPlanResponse,
)

#: Plan states a student may still edit. An approved plan is immutable.
EDITABLE_STATUSES = frozenset({PlanStatus.DRAFT, PlanStatus.READY_FOR_REVIEW, PlanStatus.STALE})

#: Sections recorded on a new version when a regeneration changed them.
SECTION_TASKS = "tasks"
SECTION_MILESTONES = "milestones"
SECTION_TRACEABILITY = "traceability"
SECTION_EFFORT = "effort"


# ---------------------------------------------------------------------------
# Loading and ownership
# ---------------------------------------------------------------------------


async def load_owned_plan(
    assignment_id: UUID, plan_id: UUID, user_id: UUID, db: AsyncSession
) -> AcademicWorkPlan:
    """Load a plan the caller is allowed to see, or 404.

    Ownership is checked through the assignment and workspace, exactly as the
    assignment service does. A plan id the caller cannot see returns 404 rather
    than 403, so the API does not confirm that the id exists.
    """
    from app.modules.assignments.service import load_owned_assignment

    await load_owned_assignment(assignment_id, user_id, db)
    plan = await db.get(AcademicWorkPlan, plan_id, options=[selectinload(AcademicWorkPlan.tasks)])
    if plan is None or plan.assignment_id != assignment_id:
        raise AppError(404, "PLAN_NOT_FOUND", "That plan does not exist.")
    return plan


async def latest_plan(
    assignment_id: UUID, db: AsyncSession, *, include_draft: bool = True
) -> AcademicWorkPlan | None:
    """The newest plan version for an assignment."""
    stmt = select(AcademicWorkPlan).where(AcademicWorkPlan.assignment_id == assignment_id)
    if not include_draft:
        stmt = stmt.where(AcademicWorkPlan.status != PlanStatus.DRAFT.value)
    stmt = stmt.order_by(AcademicWorkPlan.version.desc()).limit(1)
    plan: AcademicWorkPlan | None = await db.scalar(stmt)
    return plan


async def list_plan_versions(
    assignment_id: UUID, db: AsyncSession, *, limit: int = 50
) -> list[AcademicWorkPlan]:
    stmt = (
        select(AcademicWorkPlan)
        .where(AcademicWorkPlan.assignment_id == assignment_id)
        .order_by(AcademicWorkPlan.version.desc())
        .limit(limit)
    )
    found: list[AcademicWorkPlan] = list(await db.scalars(stmt))
    return found


async def approved_plan(assignment_id: UUID, db: AsyncSession) -> AcademicWorkPlan | None:
    """The approved plan, if there is one. This is the authoritative schedule."""
    stmt = (
        select(AcademicWorkPlan)
        .where(
            AcademicWorkPlan.assignment_id == assignment_id,
            AcademicWorkPlan.status == PlanStatus.APPROVED.value,
        )
        .order_by(AcademicWorkPlan.version.desc())
        .limit(1)
    )
    plan: AcademicWorkPlan | None = await db.scalar(stmt)
    return plan


async def load_preferences(workspace_id: UUID, db: AsyncSession) -> PlanningPreference:
    """Workspace planning preferences, created with defaults on first use."""
    preference = await db.get(PlanningPreference, workspace_id)
    if preference is None:
        preference = PlanningPreference(workspace_id=workspace_id)
        db.add(preference)
        await db.flush()
    return preference


async def resolve_preferences(
    workspace_id: UUID,
    db: AsyncSession,
    *,
    style: Any = None,
    guidance: Any = None,
    session_length: Any = None,
    ai_mode: Any = None,
) -> tuple[PlanningPreferences, Any]:
    """Merge stored preferences with per-request overrides.

    A request that specifies nothing uses the workspace's stored preferences, so
    the choice a student made once keeps applying.
    """
    stored = await load_preferences(workspace_id, db)
    preferences = build_planning_preferences(
        style or PlanningStyle(stored.planning_style),
        guidance or GuidanceLevel(stored.guidance_level),
        None if session_length is None else _session_minutes(session_length),
    )
    return preferences, (ai_mode or stored.ai_mode)


def _session_minutes(session_length: Any) -> int:
    return {"SHORT": 25, "MEDIUM": 45, "LONG": 90}.get(
        getattr(session_length, "value", session_length), 45
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def plan_idempotency_key(
    *,
    assignment_id: str,
    analysis_revision: int,
    prompt_version: str,
    provider: str,
    model: str,
    style: str,
    guidance: str,
) -> str:
    """A stable key for "this exact planning request".

    Covers everything that changes the output. A repeated identical request
    returns the existing plan instead of paying for a second run, which is what
    makes the generate endpoint safe to retry.
    """
    material = "|".join(
        [
            assignment_id,
            str(analysis_revision),
            prompt_version,
            provider,
            model,
            style,
            guidance,
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def _next_version(assignment_id: UUID, db: AsyncSession) -> int:
    current = await db.scalar(
        select(func.max(AcademicWorkPlan.version)).where(
            AcademicWorkPlan.assignment_id == assignment_id
        )
    )
    return int(current or 0) + 1


async def start_run(
    db: AsyncSession,
    *,
    assignment: Assignment,
    analysis: AssignmentAnalysis | None,
    user_id: UUID,
    idempotency_key: str,
    provider: str,
    model: str,
    model_tier: ModelTier,
    routing_reason: str,
    routing_confidence: float,
    complexity: ComplexityLevel,
    prompt_version: str,
) -> PlanningRun:
    """Record the intent to plan, before any model call.

    Written first so a crash mid-generation leaves evidence that a run was
    attempted, rather than a plan that appeared with no provenance.
    """
    run = PlanningRun(
        assignment_id=assignment.id,
        analysis_revision=analysis.revision if analysis is not None else None,
        triggered_by_id=user_id,
        idempotency_key=idempotency_key,
        status=PlanningRunStatus.RUNNING.value,
        provider=provider,
        model=model,
        model_tier=model_tier.value,
        routing_reason=routing_reason,
        routing_confidence=routing_confidence,
        complexity=complexity.value,
        prompt_version=prompt_version,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


async def finish_run(
    db: AsyncSession,
    run: PlanningRun,
    *,
    status: PlanningRunStatus,
    plan: AcademicWorkPlan | None = None,
    duration_ms: int | None = None,
    token_usage: dict[str, Any] | None = None,
    estimated_cost: float | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    output_hash: str | None = None,
    fell_back_from_tier: Any = None,
) -> None:
    run.status = status.value
    run.plan_id = plan.id if plan is not None else run.plan_id
    run.completed_at = datetime.now(UTC)
    run.duration_ms = duration_ms
    run.token_usage = token_usage
    run.estimated_cost = Decimal(str(estimated_cost)) if estimated_cost is not None else None
    run.error_code = error_code
    run.error_message = error_message
    run.output_hash = output_hash
    if fell_back_from_tier is not None:
        run.fell_back_from_tier = fell_back_from_tier.value
    await db.flush()


async def find_idempotent_plan(
    assignment_id: UUID, idempotency_key: str, db: AsyncSession
) -> AcademicWorkPlan | None:
    stmt = (
        select(AcademicWorkPlan)
        .where(
            AcademicWorkPlan.assignment_id == assignment_id,
            AcademicWorkPlan.idempotency_key == idempotency_key,
        )
        .order_by(AcademicWorkPlan.version.desc())
        .limit(1)
    )
    plan: AcademicWorkPlan | None = await db.scalar(stmt)
    return plan


async def mark_stale_plans(db: AsyncSession, assignment_id: UUID) -> int:
    """Flag every plan built on a superseded analysis.

    Marked, never deleted: an approved plan is a record of what the student
    agreed to, and the analysis moving does not retract that.
    """
    stmt = select(AcademicWorkPlan).where(
        AcademicWorkPlan.assignment_id == assignment_id,
        AcademicWorkPlan.is_stale.is_(False),
    )
    plans = list(await db.scalars(stmt))
    now = datetime.now(UTC)
    for plan in plans:
        plan.is_stale = True
        plan.stale_at = now
        if plan.status in {PlanStatus.DRAFT.value, PlanStatus.READY_FOR_REVIEW.value}:
            plan.status = PlanStatus.STALE.value
    if plans:
        await db.flush()
    return len(plans)


def is_plan_stale(plan: AcademicWorkPlan, analysis: AssignmentAnalysis | None) -> bool:
    """True when the plan no longer reflects the current analysis."""
    if plan.is_stale:
        return True
    if analysis is None or plan.analysis_id is None:
        return False
    return plan.analysis_id != analysis.id


# ---------------------------------------------------------------------------
# Persisting a validated plan
# ---------------------------------------------------------------------------


async def persist_plan(
    db: AsyncSession,
    *,
    assignment: Assignment,
    analysis: AssignmentAnalysis | None,
    plan_output: PlannerOutput,
    graph: ValidatedGraph,
    contract: PlanningContractResponse,
    trigger: PlanTrigger,
    reason: str,
    preferences: PlanningPreferences,
    idempotency_key: str | None = None,
    preserve: Sequence[PlanTask] = (),
    changed_sections: Sequence[str] = (),
) -> AcademicWorkPlan:
    """Write a validated plan as a new version.

    ``preserve`` carries tasks the student authored by hand from a previous
    version. They are re-inserted with their content intact, which is the whole
    point of a partial regeneration.
    """
    version = await _next_version(assignment.id, db)
    plan = AcademicWorkPlan(
        assignment_id=assignment.id,
        analysis_id=analysis.id if analysis is not None else None,
        version=version,
        trigger=trigger.value,
        reason=reason,
        changed_sections=list(changed_sections) or None,
        title=plan_output.title,
        summary=plan_output.summary,
        status=PlanStatus.READY_FOR_REVIEW.value,
        objectives=list(plan_output.objectives),
        payload=_plan_payload(
            plan_output,
            requirement_count=len(contract.requirements),
            deliverable_count=len(contract.deliverables),
        ),
        estimated_effort=plan_output.estimated_effort.value,
        min_minutes=plan_output.min_minutes,
        max_minutes=plan_output.max_minutes,
        idempotency_key=idempotency_key,
    )
    plan.payload = {**(plan.payload or {}), "preferences": asdict(preferences)}
    db.add(plan)
    await db.flush()

    # Order follows the validated topological order, so the stored positions
    # already read as an execution sequence.
    rows: dict[str, PlanTask] = {}
    for position, task in enumerate(plan_output.tasks):
        await _insert_task(db, plan, task, position, graph.order, rows)
    await _insert_dependencies(db, plan, plan_output, rows)

    for position, milestone in enumerate(plan_output.milestones):
        db.add(
            PlanMilestone(
                plan_id=plan.id,
                key=milestone.key,
                title=milestone.title,
                description=milestone.description,
                position=position,
                status=AcademicTaskStatus.PENDING.value,
            )
        )

    await _carry_over_user_tasks(db, plan, preserve, rows)
    await _validate_persisted_graph(db, plan)
    await db.flush()
    return plan


def _plan_payload(
    plan_output: PlannerOutput, *, requirement_count: int, deliverable_count: int
) -> dict[str, Any]:
    """The parts of a plan that are planning metadata rather than relational data.

    Milestones and dependencies are real tables. Verification points, risks and
    objectives are not queried by anything, so they live in the payload instead of
    earning three more tables.
    """
    return {
        "verification_points": [
            item.model_dump(mode="json") for item in plan_output.verification_points
        ],
        "risks": [item.model_dump(mode="json") for item in plan_output.risks],
        "milestones": [item.model_dump(mode="json") for item in plan_output.milestones],
        "objectives": list(plan_output.objectives),
        "confidence": plan_output.confidence,
        "requirement_count": requirement_count,
        "deliverable_count": deliverable_count,
    }


async def _insert_task(
    db: AsyncSession,
    plan: AcademicWorkPlan,
    task: PlannedTask,
    position: int,
    order: Sequence[str],
    rows: dict[str, PlanTask],
) -> PlanTask:
    """Insert a planned task, its traceability and its incoming edges.

    Edges are written after the whole task set exists, because an edge needs both
    endpoints. Writing them here, against tasks that may not be inserted yet, is
    how a validated graph quietly becomes an empty one in the database.
    """
    row = PlanTask(
        plan_id=plan.id,
        key=task.key,
        title=task.title,
        description=task.description,
        type=task.type.value,
        status=AcademicTaskStatus.PENDING.value,
        priority=task.priority.value,
        position=order.index(task.key) if task.key in order else position,
        estimated_effort=task.estimated_effort.value,
        min_minutes=task.min_minutes,
        max_minutes=task.max_minutes,
        verification_method=task.verification_method,
        acceptance_criteria=list(task.acceptance_criteria),
        resources=list(task.resources),
        is_user_authored=False,
    )
    db.add(row)
    await db.flush()
    for reference in task.related_requirements:
        db.add(PlanTaskRequirement(plan_id=plan.id, task_id=row.id, requirement_key=reference))
    for reference in task.related_deliverables:
        db.add(PlanTaskDeliverable(plan_id=plan.id, task_id=row.id, deliverable_key=reference))
    rows[task.key] = row
    return row


async def _insert_dependencies(
    db: AsyncSession,
    plan: AcademicWorkPlan,
    plan_output: PlannerOutput,
    rows: dict[str, PlanTask],
) -> None:
    """Write the validated edges as rows.

    ``rows`` maps plan-local task keys to inserted rows. Every endpoint is looked
    up rather than trusted: the graph validator already refused dangling keys, so
    a miss here means persistence and validation disagree, and that is worth
    raising over rather than skipping silently.
    """
    for task in plan_output.tasks:
        for key in task.depends_on:
            try:
                predecessor = rows[key]
            except KeyError as exc:
                raise AppError(
                    500,
                    "PLAN_PERSISTENCE_MISMATCH",
                    "A validated dependency was not present at persistence time.",
                    {"task": task.key, "missing": key},
                ) from exc
            db.add(
                PlanTaskDependency(
                    plan_id=plan.id,
                    predecessor_id=predecessor.id,
                    successor_id=rows[task.key].id,
                )
            )
    await db.flush()


async def _carry_over_user_tasks(
    db: AsyncSession,
    plan: AcademicWorkPlan,
    preserve: Sequence[PlanTask],
    rows: dict[str, PlanTask],
) -> None:
    """Re-insert the student's own tasks into a regenerated version.

    Content, acceptance criteria and status are copied verbatim, because the point
    of a partial regeneration is that work the student has already shaped survives
    it. Two things are deliberately not copied:

    * **Dependencies onto generated tasks.** A generated task in the new version
      may not exist, and a dangling edge is worse than a missing one. Edges
      between the student's own tasks are kept, since both endpoints are carried
      over together.
    * **The task key.** A generated ``T3`` in the new version and the student's
      old ``T3`` are different tasks, so keeping the key would either collide or
      quietly retarget the student's traceability. Preserved tasks are given a
      distinct ``U`` prefix and old keys are remapped on both sides of any edge.
    """
    carried = [task for task in preserve if task.is_user_authored]
    if not carried:
        return

    taken = set(rows)
    remap: dict[str, str] = {}
    for index, previous in enumerate(carried, start=1):
        key = f"U{index}"
        while key in taken:
            index += 1
            key = f"U{index}"
        taken.add(key)
        remap[previous.key] = key

    base = len(rows)
    for offset, previous in enumerate(carried):
        row = PlanTask(
            plan_id=plan.id,
            key=remap[previous.key],
            title=previous.title,
            description=previous.description,
            type=previous.type,
            status=previous.status,
            priority=previous.priority,
            position=base + offset,
            estimated_effort=previous.estimated_effort,
            min_minutes=previous.min_minutes,
            max_minutes=previous.max_minutes,
            verification_method=previous.verification_method,
            acceptance_criteria=list(previous.acceptance_criteria or []),
            resources=list(previous.resources or []),
            notes=previous.notes,
            is_user_authored=True,
        )
        db.add(row)
        rows[remap[previous.key]] = row
    await db.flush()

    # Query the edges rather than walking ``task.predecessors``: that relationship
    # is lazy, and touching it outside an awaited load would fault in async.
    by_id = {task.id: task for task in carried}
    edges = list(
        await db.scalars(
            select(PlanTaskDependency).where(
                PlanTaskDependency.plan_id.in_({task.plan_id for task in carried}),
                PlanTaskDependency.successor_id.in_(by_id),
                PlanTaskDependency.predecessor_id.in_(by_id),
            )
        )
    )
    for edge in edges:
        db.add(
            PlanTaskDependency(
                plan_id=plan.id,
                predecessor_id=rows[remap[by_id[edge.predecessor_id].key]].id,
                successor_id=rows[remap[by_id[edge.successor_id].key]].id,
                reason=edge.reason,
            )
        )
    await db.flush()


def _validate_persisted_graph_sync(
    tasks: Sequence[PlanTask], edges: Sequence[tuple[str, str]]
) -> None:
    """Turn a graph violation into a client error at the point of the edit.

    The check is a read of the in-session graph, so it needs no await. Wrapping it
    here means a cycle created by an edit is a 409 with a readable reason instead
    of an unhandled exception from deep inside the validator.
    """
    try:
        _check_persisted(tasks, edges)
    except PlanGraphError as exc:
        raise AppError(
            409,
            "PLAN_GRAPH_INVALID",
            "That change would produce a plan that cannot be executed.",
            {"violations": exc.violations},
        ) from exc


def _check_persisted(
    tasks: Sequence[PlanTask],
    edges: Sequence[tuple[str, str]],
) -> None:
    """Validate the graph as stored, not as proposed.

    Belt and braces: if persistence and the proposal ever disagree, the stored
    truth is the one that ships, so that is the one that gets validated.
    """
    if not tasks:
        return
    violations = validate_edited_graph([{"key": task.key} for task in tasks], edges)
    if violations:
        raise PlanGraphError(violations)


async def _load_persisted_edges(
    db: AsyncSession, plan: AcademicWorkPlan, tasks: Sequence[PlanTask]
) -> list[tuple[str, str]]:
    by_id = {task.id: task for task in tasks}
    return [
        (by_id[edge.predecessor_id].key, by_id[edge.successor_id].key)
        for edge in await db.scalars(
            select(PlanTaskDependency).where(PlanTaskDependency.plan_id == plan.id)
        )
        if edge.predecessor_id in by_id and edge.successor_id in by_id
    ]


async def _validate_persisted_graph(db: AsyncSession, plan: AcademicWorkPlan) -> None:
    await db.flush()
    tasks = list(await db.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id)))
    _check_persisted(tasks, await _load_persisted_edges(db, plan, tasks))


# ---------------------------------------------------------------------------
# Human review
# ---------------------------------------------------------------------------


async def approve_plan(
    db: AsyncSession, plan: AcademicWorkPlan, *, user_id: UUID, note: str | None = None
) -> AcademicWorkPlan:
    """Approve a plan. This is the moment it becomes the authoritative schedule."""
    if plan.status == PlanStatus.APPROVED.value:
        return plan
    if plan.status == PlanStatus.ARCHIVED.value:
        raise AppError(409, "PLAN_ARCHIVED", "An archived plan cannot be approved.")
    if plan.is_stale:
        # Clearing the flag here would make an out-of-date plan look current, and
        # the flag is the only thing telling the student to regenerate.
        raise AppError(
            409,
            "PLAN_STALE",
            "This plan was built on an earlier analysis. Regenerate it before approving.",
        )
    plan.status = PlanStatus.APPROVED.value
    plan.approved_at = datetime.now(UTC)
    plan.approved_by_id = user_id
    if note:
        plan.reason = f"{plan.reason} | approved: {note}" if plan.reason else f"approved: {note}"
    await db.flush()
    return plan


def assert_editable(plan: AcademicWorkPlan) -> None:
    """Refuse edits to a plan that is no longer the student's to change.

    An approved plan is immutable on purpose. Changing it in place would make
    "what did I agree to" unanswerable, which is the one question an approval is
    supposed to settle.
    """
    if PlanStatus(plan.status) not in EDITABLE_STATUSES:
        raise AppError(
            409,
            "PLAN_IMMUTABLE",
            "This plan is approved and cannot be edited. Regenerate it to make changes.",
        )


async def update_plan(
    db: AsyncSession, plan: AcademicWorkPlan, changes: dict[str, Any]
) -> AcademicWorkPlan:
    assert_editable(plan)
    for field, value in changes.items():
        if value is None:
            continue
        setattr(plan, field, value.value if hasattr(value, "value") else value)
    await db.flush()
    return plan


async def add_task(
    db: AsyncSession,
    plan: AcademicWorkPlan,
    *,
    title: str,
    description: str = "",
    task_type: str = AcademicTaskType.OTHER.value,
    priority: str = AcademicTaskPriority.MEDIUM.value,
    estimated_effort: str = EffortLevel.MEDIUM.value,
    depends_on: Sequence[str] = (),
    related_requirements: Sequence[str] = (),
    related_deliverables: Sequence[str] = (),
    verification_method: str | None = None,
    acceptance_criteria: Sequence[str] = (),
    notes: str | None = None,
    position: int | None = None,
) -> PlanTask:
    """Add a student-authored task.

    Always marked ``is_user_authored`` so a later regeneration keeps it. A plan
    that silently loses a task the student wrote by hand is the single most
    trust-destroying thing this service could do.
    """
    assert_editable(plan)
    existing = list(await db.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id)))
    key = await _next_task_key(plan.id, db)
    task = PlanTask(
        plan_id=plan.id,
        key=key,
        title=title,
        description=description,
        type=task_type,
        status=AcademicTaskStatus.PENDING.value,
        priority=priority,
        position=len(existing) if position is None else position,
        estimated_effort=estimated_effort,
        verification_method=verification_method,
        acceptance_criteria=list(acceptance_criteria),
        notes=notes,
        is_user_authored=True,
    )
    db.add(task)
    await db.flush()
    for reference in related_requirements:
        db.add(PlanTaskRequirement(plan_id=plan.id, task_id=task.id, requirement_key=reference))
    for reference in related_deliverables:
        db.add(PlanTaskDeliverable(plan_id=plan.id, task_id=task.id, deliverable_key=reference))
    await _replace_dependencies(db, plan, task, depends_on)
    await _validate_persisted_graph(db, plan)
    return task


async def update_task(
    db: AsyncSession,
    plan: AcademicWorkPlan,
    task: PlanTask,
    changes: dict[str, Any],
    *,
    depends_on: Sequence[str] | None = None,
    related_requirements: Sequence[str] | None = None,
    related_deliverables: Sequence[str] | None = None,
) -> PlanTask:
    """Edit one task and re-check the graph it belongs to."""
    assert_editable(plan)
    for field, value in changes.items():
        if value is None:
            continue
        setattr(task, field, value.value if hasattr(value, "value") else value)
    # An edited task is the student's work now, even if the model proposed it.
    task.is_user_authored = True
    await db.flush()
    if related_requirements is not None:
        await _replace_traceability(
            db, plan, task, related_requirements, PlanTaskRequirement, "requirement_key"
        )
    if related_deliverables is not None:
        await _replace_traceability(
            db, plan, task, related_deliverables, PlanTaskDeliverable, "deliverable_key"
        )
    if depends_on is not None:
        await _replace_dependencies(db, plan, task, depends_on)

    # Re-read rather than trust the session: the validator must see the graph as
    # stored, and an edit that failed part way through must not be committed as a
    # half-applied change.
    await db.flush()
    rows = list(await db.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id)))
    _validate_persisted_graph_sync(rows, await _load_persisted_edges(db, plan, rows))
    return task


async def delete_task(db: AsyncSession, plan: AcademicWorkPlan, task: PlanTask) -> None:
    """Delete a task and every edge that touched it.

    Edges are removed rather than left dangling. A dependency on a task that no
    longer exists is not a soft warning, it is a graph the validator would reject
    on the next write.
    """
    assert_editable(plan)
    await db.execute(
        select(PlanTaskDependency).where(
            (PlanTaskDependency.predecessor_id == task.id)
            | (PlanTaskDependency.successor_id == task.id)
        )
    )
    for edge in list(
        await db.scalars(
            select(PlanTaskDependency).where(
                (PlanTaskDependency.predecessor_id == task.id)
                | (PlanTaskDependency.successor_id == task.id)
            )
        )
    ):
        await db.delete(edge)
    await db.delete(task)
    await db.flush()
    await _validate_persisted_graph(db, plan)


async def reorder_tasks(
    db: AsyncSession, plan: AcademicWorkPlan, task_keys: Sequence[str]
) -> list[PlanTask]:
    """Reorder tasks. Never calls a model; this is pure bookkeeping."""
    assert_editable(plan)
    tasks = list(await db.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id)))
    by_key = {task.key: task for task in tasks}
    missing = [key for key in task_keys if key not in by_key]
    if missing:
        raise AppError(
            422, "UNKNOWN_TASK", f"These tasks are not in the plan: {', '.join(missing)}."
        )
    unlisted = [task.key for task in tasks if task.key not in set(task_keys)]
    if unlisted:
        raise AppError(
            422,
            "INCOMPLETE_REORDER",
            "A reorder must list every task. Missing: " + ", ".join(sorted(unlisted)),
        )
    for position, key in enumerate(task_keys):
        by_key[key].position = position
    await db.flush()
    return sorted(tasks, key=lambda task: task.position)


async def _next_task_key(plan_id: UUID, db: AsyncSession) -> str:
    keys = list(await db.scalars(select(PlanTask.key).where(PlanTask.plan_id == plan_id)))
    numbers = [int(key[1:]) for key in keys if key.startswith("T") and key[1:].isdigit()]
    return f"T{max(numbers, default=0) + 1}"


async def _replace_dependencies(
    db: AsyncSession, plan: AcademicWorkPlan, task: PlanTask, depends_on: Sequence[str]
) -> None:
    for edge in list(
        await db.scalars(
            select(PlanTaskDependency).where(PlanTaskDependency.successor_id == task.id)
        )
    ):
        await db.delete(edge)
    await db.flush()
    if not depends_on:
        return
    by_key = {
        row.key: row
        for row in await db.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id))
    }
    for key in depends_on:
        predecessor = by_key.get(key)
        if predecessor is None:
            raise AppError(422, "UNKNOWN_TASK", f"Task {key} is not in this plan.")
        if predecessor.id == task.id:
            raise AppError(422, "SELF_DEPENDENCY", "A task cannot depend on itself.")
        db.add(
            PlanTaskDependency(plan_id=plan.id, predecessor_id=predecessor.id, successor_id=task.id)
        )
    await db.flush()


TraceabilityRow = PlanTaskRequirement | PlanTaskDeliverable


async def _replace_traceability(
    db: AsyncSession,
    plan: AcademicWorkPlan,
    task: PlanTask,
    references: Sequence[str],
    model: type[PlanTaskRequirement] | type[PlanTaskDeliverable],
    column: str,
) -> None:
    existing: list[TraceabilityRow] = list(
        await db.scalars(select(model).where(model.task_id == task.id))
    )
    for row in existing:
        await db.delete(row)
    await db.flush()
    for reference in references:
        db.add(model(plan_id=plan.id, task_id=task.id, **{column: reference}))
    await db.flush()


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Counts:
    """Requirement and deliverable counts, which is all the schedule check needs."""

    requirements: list[Any]
    deliverables: list[Any]


@dataclass(slots=True)
class PlanGraphView:
    """Everything needed to render a plan, loaded in a fixed number of queries.

    Assembled once per response rather than queried per task. A forty-task plan
    rendered as a graph view would otherwise issue well over a hundred queries.
    """

    tasks: list[PlanTask]
    dependencies: list[PlanTaskDependency]
    requirements: dict[UUID, list[str]]
    deliverables: dict[UUID, list[str]]
    milestones: list[PlanMilestone]
    #: milestone key -> the task keys that version of the plan assigned to it.
    milestone_keys: dict[str, list[str]]


async def load_plan_graph(db: AsyncSession, plan: AcademicWorkPlan) -> PlanGraphView:
    plan_id = plan.id
    tasks = list(
        await db.scalars(
            select(PlanTask).where(PlanTask.plan_id == plan_id).order_by(PlanTask.position)
        )
    )
    dependencies = list(
        await db.scalars(select(PlanTaskDependency).where(PlanTaskDependency.plan_id == plan_id))
    )
    requirement_rows = list(
        await db.scalars(select(PlanTaskRequirement).where(PlanTaskRequirement.plan_id == plan_id))
    )
    deliverable_rows = list(
        await db.scalars(select(PlanTaskDeliverable).where(PlanTaskDeliverable.plan_id == plan_id))
    )
    milestones = list(
        await db.scalars(
            select(PlanMilestone)
            .where(PlanMilestone.plan_id == plan_id)
            .order_by(PlanMilestone.position)
        )
    )
    payload = plan.payload or {}
    return PlanGraphView(
        tasks=tasks,
        dependencies=dependencies,
        requirements=_group(requirement_rows, "requirement_key"),
        deliverables=_group(deliverable_rows, "deliverable_key"),
        milestones=milestones,
        milestone_keys={
            str(item.get("key")): list(item.get("task_keys", []))
            for item in payload.get("milestones", [])
        },
    )


def _group(rows: Iterable[Any], attribute: str) -> dict[UUID, list[str]]:
    grouped: dict[UUID, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.task_id, []).append(getattr(row, attribute))
    for values in grouped.values():
        values.sort()
    return grouped


def build_plan_response(
    plan: AcademicWorkPlan,
    *,
    assignment: Assignment,
    graph: PlanGraphView,
    warnings: Sequence[str] = (),
) -> WorkPlanResponse:
    """Assemble the full client view of a plan version.

    Traceability, ``blocked_by`` and progress are computed here rather than stored,
    because all three are derived state that would go stale the moment a task
    changed.
    """
    by_id = {task.id: task for task in graph.tasks}
    by_key = {task.key: task for task in graph.tasks}
    predecessors: dict[UUID, list[PlanTaskDependency]] = {}
    for edge in graph.dependencies:
        predecessors.setdefault(edge.successor_id, []).append(edge)

    task_responses: list[TaskResponse] = []
    for task in graph.tasks:
        edges = predecessors.get(task.id, [])
        parents = [by_id[edge.predecessor_id] for edge in edges if edge.predecessor_id in by_id]
        blocked_by = [
            parent.key for parent in parents if parent.status != AcademicTaskStatus.COMPLETED.value
        ]
        task_responses.append(
            TaskResponse(
                id=task.id,
                key=task.key,
                title=task.title,
                description=task.description or "",
                type=task.type,
                status=task.status,
                priority=task.priority,
                position=task.position,
                estimated_effort=task.estimated_effort,
                min_minutes=task.min_minutes,
                max_minutes=task.max_minutes,
                verification_method=task.verification_method,
                acceptance_criteria=list(task.acceptance_criteria or []),
                resources=list(task.resources or []),
                notes=task.notes,
                is_user_authored=task.is_user_authored,
                depends_on=sorted(parent.key for parent in parents),
                related_requirements=graph.requirements.get(task.id, []),
                related_deliverables=graph.deliverables.get(task.id, []),
                blocked_by=sorted(blocked_by),
            )
        )

    completed = sum(1 for task in graph.tasks if task.status == AcademicTaskStatus.COMPLETED.value)
    payload = plan.payload or {}
    return WorkPlanResponse(
        id=plan.id,
        assignment_id=plan.assignment_id,
        analysis_id=plan.analysis_id,
        version=plan.version,
        trigger=plan.trigger,
        reason=plan.reason,
        changed_sections=plan.changed_sections,
        title=plan.title,
        summary=plan.summary or "",
        status=plan.status,
        objectives=list(plan.objectives or []),
        estimated_effort=plan.estimated_effort,
        min_minutes=plan.min_minutes,
        max_minutes=plan.max_minutes,
        is_stale=plan.is_stale,
        approved_at=plan.approved_at,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        tasks=task_responses,
        milestones=[
            _milestone_response(milestone, by_key, graph) for milestone in graph.milestones
        ],
        verification_points=[
            VerificationPointResponse.model_validate(item)
            for item in payload.get("verification_points", [])
        ],
        risks=[PlanRiskResponse.model_validate(item) for item in payload.get("risks", [])],
        schedule_risk=ScheduleRiskResponse.model_validate(
            _schedule_risk_for_plan(plan, assignment)
        ),
        progress_percentage=_progress(len(graph.tasks), completed),
        validation_warnings=list(warnings),
    )


def _milestone_response(
    milestone: PlanMilestone, by_key: dict[str, PlanTask], graph: PlanGraphView
) -> MilestoneResponse:
    keys = _milestone_task_keys(milestone, graph)
    tasks = [by_key[key] for key in keys if key in by_key]
    done = sum(1 for task in tasks if task.status == AcademicTaskStatus.COMPLETED.value)
    return MilestoneResponse(
        id=milestone.id,
        key=milestone.key,
        title=milestone.title,
        description=milestone.description,
        position=milestone.position,
        status=milestone.status,
        task_keys=keys,
        completed_task_count=done,
        task_count=len(tasks),
    )


def _milestone_task_keys(milestone: PlanMilestone, graph: PlanGraphView) -> list[str]:
    """Which tasks a milestone covers.

    The task list is stored in the plan payload at generation time, because a
    milestone's membership is a property of that version of the plan, not of the
    current task rows. Recomputing it from positions would silently reassign work
    whenever a task was inserted.
    """
    return list(graph.milestone_keys.get(milestone.key, []))


def _schedule_risk_for_plan(plan: AcademicWorkPlan, assignment: Assignment) -> dict[str, Any]:
    """Compare the plan's own totals against the time remaining."""
    from app.modules.planning.planner import schedule_risk as compute

    payload = plan.payload or {}
    counts = _Counts(
        requirements=[None] * int(payload.get("requirement_count", 0)),
        deliverables=[None] * int(payload.get("deliverable_count", 0)),
    )
    return compute(
        counts,
        min_minutes=plan.min_minutes,
        max_minutes=plan.max_minutes,
        deadline=assignment.deadline,
    )


def _progress(total: int, completed: int) -> int:
    if total <= 0:
        return 0
    return int(round(completed / total * 100))


async def build_plan_summary(plan: AcademicWorkPlan, graph: PlanGraphView) -> PlanSummaryResponse:
    """The lightweight view for list endpoints: counts, no task bodies."""
    completed = sum(1 for task in graph.tasks if task.status == AcademicTaskStatus.COMPLETED.value)
    return PlanSummaryResponse(
        id=plan.id,
        assignment_id=plan.assignment_id,
        analysis_id=plan.analysis_id,
        version=plan.version,
        trigger=plan.trigger,
        title=plan.title,
        status=plan.status,
        is_stale=plan.is_stale,
        task_count=len(graph.tasks),
        completed_task_count=completed,
        progress_percentage=_progress(len(graph.tasks), completed),
        estimated_effort=plan.estimated_effort,
        created_at=plan.created_at,
        approved_at=plan.approved_at,
    )
