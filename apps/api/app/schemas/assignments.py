from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.models.enums import AssignmentStatus, RequirementPriority, RequirementType
from app.schemas.common import APIModel
from app.schemas.documents import DocumentResponse


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


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    priority: RequirementPriority | None = None
    type: RequirementType | None = None


class RequirementResponse(APIModel):
    id: UUID
    assignment_id: UUID
    title: str
    description: str | None
    priority: RequirementPriority
    type: RequirementType
    created_at: datetime
    updated_at: datetime


class ConstraintCreate(APIModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=5000)
    value: str | None = Field(default=None, max_length=500)


class ConstraintUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    value: str | None = Field(default=None, max_length=500)


class ConstraintResponse(APIModel):
    id: UUID
    assignment_id: UUID
    title: str
    description: str
    value: str | None
    created_at: datetime
    updated_at: datetime


class CriterionCreate(APIModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    weight: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class CriterionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    weight: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)


class CriterionResponse(APIModel):
    id: UUID
    assignment_id: UUID
    title: str
    description: str | None
    weight: Decimal
    created_at: datetime
    updated_at: datetime

    @field_serializer("weight")
    def serialize_weight(self, value: Decimal) -> float:
        return float(value)


class AssignmentCreate(APIModel):
    course_id: UUID
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    deadline: datetime | None = None
    status: AssignmentStatus = AssignmentStatus.DRAFT

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value)


class AssignmentUpdate(BaseModel):
    course_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    deadline: datetime | None = None
    status: AssignmentStatus | None = None

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


class AssignmentResponse(AssignmentSummary):
    workspace_id: UUID
    description: str | None
    created_at: datetime
    updated_at: datetime
    requirements: list[RequirementResponse] = Field(default_factory=list)
    constraints: list[ConstraintResponse] = Field(default_factory=list)
    criteria: list[CriterionResponse] = Field(default_factory=list)
    documents: list[DocumentResponse] = Field(default_factory=list)
    criteria_total: Decimal = Decimal("0.00")

    @field_serializer("criteria_total")
    def serialize_criteria_total(self, value: Decimal) -> float:
        return float(value)
