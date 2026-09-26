"""Universal academic assignment analysis contracts.

This module defines three layers that must stay distinguishable:

1. ``AnalyzerOutput`` - the *structured LLM contract*. It is what a provider is
   asked to produce and what deterministic semantic validation checks. It is
   domain-agnostic: nothing here assumes an assignment is a programming project.
2. Persistence/response shapes derived from it (``AssignmentAnalysisResponse``).
3. ``PlanningContractResponse`` - the frozen, stable contract the Phase 4
   Planning Engine consumes. It never requires parsing raw model text.

Confidence is always in ``[0, 1]`` and is never certainty. Provenance is modeled
explicitly with ``SourceKind`` so the UI can distinguish explicit requirements
from AI inference, uncertain findings and missing information.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AcademicDomain,
    AnalysisReviewStatus,
    AnalysisRunStatus,
    AssignmentType,
    ClassificationSource,
    ConstraintSeverity,
    ConstraintType,
    EvidenceSourceType,
    FindingSeverity,
    QuestionPriority,
    QuestionStatus,
    RequirementCategory,
    RequirementPriority,
    ScopeLevel,
    SourceKind,
)

CONFIDENCE = Field(
    default=0.0,
    ge=0.0,
    le=1.0,
    description="Model confidence in [0, 1]. Never certainty; 0 means not reported.",
)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """A concise pointer back to the material a conclusion came from.

    Deliberately not chain-of-thought: only enough to explain the conclusion.
    """

    model_config = ConfigDict(extra="ignore")

    source_type: EvidenceSourceType
    source_id: str | None = Field(
        default=None, description="Requirement/criterion/deliverable/document id or code."
    )
    location: str | None = Field(default=None, description="e.g. REQ-003 or 'description'.")
    excerpt_reference: str | None = Field(
        default=None, max_length=500, description="Short paraphrase, not a long quote."
    )
    supports: str = Field(max_length=500, description="The claim this evidence supports.")
    confidence: float = CONFIDENCE


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TypeClassification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: AssignmentType
    confidence: float = CONFIDENCE
    rationale: str | None = Field(default=None, max_length=500)


class DomainClassification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    domain: AcademicDomain
    confidence: float = CONFIDENCE
    rationale: str | None = Field(default=None, max_length=500)


class ClassifiedType(BaseModel):
    """Effective assignment type: an AI classification plus any user correction."""

    type: AssignmentType
    confidence: float
    source: ClassificationSource
    rationale: str | None = None


class ClassifiedDomain(BaseModel):
    domain: AcademicDomain
    confidence: float
    source: ClassificationSource
    rationale: str | None = None


# ---------------------------------------------------------------------------
# Core analysis sections
# ---------------------------------------------------------------------------


class Objective(BaseModel):
    model_config = ConfigDict(extra="ignore")

    statement: str = Field(max_length=500)
    source: SourceKind = SourceKind.AI_INFERENCE
    confidence: float = CONFIDENCE


class NormalizedRequirement(BaseModel):
    """A requirement normalized for analysis, keeping traceability to its source.

    ``key`` is a stable local reference (``R1``) used by dependencies,
    deliverables and verification items within one analysis. It is not the
    authoritative ``REQ-003`` identity, which stays on the assignment.
    """

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    category: RequirementCategory = RequirementCategory.OTHER
    priority: RequirementPriority = RequirementPriority.MEDIUM
    required: bool = True
    source: SourceKind = SourceKind.AI_INFERENCE
    source_reference: str | None = Field(
        default=None,
        max_length=80,
        description="Authoritative REQ code/id when source is EXPLICIT.",
    )
    confidence: float = CONFIDENCE
    evidence: list[Evidence] = Field(default_factory=list)


class Ambiguity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    description: str = Field(max_length=1000)
    severity: FindingSeverity = FindingSeverity.WARNING
    affected_requirements: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    suggested_clarification: str | None = Field(default=None, max_length=1000)
    confidence: float = CONFIDENCE


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    description: str = Field(max_length=1000)
    conflicting_items: list[str] = Field(default_factory=list)
    severity: FindingSeverity = FindingSeverity.IMPORTANT
    evidence: list[Evidence] = Field(default_factory=list)
    clarification_needed: bool = True
    confidence: float = CONFIDENCE


class MissingInformation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    description: str = Field(max_length=1000)
    area: str = Field(default="OTHER", max_length=80)
    severity: FindingSeverity = FindingSeverity.WARNING
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = CONFIDENCE


class Assumption(BaseModel):
    """A labelled guess. Never promoted to an authoritative requirement."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    statement: str = Field(max_length=1000)
    confidence: float = CONFIDENCE
    evidence: list[Evidence] = Field(default_factory=list)


