"""Academic planning endpoints.

Everything is scoped to an assignment the caller owns. Two rules shape the whole
router:

* **A plan is a version, not a document.** There is no ``PUT`` on a plan. Changing
  one is a regeneration, which writes a new version and leaves the old one
  readable, so "what did I approve" always has an answer.
* **Approval is the transition that matters.** Nothing here executes anything. A
  plan becomes authoritative when a person approves it, and after that a single
  version is immutable.

Endpoints that reach a model are the only ones that can be slow or unavailable.
The rest are reads, and they never fail because a provider is down.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import LLMUnavailableError, build_llm_provider
from app.ai.errors import LLMError
from app.ai.provider import LLMProvider
from app.ai.registry import ModelRegistry, ModelRouter
from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.core.logging import logger
from app.db.session import get_db
from app.models import AcademicWorkPlan, Assignment, AssignmentAnalysis, PlanTask, User
from app.models.enums import AIMode, AuditEventType, PlanStatus, PlanTrigger
from app.modules.analysis.service import (
    build_planning_contract,
    is_analysis_stale,
    latest_analysis,
    load_owned_analysis,
)
from app.modules.assignments.service import load_owned_assignment
from app.modules.planning import service
from app.modules.planning.complexity import score_complexity
from app.modules.planning.orchestrator import GenerationResult, generate_plan
from app.modules.planning.planner import PlanningPreferences
from app.schemas.analysis import PlanningContractResponse
from app.schemas.common import Page, PageParams, PageResponse
from app.schemas.planning import (
    PlanApproveRequest,
    PlanGenerateRequest,
    PlanningPreferencesRequest,
    PlanningPreferencesResponse,
    PlanRegenerateRequest,
    PlanSummaryResponse,
    PlanUpdateRequest,
    TaskCreateRequest,
    TaskReorderRequest,
    TaskResponse,
    TaskUpdateRequest,
    WorkPlanResponse,
)
from app.services.events import record_audit

router = APIRouter(prefix="/api/v1/assignments", tags=["Planning"])
settings = get_settings()

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def _provider(model: str | None = None) -> LLMProvider:
    try:
        return build_llm_provider(settings, model=model)
    except LLMUnavailableError as exc:
        raise AppError(503, exc.code, exc.message, exc.details or None) from exc


def _router() -> ModelRouter:
    """Build the tier router from configuration.

    Both tiers come from settings, so the routing decision is visible in
    configuration rather than hidden in a table here.
    """
    return ModelRouter(ModelRegistry(settings))


async def _record(
    db: AsyncSession,
    assignment: Assignment,
    plan: AcademicWorkPlan,
    user: User,
    event_type: AuditEventType,
    *,
    entity_type: str,
    entity_id: UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record one audited step of a student's interaction with a plan.

    Every endpoint that changes a plan writes here, so "who changed this plan and
    when" has the same answer for task edits as it does for approval. The plan's
    version is included in every event because a plan is a versioned record: an
    audit entry without it cannot be tied to what the student was looking at.
    """
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata={"version": plan.version, **(metadata or {})},
    )


async def _contract_for(
    assignment: Assignment,
    db: AsyncSession,
    analysis_id: UUID | None = None,
    user_id: UUID | None = None,
) -> tuple[PlanningContractResponse, AssignmentAnalysis]:
    """The planning contract and analysis the current plan would be built on.

    Planning reads the analyzer's output and never re-reads the specification, so
    the two cannot disagree about what was asked for. A contract whose analysis
    has gone stale is refused rather than planned from, because a plan built on
    superseded requirements is worse than no plan.
    """
    analysis = await latest_analysis(assignment.id, db)
    if analysis is None:
        raise AppError(
            409,
            "PLAN_NEEDS_ANALYSIS",
            "This assignment has not been analyzed yet, so there is nothing to plan from.",
        )
    if analysis_id is not None and analysis.id != analysis_id:
        # An explicit analysis was asked for. Planning from a different one
        # silently would make the plan disagree with the request that made it.
        if not is_analysis_stale(analysis, assignment):
            raise AppError(
                404,
                "ANALYSIS_NOT_CURRENT",
                "That analysis is no longer the current one for this assignment. Plan from the "
                "latest analysis, or re-run the analysis to make this one current again.",
            )
        if user_id is None:
            raise AppError(404, "ANALYSIS_NOT_FOUND", "No such analysis for this assignment.")
        analysis = await load_owned_analysis(assignment.id, analysis_id, user_id, db)
    if is_analysis_stale(analysis, assignment):
        raise AppError(
            409,
            "PLAN_NEEDS_FRESH_ANALYSIS",
            "The assignment has changed since this analysis was produced. Re-run the analysis "
            "before planning, or the plan will not describe the current brief.",
        )
    return build_planning_contract(analysis, stale=False), analysis


