"""API contracts for the Academic Verification Engine.

Response shapes mirror the persisted rows. The rubric payload carries an
explicit ``estimated`` flag everywhere a score appears: StudyOS never presents
its estimate as an instructor grade.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import VerificationRunStatus, VerificationTrigger


class VerificationTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(
        default="FULL",
        description="FULL, ARTIFACT (with artifact_ids) or REQUIREMENT (with requirement_ids).",
    )
    artifact_ids: list[UUID] = Field(default_factory=list)
    requirement_ids: list[UUID] = Field(default_factory=list)
    re_verification_of: UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=100)


class VerificationRunSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    assignment_id: UUID
    status: VerificationRunStatus
    scope_kind: str
    trigger: VerificationTrigger
    verdict: str | None
    completion_percentage: int
    created_at: datetime
    finished_at: datetime | None
    previous_run_id: UUID | None = None


class VerificationFindingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    validator: str
    level: str
    severity: str
    title: str
    description: str
    recommendation: str | None
    requirement_codes: list[Any] | None
    artifact_ids: list[Any] | None
    heuristic: bool


class VerificationEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    validator: str
    kind: str
    source: str
    method: str
    status: str
    content: str


class RequirementVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requirement_id: UUID
    code: str
    status: str
    explanation: str


class RubricEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    criterion_id: UUID
    status: str
    score: float | None = Field(
        description="Normalised 0–1 estimate. None means 'no evidence', never 'zero'."
    )
    justification: str
    improvement: str | None


class VerificationReportResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    assignment_id: UUID
    status: VerificationRunStatus
    scope_kind: str
    trigger: VerificationTrigger
    verdict: str | None
    completion_percentage: int
    summary: dict[str, Any]
    findings: list[VerificationFindingResponse]
    evidence: list[VerificationEvidenceResponse]
    requirements: list[RequirementVerificationResponse]
    rubric: list[RubricEvaluationResponse]
    previous_run_id: UUID | None
    comparison: dict[str, Any] | None = None
    #: Server-built, validation-safe UI blocks for the Dynamic Agent Workspace.
    ui: dict[str, Any] | None = None


class VerificationRunListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[VerificationRunSummaryResponse]
    total: int
