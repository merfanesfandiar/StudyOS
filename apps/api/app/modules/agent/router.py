"""Agent runtime endpoints.

Every route is scoped to an assignment the caller owns, and every route that
mutates a run names the transition it performs rather than offering a generic
"set status" verb. That is deliberate: the state machine in
``app.modules.agent.state_machine`` is the authority on what may happen, and a
router that accepted arbitrary status changes would quietly become a second,
unaudited one.

Three rules shape this router:

* **A run is created, not started.** ``POST /runs`` returns a ``CREATED`` run
  whose budget has already been snapshotted. Starting is a separate call, so a
  client that loses its connection between the two has not half-started work.
* **Reads never fail because a provider is down.** Only the two endpoints that
  actually execute work touch the model, and only those can be slow.
* **Everything is inspectable.** One run is one round trip: tasks, attempts,
  artifacts, checkpoints, events and decisions together, so the workspace never
  has to guess whether what it is showing is current.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import LLMUnavailableError, build_llm_provider
from app.ai.errors import LLMError
from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import User
from app.models.enums import (
    AgentAction,
    AgentExecutorKind,
    AgentRunMode,
)
from app.modules.agent import service
from app.modules.agent.tools import DEFAULT_TOOLS
from app.schemas.agent import (
    AgentCapabilitiesResponse,
    AgentCheckpointResolveRequest,
    AgentCheckpointResponse,
    AgentRunActionRequest,
    AgentRunCreateRequest,
    AgentRunDetailResponse,
    AgentRunResponse,
)

router = APIRouter(prefix="/api/v1/assignments", tags=["agent"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

settings = get_settings()


def _require_enabled() -> None:
    if not settings.agent_enabled:
        raise AppError(503, "AGENT_DISABLED", "The agent runtime is disabled.")


async def _run_response(
    run_id: UUID, assignment_id: UUID, user: User, db: AsyncSession
) -> AgentRunDetailResponse:
    """The run, validated into its response model on the way out.

    Validating here rather than at the client means a drift between what the
    service assembles and what the API promises fails in this test suite instead
    of silently dropping fields from the workspace.
    """
    loaded = await service.load_run_with_details(assignment_id, run_id, user.id, db)
    return AgentRunDetailResponse.model_validate(await service.load_run_detail(loaded, db))


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@router.get(
    "/{assignment_id}/agent/capabilities",
    response_model=AgentCapabilitiesResponse,
    summary="What this runtime can and cannot do",
    description=(
        "The closed set of tools, executors, modes and actions, plus the "
        "capabilities it deliberately does not have.\n\n"
        "Served so the UI and the security documentation share one source of "
        "truth for the boundary. Nothing here can be widened by configuration: "
        "there is no setting that grants the runtime a shell, a socket or a "
        "filesystem."
    ),
)
async def agent_capabilities(
    assignment_id: UUID,
    user: CurrentUser,
    db: Db,
) -> AgentCapabilitiesResponse:
    from app.modules.assignments.service import load_owned_assignment

    await load_owned_assignment(assignment_id, user.id, db)
    return AgentCapabilitiesResponse(
        tools=[
            {
                "name": name,
                "description": DEFAULT_TOOLS.get(name).description,
                "permissions": sorted(DEFAULT_TOOLS.get(name).permissions),
            }
            for name in DEFAULT_TOOLS.names()
        ],
        executors=[kind.value for kind in AgentExecutorKind],
        modes=[mode.value for mode in AgentRunMode],
        actions=[action.value for action in AgentAction],
        absent_capabilities=ABSENT_CAPABILITIES,
        # The runtime's own limits, so the UI can explain a stop in terms of the
        # budget that actually caused it rather than "something went wrong".
        limits={
            "max_iterations": settings.agent_max_iterations,
            "max_task_attempts": settings.agent_max_task_attempts,
            "max_consecutive_failures": settings.agent_max_consecutive_failures,
            "max_cost_per_run": settings.agent_max_cost_per_run,
            "max_cost_per_step": settings.agent_max_cost_per_step,
            "max_artifacts": settings.agent_max_artifacts,
            "max_context_chars": settings.agent_max_context_chars,
            "step_timeout_seconds": settings.agent_step_timeout_seconds,
            "heartbeat_timeout_seconds": settings.agent_heartbeat_timeout_seconds,
            "checkpoint_ttl_seconds": settings.agent_checkpoint_ttl_seconds,
            "allow_autonomous_review": settings.agent_allow_autonomous_review,
        },
    )


#: The answer to "can the agent run my code, read my disk, or go online?".
#: Deliberately a constant rather than something derived, so it stays honest even
#: if the tool registry grows: adding a capability to the runtime is a change that
#: has to be acknowledged here too.
ABSENT_CAPABILITIES: list[str] = [
    "execute_code",
    "shell",
    "filesystem_write",
    "network_access",
    "browser",
    "outbound_web_search",
    "credential_access",
    "email_or_messaging",
    "arbitrary_http",
    "background_scheduler",
    "cross_assignment_data",
]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/agent/runs",
    status_code=status.HTTP_201_CREATED,
    summary="Create a run over the approved plan",
    description=(
        "Creates a ``CREATED`` run bound to the current approved plan version.\n\n"
        "Refuses unless the assignment has an approved, non-stale plan: the agent "
        "executes work a student has agreed to, it does not decide what the work "
        "is. The run's budget is snapshotted here, so a later settings change "
        "cannot widen or shrink a run that is already in flight.\n\n"
        "Passing an `idempotency_key` makes a repeated request return the existing "
        "run rather than starting a second one. Creating a run does not execute "
        "anything -- call the start endpoint for that."
    ),
)
async def create_agent_run(
    assignment_id: UUID,
    payload: AgentRunCreateRequest,
    user: CurrentUser,
    db: Db,
) -> AgentRunDetailResponse:
    _require_enabled()
    run = await service.create_run(
        assignment_id,
        user,
        db,
        mode=payload.mode,
        max_cost=payload.max_cost,
        idempotency_key=payload.idempotency_key,
    )
    await db.commit()
    return await _run_response(run.id, assignment_id, user, db)


@router.get(
    "/{assignment_id}/agent/runs",
    summary="List an assignment's runs, newest first",
)
async def list_agent_runs(
    assignment_id: UUID,
    user: CurrentUser,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, list[AgentRunResponse]]:
    from app.modules.assignments.service import load_owned_assignment

    await load_owned_assignment(assignment_id, user.id, db)
    runs = await service.recent_runs(assignment_id, db, limit=limit)
    return {"items": [await service.load_run_summary(r, db) for r in runs]}


@router.get(
    "/{assignment_id}/agent/runs/{run_id}",
    summary="One run with everything the workspace needs",
    description=(
        "Tasks, attempts, artifacts, checkpoints, events and decisions in a single "
        "response.\n\n"
        "Returning the whole picture together is what lets the UI avoid showing a "
        "run state that has already changed underneath it."
    ),
)
async def get_agent_run(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> AgentRunDetailResponse:
    await service.load_owned_run(assignment_id, run_id, user.id, db)
    return await _run_response(run_id, assignment_id, user, db)


@router.post(
    "/{assignment_id}/agent/runs/{run_id}/start",
    summary="Start a created run",
    description=(
        "Executes steps until the run needs the student, hits a budget, or "
        "finishes.\n\n"
        "This is the only endpoint that does work, so it is the only one that can "
        "be slow or depend on a provider. It returns immediately when the run "
        "reaches a wall it cannot pass on its own -- waiting for you is a normal "
        "outcome, not an error."
    ),
)
async def start_agent_run(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> AgentRunDetailResponse:
    _require_enabled()
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    await service.start_run(run, user, db)

    provider = None
    try:
        provider = build_llm_provider(settings)
    except LLMUnavailableError:
        # The deterministic executors still make progress without a model, so a
        # provider outage degrades the run rather than stranding it. The routed
        # model on the run stays empty and the response says so via the events.
        provider = None

    try:
        await service.execute_run(run, user, db, provider=provider)
    except LLMError as exc:  # pragma: no cover - provider-specific
        await db.rollback()
        raise AppError(502, "AGENT_PROVIDER_ERROR", str(exc)) from exc
    await db.commit()
    return await _run_response(run_id, assignment_id, user, db)


@router.post(
    "/{assignment_id}/agent/runs/{run_id}/pause",
    summary="Pause a run the student wants to stop",
)
async def pause_agent_run(
    assignment_id: UUID,
    run_id: UUID,
    payload: AgentRunActionRequest,
    user: CurrentUser,
    db: Db,
) -> AgentRunDetailResponse:
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    await service.pause_run(run, user, db, reason=payload.note or "Paused by the student.")
    await db.commit()
    return await _run_response(run_id, assignment_id, user, db)


@router.post(
    "/{assignment_id}/agent/runs/{run_id}/resume",
    summary="Resume a paused, waiting or blocked run",
    description=(
        "Refuses to resume a blocked run until the wall is actually resolved, and "
        "refuses to resume a terminal one at all.\n\n"
        "Resuming continues from the recorded position rather than restarting, so "
        "work already done is not redone."
    ),
)
async def resume_agent_run(
    assignment_id: UUID,
    run_id: UUID,
    payload: AgentRunActionRequest,
    user: CurrentUser,
    db: Db,
) -> AgentRunDetailResponse:
    _require_enabled()
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    await service.resume_run(run, user, db, note=payload.note)

    provider = None
    try:
        provider = build_llm_provider(settings)
    except LLMUnavailableError:
        provider = None
    await service.execute_run(run, user, db, provider=provider)
    await db.commit()
    return await _run_response(run_id, assignment_id, user, db)


@router.post(
    "/{assignment_id}/agent/runs/{run_id}/cancel",
    summary="Cancel a run",
    description=(
        "Terminal and idempotent in effect: a cancelled run never resumes, and its "
        "artifacts stay readable so finished thinking is not thrown away."
    ),
)
async def cancel_agent_run(
    assignment_id: UUID,
    run_id: UUID,
    payload: AgentRunActionRequest,
    user: CurrentUser,
    db: Db,
) -> AgentRunDetailResponse:
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    await service.cancel_run(run, user, db, reason=payload.note or "Cancelled by the student.")
    await db.commit()
    return await _run_response(run_id, assignment_id, user, db)


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{assignment_id}/agent/runs/{run_id}/checkpoints/pending",
    summary="The question a run is currently waiting on",
    description=(
        "Returns ``null`` when nothing is pending, so a client can poll this to "
        "know whether it owes the student an answer without inspecting the whole "
        "run."
    ),
)
async def pending_checkpoint(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> AgentCheckpointResponse | None:
    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    checkpoint = await service.pending_checkpoint(run, db)
    if checkpoint is None:
        return None
    return AgentCheckpointResponse.model_validate(checkpoint)


@router.post(
    "/{assignment_id}/agent/runs/{run_id}/checkpoints/{checkpoint_id}/resolve",
    summary="Answer the question a run is waiting on",
    description=(
        "Records the student's answer and puts the run back in motion.\n\n"
        "A `selected_option` is checked against the options actually offered, so a "
        "stale client cannot resolve a checkpoint with an answer that was never "
        "asked for."
    ),
)
async def resolve_checkpoint(
    assignment_id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    payload: AgentCheckpointResolveRequest,
    user: CurrentUser,
    db: Db,
) -> AgentRunDetailResponse:
    _require_enabled()
    from app.models import AgentCheckpoint

    run = await service.load_owned_run(assignment_id, run_id, user.id, db)
    checkpoint = await db.get(AgentCheckpoint, checkpoint_id)
    if checkpoint is None or checkpoint.run_id != run.id:
        raise AppError(404, "AGENT_CHECKPOINT_NOT_FOUND", "Checkpoint not found.")

    await service.resolve_checkpoint(
        checkpoint,
        run,
        user,
        db,
        response=payload.response,
        selected_option=payload.selected_option,
        approved=payload.approved,
        retry=payload.retry,
    )

    provider = None
    try:
        provider = build_llm_provider(settings)
    except LLMUnavailableError:
        provider = None
    await service.execute_run(run, user, db, provider=provider)
    await db.commit()
    return await _run_response(run_id, assignment_id, user, db)


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


@router.post(
    "/{assignment_id}/agent/recover",
    summary="Reclaim runs abandoned by a stopped worker",
    description=(
        "Pauses runs whose worker stopped reporting and expires questions nobody "
        "answered in time.\n\n"
        "Paused, never resumed automatically: re-entering a loop whose last step may "
        "already have written a draft is not the runtime's call to make."
    ),
)
async def recover_assignment_runs(
    assignment_id: UUID,
    user: CurrentUser,
    db: Db,
) -> dict[str, Any]:
    from app.modules.agent.recovery import recover_stale_runs
    from app.modules.assignments.service import load_owned_assignment

    await load_owned_assignment(assignment_id, user.id, db)
    # Scoped to this assignment on purpose: recovery pauses runs, and a
    # student-triggered pause must never reach another student's work.
    report = await recover_stale_runs(db, settings, assignment_id=assignment_id)
    await db.commit()
    return report.as_dict()