async def _preferences_for(
    assignment: Assignment,
    db: AsyncSession,
    payload: PlanGenerateRequest | PlanRegenerateRequest,
) -> PlanningPreferences:
    preferences, _mode = await service.resolve_preferences(
        assignment.workspace_id,
        db,
        style=payload.planning_style,
        guidance=payload.guidance_level,
        session_length=payload.session_length,
        ai_mode=payload.ai_mode,
    )
    return preferences


async def _generate(
    db: AsyncSession,
    *,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    user: User,
    payload: PlanGenerateRequest | PlanRegenerateRequest,
    trigger: PlanTrigger,
    reason: str,
    preserve: Sequence[PlanTask] = (),
) -> GenerationResult:
    """Run generation, turning provider trouble into a stated outcome.

    A model that is unreachable or answers with something invalid is not the
    student's mistake, so the deterministic engine answers and the run says so.
    Only a configuration problem, or a provider failure with fallback disabled,
    surfaces as an error.
    """
    selection = _router().select(score_complexity(contract), payload.ai_mode or AIMode.AUTO)
    preferences = await _preferences_for(assignment, db, payload)
    provider = _provider(selection.model)
    try:
        return await generate_plan(
            db,
            assignment=assignment,
            analysis=analysis,
            contract=contract,
            provider=provider,
            selection=selection,
            preferences=preferences,
            user_id=user.id,
            trigger=trigger,
            reason=reason,
            idempotency_key=payload.idempotency_key,
            preserve=preserve,
            max_task_count=settings.planning_max_task_count,
            hours_per_grade_point=settings.planning_effort_hours_per_point,
            fallback_enabled=settings.planning_fallback_enabled,
            prompt_version=settings.llm_planner_prompt_version,
            force=payload.force,
        )
    except LLMError as exc:
        logger.error(
            "PLAN_GENERATION_PROVIDER_ERROR",
            extra={"assignment_id": str(assignment.id), "code": exc.code},
        )
        await db.rollback()
        raise AppError(
            503,
            "PLANNER_UNAVAILABLE",
            "The planning model is unavailable and no fallback was permitted.",
            {"code": exc.code},
        ) from exc


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/plans",
    response_model=WorkPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a study plan for an analyzed assignment",
    description=(
        "Plans the assignment from its current analysis.\n\n"
        "The routed model tier proposes a plan, the proposal is validated against the "
        "analysis and the graph rules, and the deterministic planning engine answers if the "
        "model is unavailable or its proposal does not validate. The response's "
        "`validation_warnings` says which path produced the plan, so a fallback is never "
        "presented as a model result.\n\n"
        "Creates version 1 on the first call and a new version afterwards. Supplying an "
        "`idempotency_key` makes a repeated request return the existing plan unchanged instead "
        "of planning and billing again."
    ),
)
async def generate_plan_for_assignment(
    assignment_id: UUID,
    payload: PlanGenerateRequest,
    user: CurrentUser,
    db: Db,
) -> WorkPlanResponse:
    if not settings.planning_enabled:
        raise AppError(503, "PLANNING_DISABLED", "Planning is disabled.")

    assignment = await load_owned_assignment(assignment_id, user.id, db)
    contract, analysis = await _contract_for(
        assignment,
        db,
        payload.analysis_id if isinstance(payload, PlanGenerateRequest) else None,
        user.id,
    )

    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.PLAN_REQUESTED,
        entity_type="Assignment",
        entity_id=assignment.id,
        metadata={"scope": "generate"},
    )

    result = await _generate(
        db,
        assignment=assignment,
        analysis=analysis,
        contract=contract,
        user=user,
        payload=payload,
        trigger=PlanTrigger.GENERATED,
        reason=payload.reason or "",
    )
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.PLAN_GENERATED,
        entity_type="AcademicWorkPlan",
        entity_id=result.plan.id,
        metadata={
            "version": result.plan.version,
            "used_fallback": result.used_fallback,
        },
    )
    logger.info(
        "PLAN_GENERATED",
        extra={
            "assignment_id": str(assignment.id),
            "plan_id": str(result.plan.id),
            "version": result.plan.version,
            "used_fallback": result.used_fallback,
        },
    )
    await db.commit()
    return service.build_plan_response(
        result.plan, assignment=assignment, graph=result.graph, warnings=result.warnings
    )


