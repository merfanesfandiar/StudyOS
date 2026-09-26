"""Phase 4 DTOs: the Academic Planning Engine.

Two families live here and the distinction matters:

* ``PlannerOutput`` and its children describe what a *provider must return*.
  These are validated and repaired before anything is persisted, exactly like
  ``AnalyzerOutput`` in Phase 3.
* The ``*Response`` and ``*Request`` models describe the API surface.

Planning vocabulary is generic on purpose. There is no task type for writing a
unit test or running a titration, because a plan that only works for one kind of
assignment is not a planning engine. Domain-specific wording travels in titles,
descriptions and acceptance criteria.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AcademicTaskPriority,
    AcademicTaskStatus,
    AcademicTaskType,
    AIMode,
    ComplexityLevel,
    EffortLevel,
    GuidanceLevel,
    ModelTier,
    PlanningRunStatus,
    PlanningStyle,
    PlanStatus,
    PlanTrigger,
    SessionLength,
)
from app.schemas.analysis import CONFIDENCE
from app.schemas.common import APIModel

#: A plan with more milestones than this is a list, not a set of checkpoints.
MAX_MILESTONES = 8

#: Upper bound on acceptance criteria per task. A task with twenty criteria is
#: not checkable, which defeats the point of stating them.
MAX_ACCEPTANCE_CRITERIA = 8


# ---------------------------------------------------------------------------
# Provider output
# ---------------------------------------------------------------------------


class PlannedTask(BaseModel):
    """One unit of academic work.

    ``dependencies`` references other tasks by their plan-local key rather than
    by database id, because a plan does not exist yet when the model produces it.
    Keys rather than positions, so a partial regeneration can add a task without
    renumbering every edge in the plan.
    """

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    type: AcademicTaskType = AcademicTaskType.OTHER
    priority: AcademicTaskPriority = AcademicTaskPriority.MEDIUM
    estimated_effort: EffortLevel = EffortLevel.MEDIUM
    min_minutes: int | None = Field(default=None, ge=0, le=100_000)
    max_minutes: int | None = Field(default=None, ge=0, le=100_000)
    #: Keys of tasks that must finish first.
    depends_on: list[str] = Field(default_factory=list, max_length=40)
    #: Planning-contract keys (``R1``, ``W2``) this task exists to serve.
    related_requirements: list[str] = Field(default_factory=list, max_length=40)
    #: Planning-contract deliverable keys (``D1``) this task contributes to.
    related_deliverables: list[str] = Field(default_factory=list, max_length=40)
    verification_method: str | None = Field(default=None, max_length=300)
    acceptance_criteria: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("depends_on", "related_requirements", "related_deliverables")
    @classmethod
    def _no_self_reference(cls, value: list[str], info: Any) -> list[str]:
        key = info.data.get("key")
        if key and key in value:
            raise ValueError(f"task {key} cannot reference itself")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def _bound_criteria(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_ACCEPTANCE_CRITERIA:
            raise ValueError(
                f"a task may state at most {MAX_ACCEPTANCE_CRITERIA} acceptance criteria"
            )
        return [item for item in (part.strip() for part in value) if item]


class PlannedMilestone(BaseModel):
    """A meaningful checkpoint. The planner is capped at ``MAX_MILESTONES``."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=1000)
    #: Keys of the tasks whose completion reaches this milestone.
    task_keys: list[str] = Field(default_factory=list, max_length=60)


class PlannedVerificationPoint(BaseModel):
    """A check the student performs on their own work.

    Planning metadata only. The verification *engine* belongs to a later phase, so
    nothing here executes anything.
    """

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=1000)
    method: str = Field(default="MANUAL_REVIEW", max_length=100)
    task_keys: list[str] = Field(default_factory=list, max_length=60)
    related_requirements: list[str] = Field(default_factory=list, max_length=40)


class PlannedRisk(BaseModel):
    """A planning risk, distinct from an analysis risk.

    An analysis risk is a threat the brief already contains. A planning risk is a
    threat introduced by the plan itself: too little time, an unverified
    prerequisite, an estimate that does not fit the deadline.
    """

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=1000)
    severity: str = Field(default="WARNING", max_length=20)
    mitigation: str | None = Field(default=None, max_length=1000)
    related_task_keys: list[str] = Field(default_factory=list, max_length=60)