class Risk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    description: str = Field(max_length=1000)
    severity: FindingSeverity = FindingSeverity.WARNING
    affected_area: str = Field(default="OTHER", max_length=80)
    evidence: list[Evidence] = Field(default_factory=list)
    mitigation_hint: str | None = Field(default=None, max_length=1000)
    confidence: float = CONFIDENCE


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=20)
    priority: QuestionPriority = QuestionPriority.IMPORTANT
    question: str = Field(max_length=1000)
    rationale: str | None = Field(default=None, max_length=1000)
    related_requirements: list[str] = Field(default_factory=list)
    confidence: float = CONFIDENCE


# ---------------------------------------------------------------------------
# Deliverables, evaluation, scope, work areas, resources, dependencies
# ---------------------------------------------------------------------------


class DeliverableAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    #: ``None`` means the requirement status is genuinely unknown. A deliverable
    #: taken from authoritative data must be known (enforced semantically).
    required: bool | None = True
    expected_content: list[str] = Field(default_factory=list)
    format: str | None = Field(default=None, max_length=200)
    related_requirements: list[str] = Field(default_factory=list)
    verification_needs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(
        default_factory=list, description="Keys of other deliverables this one needs first."
    )
    uncertainty: SourceKind = SourceKind.AI_INFERENCE
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = CONFIDENCE


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=1000)
    #: Only set when the assignment states a weight. Never invented.
    weight: Decimal | None = Field(default=None, ge=0, le=100)
    related_requirements: list[str] = Field(default_factory=list)
    implied: bool = False
    confidence: float = CONFIDENCE


class EvaluationAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rubric_available: bool = False
    criteria: list[RubricCriterion] = Field(default_factory=list)
    implied_quality_expectations: list[str] = Field(default_factory=list)
    missing_rubric_information: list[str] = Field(default_factory=list)
    confidence: float = CONFIDENCE


