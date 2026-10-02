"""Phase 5 DTOs: the Professional Agent Runtime.

The shapes here are the runtime's public contract. Three conventions carry over
from Phases 3 and 4 and are worth restating:

* ``*Response`` models describe what the API returns and are built with
  ``from_attributes`` so they can be constructed straight from ORM rows.
* Vocabulary is domain-agnostic. There is no ``run_unit_tests`` field because a
  field like that would mean this runtime only works for programming
  assignments; domain specifics travel in free text the agent produced.
* Nothing here exposes reasoning. ``AgentDecisionResponse`` carries an action, a
  one-sentence reason and an outcome. There is no field for a chain of thought
  because there is no such thing to store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.models.enums import (
    AcademicTaskStatus,
    AgentAction,
    AgentArtifactStatus,
    AgentArtifactType,
    AgentCheckpointStatus,
    AgentCheckpointType,
    AgentEventType,
    AgentExecutionStatus,
    AgentExecutorKind,
    AgentFailureCategory,
    AgentRunMode,
    AgentRunStatus,
)
from app.schemas.common import APIModel

# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class AgentRunCreateRequest(APIModel):
    """Start a run over an assignment's approved plan."""

    model_config = APIModel.model_config | {"extra": "forbid"}

    #: ``SUPERVISED`` asks before it acts where a decision is genuinely the
    #: student's. ``AUTONOMOUS`` runs to the next real wall.
    mode: AgentRunMode = AgentRunMode.SUPERVISED
    #: Optional ceiling. Lowering it is always allowed; raising it above the
    #: configured maximum is refused so the budget cannot be widened from the UI.
    max_cost: float | None = Field(default=None, gt=0.0)
    #: Deterministic key. Two identical requests return the same run rather than
    #: starting two.
    idempotency_key: str | None = Field(default=None, max_length=64)


class AgentRunActionRequest(APIModel):
    """Pause, resume, cancel or retry."""

    model_config = APIModel.model_config | {"extra": "forbid"}

    #: Required for resume-from-blocked: what the student did about the wall.
    note: str | None = Field(default=None, max_length=500)


class AgentCheckpointResolveRequest(APIModel):
    """The student's answer to a checkpoint."""

    model_config = APIModel.model_config | {"extra": "forbid"}

    #: Required for CLARIFICATION and MISSING_INFORMATION, where the answer is
    #: used in the next step's context.
    response: str | None = Field(default=None, max_length=4_000)
    #: One of the offered options. Validated against what was actually offered,
    #: so a stale client cannot invent an option.
    selected_option: str | None = Field(default=None, max_length=200)
    #: ``true`` approves, ``false`` rejects. Only meaningful for APPROVAL/REVIEW.
    approved: bool | None = None
    #: Ask the agent to try the rejected step again.
    retry: bool = False


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class AgentRunResponse(APIModel):
    """A run, as the UI needs it."""

    id: UUID
    assignment_id: UUID
    plan_id: UUID | None = None
    plan_version: int
    status: AgentRunStatus
    mode: AgentRunMode
    #: Always populated for a stopped run. This is the difference between a run
    #: that is waiting on you and one that is merely slow.
    paused_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_category: AgentFailureCategory | None = None
    model: str | None = None
    model_tier: str | None = None
    routing_reason: str | None = None
    iteration_count: int
    max_iterations: int
    max_cost: float
    estimated_cost: float
    token_usage: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime
    #: Progress from the plan's task graph. Present on the detail endpoint so the
    #: workspace can render the bar without a second request.
    progress: AgentProgressResponse | None = None
    #: Set when the run has a task waiting for a student decision.
    awaiting_checkpoint_id: UUID | None = None
    #: Set when there is an actionable error worth surfacing.
    can_resume: bool = False
    can_retry: bool = False


class AgentProgressResponse(APIModel):
    total: int
    completed: int
    skipped: int
    in_progress: int
    blocked: int
    remaining: int
    percent: int


class AgentTaskResponse(APIModel):
    """One task from the plan, with this run's progress against it."""

    id: UUID
    key: str
    title: str
    type: str
    status: AcademicTaskStatus
    priority: str
    position: int
    #: True when this run has attempted it at least once.
    attempted: bool = False
    #: Attempts made in this run.
    attempts: int = 0
    last_status: AgentExecutionStatus | None = None
    last_summary: str | None = None
    #: Artifacts this run produced for the task.
    artifact_ids: list[UUID] = Field(default_factory=list)
    #: True when the runtime may mark it done without a human.
    can_auto_complete: bool = True