@router.post(
    "/{assignment_id}/plans/regenerate",
    response_model=WorkPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Regenerate a plan as a new version",
    description=(
        "Re-plans the assignment and writes the result as a new version. The previous version "
        "stays readable, and an approved version is never modified.\n\n"
        "Tasks the student authored or edited by hand are carried into the new version with "
        "their content intact (unless `preserve_user_edits` is false). Dependencies between "
        "those carried tasks are preserved; dependencies from them onto generated tasks are "
        "dropped, because those tasks may not exist in the new plan."
    ),
)
async def regenerate_plan(
    assignment_id: UUID,
    payload: PlanRegenerateRequest,
    user: CurrentUser,
    db: Db,
) -> WorkPlanResponse:
    if not settings.planning_enabled:
        raise AppError(503, "PLANNING_DISABLED", "Planning is disabled.")

    assignment = await load_owned_assignment(assignment_id, user.id, db)
    current = await service.latest_plan(assignment_id, db, include_draft=True)
    if current is None:
        raise AppError(409, "PLAN_NOT_FOUND", "There is no plan to regenerate. Generate one first.")
    if current.status == PlanStatus.ARCHIVED.value:
        raise AppError(409, "PLAN_ARCHIVED", "An archived plan cannot be regenerated.")

    contract, analysis = await _contract_for(
        assignment,
        db,
        payload.analysis_id if isinstance(payload, PlanGenerateRequest) else None,
        user.id,
    )
    preserve: Sequence[PlanTask] = ()
    if payload.preserve_user_edits:
        preserve = tuple(await service.user_authored_tasks(current.id, db))

    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.PLAN_REGENERATION_REQUESTED,
        entity_type="AcademicWorkPlan",
        entity_id=current.id,
        metadata={"from_version": current.version, "scope": payload.scope},
    )

    result = await _generate(
        db,
        assignment=assignment,
        analysis=analysis,
        contract=contract,
        user=user,
        payload=payload,
        trigger=PlanTrigger.REGENERATED,
        reason=payload.reason or "regenerated",
        preserve=preserve,
    )
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.PLAN_REGENERATED,
        entity_type="AcademicWorkPlan",
        entity_id=result.plan.id,
        metadata={
            "from_version": current.version,
            "version": result.plan.version,
            "carried_tasks": len(preserve),
            "used_fallback": result.used_fallback,
        },
    )
    await db.commit()
    return service.build_plan_response(
        result.plan, assignment=assignment, graph=result.graph, warnings=result.warnings
    )


# ---------------------------------------------------------------------------
# Reading plans
# ---------------------------------------------------------------------------


@router.get(
    "/{assignment_id}/plans",
    response_model=WorkPlanResponse | None,
    summary="Get the most recent plan version",
    description=(
        "Returns the newest plan version, or null when the assignment has never been planned. "
        "This endpoint never triggers generation, so it cannot fail because a provider is "
        "unavailable."
    ),
)
async def get_latest_plan(
    assignment_id: UUID,
    user: CurrentUser,
    db: Db,
) -> WorkPlanResponse | None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.latest_plan(assignment_id, db, include_draft=True)
    if plan is None:
        return None
    graph = await service.load_plan_graph(db, plan)
    return service.build_plan_response(
        plan, assignment=assignment, graph=graph, warnings=service.staleness_warnings(plan)
    )


@router.get(
    "/{assignment_id}/plans/summary",
    response_model=PlanSummaryResponse,
    summary="Plan progress at a glance",
    description=(
        "Counts and progress for the newest version, for a dashboard tile. Deliberately does "
        "not return tasks."
    ),
)
async def get_plan_summary(
    assignment_id: UUID,
    user: CurrentUser,
    db: Db,
) -> PlanSummaryResponse:
    await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.latest_plan(assignment_id, db, include_draft=True)
    if plan is None:
        raise AppError(404, "PLAN_NOT_FOUND", "This assignment has no plan yet.")
    return await service.build_plan_summary(plan, await service.load_plan_graph(db, plan))