class PlannerOutput(BaseModel):
    """Exactly what a planner provider must return.

    Unknown extra fields are ignored so a chatty model does not fail a run.
    Missing tasks, out-of-range confidence and dangling references are still
    rejected by the validator.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=2000)
    objectives: list[str] = Field(default_factory=list, max_length=20)
    tasks: list[PlannedTask] = Field(min_length=1)
    milestones: list[PlannedMilestone] = Field(default_factory=list, max_length=20)
    verification_points: list[PlannedVerificationPoint] = Field(default_factory=list, max_length=20)
    risks: list[PlannedRisk] = Field(default_factory=list, max_length=20)
    estimated_effort: EffortLevel = EffortLevel.MEDIUM
    min_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    max_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    confidence: float = CONFIDENCE


# ---------------------------------------------------------------------------
# API requests
# ---------------------------------------------------------------------------


class PlanGenerateRequest(BaseModel):
    """Ask for a plan.

    ``force`` re-plans even when an identical request already produced a plan.
    Without it a repeated call is idempotent and does not bill a second time.
    """

    model_config = ConfigDict(extra="forbid")

    analysis_id: UUID | None = Field(
        default=None,
        description="Plan against this analysis. Defaults to the latest non-stale one.",
    )
    force: bool = False
    planning_style: PlanningStyle | None = None
    guidance_level: GuidanceLevel | None = None
    session_length: SessionLength | None = None
    ai_mode: AIMode | None = None
    #: Caller-supplied deduplication key. A repeat with the same key returns the
    #: plan that was already generated instead of creating a version and billing
    #: a second call.
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)
    reason: str | None = Field(default=None, max_length=200)


class PlanRegenerateRequest(BaseModel):
    """Re-plan, preserving what the student authored.

    ``scope`` narrows regeneration. ``NONE`` re-plans the whole plan;
    ``MILESTONES`` re-derives milestones against the current tasks; ``TASKS``
    re-derives tasks while keeping milestones that still apply. Regeneration
    always creates a new version and never overwrites the approved one.
    """

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(default="TASKS", max_length=20)
    reason: str | None = Field(default=None, max_length=200)
    force: bool = False
    planning_style: PlanningStyle | None = None
    guidance_level: GuidanceLevel | None = None
    session_length: SessionLength | None = None
    ai_mode: AIMode | None = None
    #: When false, tasks the student authored or edited by hand are carried into
    #: the new version. When true, the new version is entirely the planner's.
    preserve_user_edits: bool = True
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        allowed = {"TASKS", "MILESTONES", "NONE"}
        if value not in allowed:
            raise ValueError(f"scope must be one of {sorted(allowed)}")
        return value


class PlanApproveRequest(BaseModel):
    """Human approval. The plan is not authoritative until this succeeds."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=1000)


class PlanUpdateRequest(BaseModel):
    """Edit plan-level fields. Task edits go through the task endpoints.

    A plan can only be edited while it is under review. An approved plan is
    immutable, and the way to change it is to regenerate, so "what did I approve"
    stays answerable.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=240)
    summary: str | None = Field(default=None, max_length=2000)
    #: ``status`` is deliberately not editable here. Approval and staleness are
    #: state transitions owned by their own endpoints: a client that can PATCH a
    #: plan straight to ``APPROVED`` would skip the graph check and the staleness
    #: check, and produce an approved plan nobody ever reviewed.
    #: ``is_stale`` is likewise derived, and a client that can clear it can
    #: silence the one warning that their plan no longer matches the assignment.

    def changes(self) -> dict[str, Any]:
        """The fields the client actually set.

        Absent fields are dropped so ``update_plan`` does not null out values the
        client never mentioned.
        """
        return {
            name: value
            for name, value in (
                ("title", self.title),
                ("summary", self.summary),
            )
            if value is not None
        }


class TaskCreateRequest(BaseModel):
    """Add a student-authored task.

    Marked ``is_user_authored`` so a later regeneration preserves it instead of
    quietly deleting work the student did by hand.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    type: AcademicTaskType = AcademicTaskType.OTHER
    priority: AcademicTaskPriority = AcademicTaskPriority.MEDIUM
    estimated_effort: EffortLevel = EffortLevel.MEDIUM
    depends_on: list[str] = Field(default_factory=list, max_length=40)
    related_requirements: list[str] = Field(default_factory=list, max_length=40)
    related_deliverables: list[str] = Field(default_factory=list, max_length=40)
    verification_method: str | None = Field(default=None, max_length=300)
    acceptance_criteria: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)
    position: int | None = Field(default=None, ge=0, le=1000)

    def service_kwargs(self) -> dict[str, Any]:
        """Map onto ``service.add_task``, which stores enum *values*.

        Kept here so the router never has to know that a request enum becomes a
        string column, and so a new field has one obvious place to be wired.
        """
        data = self.model_dump(exclude={"type", "priority", "estimated_effort"})
        data["task_type"] = self.type.value
        data["priority"] = self.priority.value
        data["estimated_effort"] = self.estimated_effort.value
        return data