class AgentExecutionResponse(APIModel):
    """One attempt at one task. Every attempt is kept, including failures."""

    id: UUID
    task_id: UUID
    task_key: str
    attempt: int
    status: AgentExecutionStatus
    executor: AgentExecutorKind
    model: str | None = None
    model_tier: str | None = None
    summary: str | None = None
    reason: str | None = None
    output: dict[str, Any] | None = None
    failure_category: AgentFailureCategory | None = None
    error_code: str | None = None
    error_message: str | None = None
    validation_errors: list[dict[str, Any]] | None = None
    token_usage: dict[str, Any] | None = None
    estimated_cost: float | None = None
    duration_ms: int | None = None
    started_at: datetime
    completed_at: datetime | None = None


class AgentArtifactResponse(APIModel):
    id: UUID
    run_id: UUID
    task_id: UUID | None = None
    title: str
    artifact_type: AgentArtifactType
    status: AgentArtifactStatus
    content: str
    metadata_json: dict[str, Any] | None = None
    revision: int
    deliverable_key: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentCheckpointResponse(APIModel):
    id: UUID
    run_id: UUID
    task_id: UUID | None = None
    checkpoint_type: AgentCheckpointType
    status: AgentCheckpointStatus
    question: str
    context: str | None = None
    options: list[str] | None = None
    #: Present only after resolution. Kept in the response so the activity trail
    #: shows what was asked and what came back.
    response: str | None = None
    requested_at: datetime
    resolved_at: datetime | None = None
    expires_at: datetime | None = None


class AgentEventResponse(APIModel):
    id: UUID
    sequence: int
    event_type: AgentEventType
    summary: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    task_id: UUID | None = None
    created_at: datetime


class AgentDecisionResponse(APIModel):
    """A structured decision and what the runtime did about it.

    ``reason`` is the only explanation stored. There is no field for internal
    reasoning because the runtime never requests or persists any.
    """

    id: UUID
    iteration: int
    action: AgentAction
    reason: str
    expected_output: str | None = None
    confidence: float
    model: str | None = None
    model_tier: str | None = None
    payload: dict[str, Any] | None = None
    outcome: str | None = None
    executed_at: datetime


class AgentRunDetailResponse(AgentRunResponse):
    """Run plus the things the workspace needs in one round trip."""

    tasks: list[AgentTaskResponse] = Field(default_factory=list)
    executions: list[AgentExecutionResponse] = Field(default_factory=list)
    artifacts: list[AgentArtifactResponse] = Field(default_factory=list)
    checkpoints: list[AgentCheckpointResponse] = Field(default_factory=list)
    events: list[AgentEventResponse] = Field(default_factory=list)
    decisions: list[AgentDecisionResponse] = Field(default_factory=list)
    #: What the context builder used, and what it had to leave out. The answer to
    #: "why didn't the agent see my document?" lives here.
    context_provenance: list[dict[str, Any]] = Field(default_factory=list)


class AgentToolResponse(APIModel):
    """One available tool. The list is complete and closed."""

    name: str
    description: str
    permissions: list[str]


class AgentCapabilitiesResponse(APIModel):
    """What this runtime can do, and — more importantly — what it cannot.

    Exposed so the UI and the security documentation have one source of truth for
    the boundary. ``absent_capabilities`` is not decoration: it is the honest
    answer to "can the agent run my code?", and a client should be able to read it
    rather than infer it.
    """

    tools: list[AgentToolResponse]
    executors: list[str]
    modes: list[AgentRunMode]
    actions: list[AgentAction]
    #: Capabilities this runtime deliberately does not have. There is no setting
    #: that turns any of them on.
    absent_capabilities: list[str]
    limits: dict[str, Any]


# Rebuild the forward reference declared above.
AgentRunResponse.model_rebuild()


def build_agent_capabilities(
    *,
    tools: list[AgentToolResponse],
    executors: list[str],
    limits: dict[str, Any],
) -> AgentCapabilitiesResponse:
    return AgentCapabilitiesResponse(
        tools=tools,
        executors=executors,
        modes=[AgentRunMode.SUPERVISED, AgentRunMode.AUTONOMOUS],
        actions=list(AgentAction),
        absent_capabilities=[
            "shell",
            "command execution",
            "code execution",
            "subprocess",
            "filesystem access",
            "outbound network",
            "web browsing",
            "autonomous web research",
            "credential access",
            "self-approval of work",
        ],
        limits=limits,
    )
