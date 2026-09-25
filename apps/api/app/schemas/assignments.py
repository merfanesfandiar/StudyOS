"""Request and response models for assignment specifications.

The specification is deliberately split across grouped modules:

* ``schemas/assignments.py`` - the assignment itself and its structured children
* ``schemas/specification.py`` - the assembled specification, readiness report,
  summary, dependency graph, version history and activity feed
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    AssignmentStatus,
    ConstraintSeverity,
    ConstraintType,
    DeliverableStatus,
    DeliverableType,
    RequirementPriority,
    RequirementStatus,
    RequirementType,
    TechnologyCategory,
)
from app.schemas.common import APIModel, PageParams
from app.schemas.documents import DocumentResponse

# Statuses a client may set directly. ``READY_FOR_ANALYSIS`` is deliberately
# absent: it can only be reached through the readiness gate, and the two
# analysis states are reserved for the future AI layer.
CLIENT_SETTABLE_STATUSES: frozenset[AssignmentStatus] = frozenset(
    {
        AssignmentStatus.DRAFT,
        AssignmentStatus.INCOMPLETE,
        AssignmentStatus.COMPLETED,
        AssignmentStatus.ARCHIVED,
    }
)


_STATUS_DESCRIPTION = (
    "A client may only set "
    + ", ".join(sorted(item.value for item in CLIENT_SETTABLE_STATUSES))
    + ". READY_FOR_ANALYSIS is reached through the readiness gate, and the analysis"
    " states are reserved for the future AI layer. Anything else is rejected with"
    " STATUS_NOT_CLIENT_SETTABLE."
)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Deadline must include a timezone")
    return value.astimezone(UTC)


class RequirementCreate(APIModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    priority: RequirementPriority = RequirementPriority.MEDIUM
    type: RequirementType = RequirementType.OTHER
    status: RequirementStatus = RequirementStatus.TODO
    is_required: bool = True
    position: int | None = Field(default=None, ge=0, le=100000)
    parent_id: UUID | None = None


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    priority: RequirementPriority | None = None
    type: RequirementType | None = None
    status: RequirementStatus | None = None
    is_required: bool | None = None
    position: int | None = Field(default=None, ge=0, le=100000)
    parent_id: UUID | None = None


class RequirementResponse(APIModel):
    id: UUID
    assignment_id: UUID
    code: str
    sequence: int
    title: str
    description: str | None
    priority: RequirementPriority
    type: RequirementType
    status: RequirementStatus
    is_required: bool
    position: int
    parent_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DependencyCreate(APIModel):
    depends_on_id: UUID
    note: str | None = Field(default=None, max_length=500)


class DependencyResponse(APIModel):
    id: UUID
    requirement_id: UUID
    depends_on_id: UUID
    depends_on_code: str
    depends_on_title: str
    note: str | None
    created_at: datetime


class ConstraintCreate(APIModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=5000)
    value: str | None = Field(default=None, max_length=500)
    type: ConstraintType = ConstraintType.OTHER
    severity: ConstraintSeverity = ConstraintSeverity.WARNING
    position: int | None = Field(default=None, ge=0, le=100000)


class ConstraintUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    value: str | None = Field(default=None, max_length=500)
    type: ConstraintType | None = None
    severity: ConstraintSeverity | None = None
    position: int | None = Field(default=None, ge=0, le=100000)


class ConstraintResponse(APIModel):
    id: UUID
    assignment_id: UUID
    title: str
    description: str
    value: str | None
    type: ConstraintType
    severity: ConstraintSeverity
    position: int
    created_at: datetime
    updated_at: datetime


class CriterionCreate(APIModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    weight: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    position: int | None = Field(default=None, ge=0, le=100000)


class CriterionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    weight: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    position: int | None = Field(default=None, ge=0, le=100000)


class CriterionResponse(APIModel):
    id: UUID
    assignment_id: UUID
    title: str
    description: str | None
    weight: Decimal
    position: int
    created_at: datetime
    updated_at: datetime


class DeliverableCreate(APIModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    type: DeliverableType = DeliverableType.DOCUMENT
    status: DeliverableStatus = DeliverableStatus.PENDING
    is_required: bool = True
    position: int | None = Field(default=None, ge=0, le=100000)


class DeliverableUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    type: DeliverableType | None = None
    status: DeliverableStatus | None = None
    is_required: bool | None = None
    position: int | None = Field(default=None, ge=0, le=100000)


class DeliverableResponse(APIModel):
    id: UUID
    assignment_id: UUID
    title: str
    description: str | None
    type: DeliverableType
    status: DeliverableStatus
    is_required: bool
    position: int
    created_at: datetime
    updated_at: datetime


class TechnologyCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)
    version: str | None = Field(default=None, max_length=50)
    category: TechnologyCategory = TechnologyCategory.OTHER


class TechnologyResponse(APIModel):
    id: UUID
    workspace_id: UUID
    name: str
    version: str | None
    category: TechnologyCategory
    created_at: datetime


class TagCreate(APIModel):
    name: str = Field(min_length=1, max_length=60)


class TagResponse(APIModel):
    id: UUID
    workspace_id: UUID
    name: str
    created_at: datetime


class AssignmentCreate(APIModel):
    course_id: UUID
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    deadline: datetime | None = None
    status: AssignmentStatus = Field(
        default=AssignmentStatus.DRAFT,
        description=_STATUS_DESCRIPTION,
    )

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)


class AssignmentUpdate(BaseModel):
    course_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    deadline: datetime | None = None
    status: AssignmentStatus | None = Field(default=None, description=_STATUS_DESCRIPTION)

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)


class AssignmentSummary(APIModel):
    id: UUID
    title: str
    deadline: datetime | None
    status: AssignmentStatus
    course_id: UUID
    course_name: str
    course_code: str


class AssignmentListItem(AssignmentSummary):
    description: str | None
    readiness_score: int
    readiness_state: AssignmentStatus
    requirements_count: int
    completed_requirements_count: int
    criteria_total: Decimal
    deadline_state: str
    updated_at: datetime


class AssignmentResponse(AssignmentSummary):
    workspace_id: UUID
    description: str | None
    readiness_score: int
    ready_for_analysis_at: datetime | None
    created_at: datetime
    updated_at: datetime
    requirements: list[RequirementResponse] = Field(default_factory=list)
    constraints: list[ConstraintResponse] = Field(default_factory=list)
    criteria: list[CriterionResponse] = Field(default_factory=list)
    deliverables: list[DeliverableResponse] = Field(default_factory=list)
    technologies: list[TechnologyResponse] = Field(default_factory=list)
    tags: list[TagResponse] = Field(default_factory=list)
    documents: list[DocumentResponse] = Field(default_factory=list)
    criteria_total: Decimal = Decimal("0.00")


class AssignmentListParams(PageParams):
    """Query parameters for ``GET /api/v1/assignments``.

    Filtering, sorting and pagination all happen in the database. ``search``
    matches the title, the description, the course name and code, and any tag
    attached to the assignment.
    """

    course_id: UUID | None = None
    status: AssignmentStatus | None = None
    readiness: AssignmentStatus | None = None
    tag: str | None = Field(default=None, max_length=60)
    search: str | None = Field(default=None, max_length=200)
    deadline_before: datetime | None = None
    deadline_after: datetime | None = None
    sort_by: str = "updated_at"
    sort_direction: str = "desc"

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, value: str) -> str:
        allowed = {"deadline", "created_at", "updated_at", "title", "readiness_score"}
        if value not in allowed:
            raise ValueError(f"sort_by must be one of {sorted(allowed)}")
        return value

    @field_validator("sort_direction")
    @classmethod
    def validate_sort_direction(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"asc", "desc"}:
            raise ValueError("sort_direction must be 'asc' or 'desc'")
        return normalized

    @field_validator("deadline_before", "deadline_after")
    @classmethod
    def validate_deadline(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)