class ScopeDimension(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: ScopeLevel = ScopeLevel.UNKNOWN
    rationale: str | None = Field(default=None, max_length=500)


class ScopeAnalysis(BaseModel):
    """Coarse, honest scope estimate. Never a claim of precise effort."""

    model_config = ConfigDict(extra="ignore")

    breadth: ScopeDimension = Field(default_factory=ScopeDimension)
    depth: ScopeDimension = Field(default_factory=ScopeDimension)
    research_intensity: ScopeDimension = Field(default_factory=ScopeDimension)
    reasoning_intensity: ScopeDimension = Field(default_factory=ScopeDimension)
    technical_complexity: ScopeDimension = Field(default_factory=ScopeDimension)
    writing_intensity: ScopeDimension = Field(default_factory=ScopeDimension)
    experimental_complexity: ScopeDimension = Field(default_factory=ScopeDimension)
    presentation_complexity: ScopeDimension = Field(default_factory=ScopeDimension)
    dependency_complexity: ScopeDimension = Field(default_factory=ScopeDimension)
    deliverable_count: int = Field(default=0, ge=0)
    requirement_count: int = Field(default=0, ge=0)
    overall: ScopeLevel = ScopeLevel.UNKNOWN
    confidence: float = CONFIDENCE


class WorkArea(BaseModel):
    """A high-level area of work. Not an executable task; Phase 4 plans those."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(min_length=1, max_length=20)
    title: str = Field(max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    category: RequirementCategory = RequirementCategory.OTHER
    related_requirements: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list, description="Keys of prerequisite areas.")
    origin: SourceKind = SourceKind.AI_INFERENCE
    confidence: float = CONFIDENCE


class ResourceInsight(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_id: str | None = None
    filename: str = Field(max_length=300)
    resource_type: str = Field(default="OTHER", max_length=30)
    role: str = Field(default="OTHER", max_length=80)
    relevant_sections: list[str] = Field(default_factory=list)
    referenced_concepts: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    terminology: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = CONFIDENCE


class ResourceAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resources: list[ResourceInsight] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    confidence: float = CONFIDENCE


class AnalysisDependency(BaseModel):
    """A generic dependency edge.

    Endpoints reference normalized requirement keys, work-area keys or
    deliverable keys, all of which exist in the same analysis. Programming is not
    special: ``predecessor -> successor`` expresses "needs first".
    """

    model_config = ConfigDict(extra="ignore")

    predecessor: str = Field(min_length=1, max_length=40)
    successor: str = Field(min_length=1, max_length=40)
    kind: str = Field(default="WORK_AREA", max_length=20)
    reason: str | None = Field(default=None, max_length=500)
    confidence: float = CONFIDENCE


class VerificationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(max_length=300)
    description: str = Field(max_length=1000)
    method: str = Field(
        default="OTHER",
        max_length=40,
        description="Generic method, e.g. PROOF_CHECK, CITATION_CHECK, CODE_TEST.",
    )
    applies_to: list[str] = Field(default_factory=list)
    confidence: float = CONFIDENCE


class VerificationStrategy(BaseModel):
    """How completion could later be verified. Not verification itself."""

    model_config = ConfigDict(extra="ignore")

    items: list[VerificationItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    confidence: float = CONFIDENCE


class SpecializedAnalysis(BaseModel):
    """One domain-specific analyzer's structured output.

    ``data`` is validated by the producing analyzer's own model before it is
    stored here, so the universal core never has to know the field names.
    """

    model_config = ConfigDict(extra="ignore")

    analyzer: str = Field(max_length=60, description="e.g. 'mathematics', 'programming'.")
    assignment_types: list[AssignmentType] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = Field(default=None, max_length=1000)
    confidence: float = CONFIDENCE


class ConstraintSnapshot(BaseModel):
    """Frozen copy of an authoritative constraint, for the planning contract."""

    id: UUID
    title: str
    description: str
    value: str | None = None
    type: ConstraintType = ConstraintType.OTHER
    severity: ConstraintSeverity = ConstraintSeverity.WARNING


# ---------------------------------------------------------------------------
# The structured LLM contract
# ---------------------------------------------------------------------------


class AnalyzerOutput(BaseModel):
    """Exactly what a provider must return and what validation checks.

    Unknown extra fields are ignored rather than fatal so a slightly chatty
    model does not fail a run; missing fields, invalid enums, out-of-range
    confidence and inconsistent references are all still enforced.
    """

    model_config = ConfigDict(extra="ignore")

    assignment_types: list[TypeClassification] = Field(min_length=1)
    academic_domains: list[DomainClassification] = Field(min_length=1)
    summary: str = Field(max_length=2000)
    objectives: list[Objective] = Field(default_factory=list)
    normalized_requirements: list[NormalizedRequirement] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    deliverables: list[DeliverableAnalysis] = Field(default_factory=list)
    evaluation: EvaluationAnalysis = Field(default_factory=EvaluationAnalysis)
    scope: ScopeAnalysis = Field(default_factory=ScopeAnalysis)
    work_areas: list[WorkArea] = Field(default_factory=list)
    resources: ResourceAnalysis = Field(default_factory=ResourceAnalysis)
    dependencies: list[AnalysisDependency] = Field(default_factory=list)
    verification: VerificationStrategy = Field(default_factory=VerificationStrategy)
    risks: list[Risk] = Field(default_factory=list)
    confidence: float = CONFIDENCE


# ---------------------------------------------------------------------------
# API response shapes
# ---------------------------------------------------------------------------


class QuestionResponse(BaseModel):
    id: UUID
    code: str
    priority: QuestionPriority
    status: QuestionStatus
    question: str
    rationale: str | None
    related_requirements: list[str] = Field(default_factory=list)
    answer: str | None = None
    answered_at: datetime | None = None
    position: int = 0


class AnalysisRunResponse(BaseModel):
    id: UUID
    assignment_id: UUID
    analysis_id: UUID | None
    status: AnalysisRunStatus
    provider: str
    model: str
    prompt_version: str
    specification_version: int
    input_hash: str
    output_hash: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    token_usage: dict[str, Any] | None
    estimated_cost: Decimal | None
    error_code: str | None
    error_message: str | None


class AssignmentAnalysisResponse(BaseModel):
    """The complete analysis plus human review state.

    ``payload`` fields are flattened for a convenient client shape. When a
    student has corrected a classification it appears here with
    ``source: USER``; the original AI rows remain auditable.
    """

    id: UUID
    assignment_id: UUID
    analysis_version: int
    specification_version: int
    specification_hash: str
    prompt_version: str
    provider: str
    model: str
    status: AnalysisReviewStatus
    is_stale: bool
    stale_at: datetime | None
    summary: str
    confidence: float

    assignment_types: list[ClassifiedType]
    academic_domains: list[ClassifiedDomain]
    objectives: list[Objective]
    normalized_requirements: list[NormalizedRequirement]
    constraints: list[ConstraintSnapshot]
    ambiguities: list[Ambiguity]
    contradictions: list[Contradiction]
    missing_information: list[MissingInformation]
    assumptions: list[Assumption]
    clarification_questions: list[QuestionResponse]
    deliverables: list[DeliverableAnalysis]
    evaluation: EvaluationAnalysis
    scope: ScopeAnalysis
    work_areas: list[WorkArea]
    resources: ResourceAnalysis
    dependencies: list[AnalysisDependency]
    verification: VerificationStrategy
    risks: list[Risk]
    specialized_analysis: list[SpecializedAnalysis]
    evidence: list[Evidence] = Field(
        default_factory=list, description="Flattened evidence index across the analysis."
    )

    edited: bool = False
    reviewed_at: datetime | None = None
    review_note: str | None = None
    created_at: datetime
    updated_at: datetime


class AnalysisRequest(BaseModel):
    """Optional controls for an analysis request."""

    model_config = ConfigDict(extra="forbid")

    force: bool = Field(
        default=False,
        description="Re-run even when an identical, non-stale analysis already exists.",
    )
    user_notes: str | None = Field(
        default=None, max_length=4000, description="Context the student wants the analyzer to use."
    )
    include_questions: bool = Field(
        default=True, description="Whether to generate clarification questions."
    )


class ClassificationCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    types: list[AssignmentType] | None = None
    domains: list[AcademicDomain] | None = None


class AnalysisEditRequest(BaseModel):
    """Human corrections layered on an analysis.

    Every field is optional. ``edits`` is a shallow overlay on the AI payload
    (for example replacing the ``ambiguities`` list to dismiss one). Authoritative
    assignment data is never touched.
    """

    model_config = ConfigDict(extra="forbid")

    types: list[AssignmentType] | None = None
    domains: list[AcademicDomain] | None = None
    edits: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=2000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class QuestionAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=4000)


class QuestionDismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Phase 4 contract
# ---------------------------------------------------------------------------


class PlanningContractRequirement(BaseModel):
    key: str
    title: str
    description: str | None
    category: RequirementCategory
    priority: RequirementPriority
    required: bool
    source_kind: SourceKind
    source_reference: str | None
    confidence: float


class PlanningContractDeliverable(BaseModel):
    key: str
    title: str
    description: str | None
    required: bool | None
    format: str | None
    related_requirements: list[str]
    verification_needs: list[str]
    depends_on: list[str]
    uncertainty: SourceKind
    confidence: float


class PlanningContractResponse(BaseModel):
    """Stable, structured input for the Phase 4 Planning Engine.

    Everything the planner needs, already validated and with no raw LLM text to
    parse. ``is_stale`` is a hard signal: a stale analysis must not be planned
    against silently.
    """

    analysis_id: UUID
    assignment_id: UUID
    analysis_version: int
    specification_version: int
    specification_hash: str
    prompt_version: str
    provider: str
    model: str
    is_stale: bool

    assignment_types: list[ClassifiedType]
    academic_domains: list[ClassifiedDomain]
    objectives: list[Objective]
    requirements: list[PlanningContractRequirement]
    constraints: list[ConstraintSnapshot]
    deliverables: list[PlanningContractDeliverable]
    dependencies: list[AnalysisDependency]
    work_areas: list[WorkArea]
    risks: list[Risk]
    verification_strategy: VerificationStrategy
    clarification_questions: list[QuestionResponse]
    specialized_analysis: list[SpecializedAnalysis]
    evaluation: EvaluationAnalysis
    scope: ScopeAnalysis
