"""Schemas for the assembled assignment specification.

``AssignmentSpecificationResponse`` is the stable contract between the core
application and any future AI layer. It is deterministic and fully
self-describing: an analyzer never has to read UI state, re-parse free text, or
call back into the assignment domain. See
``docs/architecture/future-ai-contract.md``.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssignmentStatus, CompletenessCheckStatus, RequirementStatus
from app.schemas.assignments import (
    AssignmentSummary,
    ConstraintResponse,
    CriterionResponse,
    DeliverableResponse,
    RequirementResponse,
    TagResponse,
    TechnologyResponse,
)
from app.schemas.common import PageParams
from app.schemas.documents import DocumentResponse


class CompletenessCheck(BaseModel):
    """One deterministic check performed by the completeness analyzer."""

    field: str
    label: str
    status: CompletenessCheckStatus
    message: str
    weight: int
    blocking: bool


class ReadinessReport(BaseModel):
    """Deterministic completeness verdict. Not an AI confidence score."""

    score: int = Field(ge=0, le=100, description="Weighted completeness percentage.")
    is_complete: bool = Field(
        description="True when no check failed and the score is at least the completeness bar."
    )
    is_ready_for_analysis: bool = Field(
        description="True when no blocking check failed. This is the readiness gate."
    )
    completeness_bar: int
    failing_checks: list[str] = Field(default_factory=list)
    warning_checks: list[str] = Field(default_factory=list)
    checks: list[CompletenessCheck] = Field(default_factory=list)


class SpecificationSummary(BaseModel):
    """Compact, machine-readable summary of a specification."""

    assignment: AssignmentSummary
    requirements_total: int
    requirements_required: int
    requirements_completed: int
    requirements_verified: int
    requirements_by_status: dict[str, int]
    critical_requirements: int
    constraints_total: int
    constraints_by_severity: dict[str, int]
    criteria_total: Decimal
    criteria_count: int
    criteria_balanced: bool
    deliverables_total: int
    deliverables_completed: int
    technologies: list[str]
    tags: list[str]
    resources_total: int
    readiness: AssignmentStatus
    readiness_score: int
    specification_version: int


class AssignmentSpecificationResponse(BaseModel):
    """The complete structured specification of one assignment."""

    model_config = ConfigDict(
        json_schema_extra={"description": "Complete, machine-readable assignment specification."}
    )

    assignment: AssignmentSummary
    description: str | None
    criteria_total: Decimal
    requirements: list[RequirementResponse]
    constraints: list[ConstraintResponse]
    evaluation_criteria: list[CriterionResponse]
    deliverables: list[DeliverableResponse]
    technologies: list[TechnologyResponse]
    tags: list[TagResponse]
    resources: list[DocumentResponse]
    readiness: ReadinessReport
    summary: SpecificationSummary
    specification_version: int
    updated_at: datetime


class ValidationResponse(BaseModel):
    """Result of an explicit specification validation request."""

    is_valid: bool
    readiness: ReadinessReport
    validated_at: datetime
    specification_version: int


class DependencyNode(BaseModel):
    id: UUID
    code: str
    title: str
    status: RequirementStatus
    priority: str
    depth: int = Field(
        description="Longest distance from a node with no dependencies. 0 means nothing blocks it."
    )


class DependencyEdge(BaseModel):
    requirement_id: UUID
    requirement_code: str
    depends_on_id: UUID
    depends_on_code: str


class DependencyGraph(BaseModel):
    """Acyclic requirement dependency graph, ready for a future planner."""

    nodes: list[DependencyNode]
    edges: list[DependencyEdge]
    execution_order: list[str] = Field(
        default_factory=list, description="Requirement codes in a safe execution order."
    )
    has_cycles: bool = False


class VersionSummary(BaseModel):
    version: int
    change_summary: str
    created_at: datetime
    created_by_id: UUID | None


class VersionDetail(VersionSummary):
    snapshot: dict[str, Any]


class ActivityEvent(BaseModel):
    id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID | None
    change_summary: str | None = None
    metadata: dict[str, Any]
    created_at: datetime


class ActivityParams(PageParams):
    event_type: str | None = Field(default=None, max_length=80)