@router.get(
    "/{assignment_id}/plans/versions",
    response_model=PageResponse[PlanSummaryResponse],
    summary="List plan versions, newest first",
    description=(
        "The version history for an assignment. Each version is a separate record, so this is "
        'how a client answers "what changed" and "which one did I approve".'
    ),
)
async def list_plan_versions(
    assignment_id: UUID,
    params: Annotated[PageParams, Query()],
    user: CurrentUser,
    db: Db,
) -> PageResponse[PlanSummaryResponse]:
    await load_owned_assignment(assignment_id, user.id, db)
    # `page` is 1-based, so the offset is (page - 1) * page_size.
    offset = (params.page - 1) * params.page_size
    plans = await service.list_plan_versions(
        assignment_id, db, limit=params.page_size, offset=offset
    )
    total = await service.count_plan_versions(assignment_id, db)
    return PageResponse[PlanSummaryResponse](
        items=[
            await service.build_plan_summary(plan, await service.load_plan_graph(db, plan))
            for plan in plans
        ],
        page=Page(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=max(1, -(-total // params.page_size)),
        ),
    )


@router.get(
    "/{assignment_id}/plans/preferences",
    response_model=PlanningPreferencesResponse,
    summary="Get planning preferences for the workspace",
    description=(
        "The style, guidance level and session length a new plan will be generated with. These "
        "are workspace-wide because they describe how this student likes to work, not one "
        "assignment."
    ),
)
async def get_preferences(
    assignment_id: UUID,
    user: CurrentUser,
    db: Db,
) -> PlanningPreferencesResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return await service.get_preferences(assignment.workspace_id, db)


@router.put(
    "/{assignment_id}/plans/preferences",
    response_model=PlanningPreferencesResponse,
    summary="Set planning preferences",
    description=(
        "Sets the preferences used for the next generated plan. Existing versions are not "
        "rewritten: a plan records the preferences it was built with, so old versions stay "
        "reproducible."
    ),
)
async def set_preferences(
    assignment_id: UUID,
    payload: PlanningPreferencesRequest,
    user: CurrentUser,
    db: Db,
) -> PlanningPreferencesResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    stored = await service.save_preferences(assignment.workspace_id, db, payload)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.PLAN_PREFERENCES_UPDATED,
        entity_type="PlanningPreference",
        entity_id=assignment.workspace_id,
        metadata={
            "planning_style": stored.planning_style,
            "guidance_level": stored.guidance_level,
            "session_length": stored.session_length,
            "ai_mode": stored.ai_mode,
        },
    )
    await db.commit()
    return stored


@router.get(
    "/{assignment_id}/plans/{plan_id}",
    response_model=WorkPlanResponse,
    summary="Get one specific plan version",
    description=(
        "Returns a specific version. Useful for diffing a regeneration against what was "
        "approved, and for reading a plan that is no longer the latest."
    ),
)
async def get_plan(
    assignment_id: UUID,
    plan_id: UUID,
    user: CurrentUser,
    db: Db,
) -> WorkPlanResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.load_owned_plan(assignment_id, plan_id, user.id, db)
    graph = await service.load_plan_graph(db, plan)
    return service.build_plan_response(
        plan, assignment=assignment, graph=graph, warnings=service.staleness_warnings(plan)
    )


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/plans/{plan_id}/approve",
    response_model=WorkPlanResponse,
    summary="Approve a plan",
    description=(
        "Approves a plan version, which is the moment it becomes the authoritative schedule. "
        "This is a human decision: nothing is executed.\n\n"
        "An approved version is immutable; to change it, regenerate. A plan with unresolved "
        "graph problems, or one built on a superseded analysis, cannot be approved."
    ),
)
async def approve_plan(
    assignment_id: UUID,
    plan_id: UUID,
    payload: PlanApproveRequest,
    user: CurrentUser,
    db: Db,
) -> WorkPlanResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.load_owned_plan(assignment_id, plan_id, user.id, db)

    graph = await service.load_plan_graph(db, plan)
    if graph.violations:
        raise AppError(
            409,
            "PLAN_GRAPH_INVALID",
            "This plan has validation problems and cannot be approved.",
            {"violations": graph.violations},
        )

    plan = await service.approve_plan(
        db,
        plan,
        user_id=user.id,
        note=payload.note,
        analysis=await latest_analysis(assignment.id, db),
        assignment=assignment,
    )
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.PLAN_APPROVED,
        entity_type="AcademicWorkPlan",
        entity_id=plan.id,
        metadata={"version": plan.version, "note": payload.note},
    )
    await db.commit()
    return service.build_plan_response(plan, assignment=assignment, graph=graph)