class TaskUpdateRequest(BaseModel):
    """Edit a task. Every field is optional; unset fields are left alone."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    type: AcademicTaskType | None = None
    status: AcademicTaskStatus | None = None
    priority: AcademicTaskPriority | None = None
    estimated_effort: EffortLevel | None = None
    min_minutes: int | None = Field(default=None, ge=0, le=100_000)
    max_minutes: int | None = Field(default=None, ge=0, le=100_000)
    depends_on: list[str] | None = None
    related_requirements: list[str] | None = None
    related_deliverables: list[str] | None = None
    verification_method: str | None = Field(default=None, max_length=300)
    acceptance_criteria: list[str] | None = None
    resources: list[str] | None = None
    notes: str | None = Field(default=None, max_length=2000)

    def service_kwargs(self) -> dict[str, Any]:
        """Split into scalar column changes and whole-list relationship replaces.

        Scalars go through ``changes`` so an omitted field is left alone.
        ``depends_on`` and the two traceability lists are *replacements*, not
        merges, so they are only passed when the client actually sent them.
        """
        scalar = (
            "title",
            "description",
            "status",
            "priority",
            "estimated_effort",
            "min_minutes",
            "max_minutes",
            "verification_method",
            "acceptance_criteria",
            "resources",
            "notes",
        )
        changes = {name: getattr(self, name) for name in scalar if getattr(self, name) is not None}
        changes = {k: v for k, v in changes.items() if k not in {"type"}}
        kwargs: dict[str, Any] = {"changes": changes}
        if self.type is not None:
            changes["type"] = self.type
        for name in ("depends_on", "related_requirements", "related_deliverables"):
            value = getattr(self, name)
            if value is not None:
                kwargs[name] = value
        return kwargs


class TaskReorderRequest(BaseModel):
    """Reorder tasks.

    Only the order changes, so this never calls the model. ``task_keys`` is the
    complete new order; a partial list is rejected rather than interpreted,
    because a partial reorder has no single obvious meaning.
    """

    model_config = ConfigDict(extra="forbid")

    task_keys: list[str] = Field(min_length=1, max_length=200)


class PlanningPreferencesRequest(BaseModel):
    """Per-workspace planning and AI preferences."""

    model_config = ConfigDict(extra="forbid")

    planning_style: PlanningStyle | None = None
    guidance_level: GuidanceLevel | None = None
    session_length: SessionLength | None = None
    ai_mode: AIMode | None = None


# ---------------------------------------------------------------------------
# API responses
# ---------------------------------------------------------------------------


class TaskResponse(APIModel):
    """A task as the client sees it, with its traceability already resolved.

    ``depends_on`` comes back as task keys rather than database ids, because that
    is the vocabulary the UI and the graph view speak. ``depends_on_ids`` is there
    for the rare caller that needs to address a task by id.
    """

    id: UUID
    key: str
    title: str
    description: str
    type: AcademicTaskType
    status: AcademicTaskStatus
    priority: AcademicTaskPriority
    position: int
    estimated_effort: EffortLevel
    min_minutes: int | None
    max_minutes: int | None
    verification_method: str | None
    acceptance_criteria: list[str]
    resources: list[str]
    notes: str | None
    is_user_authored: bool
    depends_on: list[str] = Field(default_factory=list)
    related_requirements: list[str] = Field(default_factory=list)
    related_deliverables: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(
        default_factory=list,
        description="Keys of incomplete predecessors. Drives the BLOCKED badge.",
    )


class MilestoneResponse(APIModel):
    id: UUID
    key: str
    title: str
    description: str | None
    position: int
    status: AcademicTaskStatus
    task_keys: list[str] = Field(default_factory=list)
    completed_task_count: int = 0
    task_count: int = 0


class VerificationPointResponse(BaseModel):
    key: str
    title: str
    description: str
    method: str
    task_keys: list[str] = Field(default_factory=list)
    related_requirements: list[str] = Field(default_factory=list)


class PlanRiskResponse(BaseModel):
    key: str
    description: str
    severity: str
    mitigation: str | None = None
    related_task_keys: list[str] = Field(default_factory=list)


class ScheduleRiskResponse(BaseModel):
    """Deterministic deadline check, computed rather than asserted.

    The point of this response is that it can say "18 to 24 estimated hours
    against 8 hours remaining" and let the student decide. It never claims the
    work will be finished on time.
    """

    level: ComplexityLevel
    estimated_minutes: int
    available_minutes: int | None
    #: True when the upper estimate exceeds the time remaining.
    is_overcommitted: bool
    summary: str
    factors: list[str] = Field(default_factory=list)


class WorkPlanResponse(APIModel):
    """A plan version, fully resolved for the client."""

    id: UUID
    assignment_id: UUID
    analysis_id: UUID | None
    version: int
    trigger: PlanTrigger
    reason: str
    changed_sections: list[str] | None
    title: str
    summary: str
    status: PlanStatus
    objectives: list[str]
    estimated_effort: EffortLevel
    min_minutes: int | None
    max_minutes: int | None
    is_stale: bool
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tasks: list[TaskResponse] = Field(default_factory=list)
    milestones: list[MilestoneResponse] = Field(default_factory=list)
    verification_points: list[VerificationPointResponse] = Field(default_factory=list)
    risks: list[PlanRiskResponse] = Field(default_factory=list)
    schedule_risk: ScheduleRiskResponse | None = None
    progress_percentage: int = 0
    validation_warnings: list[str] = Field(default_factory=list)


class PlanSummaryResponse(BaseModel):
    """A plan version without its tasks.

    The list endpoint returns these. A workspace with fifty assignments should not
    ship fifty full task graphs to render a list.
    """

    id: UUID
    assignment_id: UUID
    analysis_id: UUID | None
    version: int
    trigger: PlanTrigger
    title: str
    status: PlanStatus
    is_stale: bool
    task_count: int = 0
    completed_task_count: int = 0
    progress_percentage: int = 0
    estimated_effort: EffortLevel
    created_at: datetime
    approved_at: datetime | None


class PlanningRunResponse(APIModel):
    """One generation attempt. Telemetry, never chain-of-thought.

    ``routing_reason`` is the one-line explanation written for a human, not the
    router's internal scoring.
    """

    id: UUID
    assignment_id: UUID
    plan_id: UUID | None
    status: PlanningRunStatus
    provider: str
    model: str
    model_tier: ModelTier
    routing_reason: str
    routing_confidence: float
    complexity: ComplexityLevel
    fell_back_from_tier: ModelTier | None
    prompt_version: str
    duration_ms: int | None
    token_usage: dict[str, Any] | None
    estimated_cost: float | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class ModelSelectionResponse(BaseModel):
    """The router's decision, explained for a human.

    Exposed so the "which model did this use" panel can show something truthful.
    ``reason`` is deliberately one sentence: the router's internal scoring is not
    the student's business.
    """

    model_tier: ModelTier
    model: str
    reason: str
    confidence: float
    complexity: ComplexityLevel
    complexity_factors: list[str] = Field(default_factory=list)
    ai_mode: AIMode
    #: True when the student's FAST preference was overridden for correctness.
    overridden: bool = False
    override_reason: str | None = None


class PlanningPreferencesResponse(APIModel):
    planning_style: PlanningStyle
    guidance_level: GuidanceLevel
    session_length: SessionLength
    ai_mode: AIMode