@router.patch(
    "/{assignment_id}/plans/{plan_id}",
    response_model=WorkPlanResponse,
    summary="Edit plan-level fields",
    description=(
        "Updates the title, summary or status of a plan that is still under review. Refused "
        "for an approved plan: regenerate instead, so the change is recorded as a new version "
        "rather than rewriting the one that was agreed to."
    ),
)
async def update_plan(
    assignment_id: UUID,
    plan_id: UUID,
    payload: PlanUpdateRequest,
    user: CurrentUser,
    db: Db,
) -> WorkPlanResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.load_owned_plan(assignment_id, plan_id, user.id, db)
    plan = await service.update_plan(db, plan, payload.changes())
    await _record(
        db,
        assignment,
        plan,
        user,
        AuditEventType.PLAN_EDITED,
        entity_type="AcademicWorkPlan",
        entity_id=plan.id,
        metadata={"fields": sorted(payload.changes())},
    )
    await db.commit()
    graph = await service.load_plan_graph(db, plan)
    return service.build_plan_response(plan, assignment=assignment, graph=graph)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/plans/{plan_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a task to a plan",
    description=(
        "Adds a task by hand. A task added this way is marked as the student's own, so a later "
        "regeneration keeps it.\n\n"
        "The graph is revalidated after the change, so a dependency that would create a cycle "
        "is refused with the reason rather than stored."
    ),
)
async def create_task(
    assignment_id: UUID,
    plan_id: UUID,
    payload: TaskCreateRequest,
    user: CurrentUser,
    db: Db,
) -> TaskResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.load_owned_plan(assignment_id, plan_id, user.id, db)
    task = await service.add_task(db, plan, **payload.service_kwargs())
    await _record(
        db,
        assignment,
        plan,
        user,
        AuditEventType.PLAN_TASK_ADDED,
        entity_type="PlanTask",
        entity_id=task.id,
        metadata={"task_key": task.key, "title": task.title},
    )
    await db.commit()
    return service.build_task_response(task, await service.load_plan_graph(db, plan))


@router.patch(
    "/{assignment_id}/plans/{plan_id}/tasks/{task_key}",
    response_model=TaskResponse,
    summary="Edit a task",
    description=(
        "Edits a task and revalidates the graph. An edited task is marked as the student's "
        "own, so a later regeneration will not discard it.\n\n"
        "Send `depends_on`, `related_requirements` or `related_deliverables` to replace those "
        "relationships wholesale; omit a field to leave it alone."
    ),
)
async def update_task(
    assignment_id: UUID,
    plan_id: UUID,
    task_key: str,
    payload: TaskUpdateRequest,
    user: CurrentUser,
    db: Db,
) -> TaskResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.load_owned_plan(assignment_id, plan_id, user.id, db)
    task = await service.task_by_key(plan.id, task_key, db)
    task = await service.update_task(db, plan, task, **payload.service_kwargs())
    await _record(
        db,
        assignment,
        plan,
        user,
        AuditEventType.PLAN_TASK_UPDATED,
        entity_type="PlanTask",
        entity_id=task.id,
        metadata={"task_key": task.key, "fields": sorted(payload.service_kwargs())},
    )
    await db.commit()
    return service.build_task_response(task, await service.load_plan_graph(db, plan))


@router.delete(
    "/{assignment_id}/plans/{plan_id}/tasks/{task_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a task",
    description=(
        "Removes a task along with its dependencies and traceability rows. The graph is "
        "revalidated afterwards, and the delete is refused if it would leave another task "
        "depending on something that no longer exists."
    ),
)
async def delete_task(
    assignment_id: UUID,
    plan_id: UUID,
    task_key: str,
    user: CurrentUser,
    db: Db,
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.load_owned_plan(assignment_id, plan_id, user.id, db)
    task = await service.task_by_key(plan.id, task_key, db)
    await service.delete_task(db, plan, task)
    await _record(
        db,
        assignment,
        plan,
        user,
        AuditEventType.PLAN_TASK_DELETED,
        entity_type="PlanTask",
        entity_id=task.id,
        metadata={"task_key": task.key, "title": task.title},
    )
    await db.commit()


@router.post(
    "/{assignment_id}/plans/{plan_id}/tasks/reorder",
    response_model=list[TaskResponse],
    summary="Reorder tasks",
    description=(
        "Sets the display order from an explicit list of task keys. Every key in the plan must "
        "appear exactly once, so a client cannot silently drop a task by forgetting it.\n\n"
        "Reordering changes presentation, not dependencies. A task can still be blocked by one "
        "that appears later in the list."
    ),
)
async def reorder_tasks(
    assignment_id: UUID,
    plan_id: UUID,
    payload: TaskReorderRequest,
    user: CurrentUser,
    db: Db,
) -> list[TaskResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    plan = await service.load_owned_plan(assignment_id, plan_id, user.id, db)
    rows = await service.reorder_tasks(db, plan, payload.task_keys)
    await _record(
        db,
        assignment,
        plan,
        user,
        AuditEventType.PLAN_TASKS_REORDERED,
        entity_type="AcademicWorkPlan",
        entity_id=plan.id,
        metadata={"order": [row.key for row in rows]},
    )
    await db.commit()
    graph = await service.load_plan_graph(db, plan)
    return [service.build_task_response(row, graph) for row in rows]
