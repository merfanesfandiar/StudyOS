"""Contracts for the Phase 10 Academic Verification Engine.

Two layers, kept separate exactly like the analysis module does:

1. **Snapshots** (``AssignmentSnapshot`` etc.) — frozen copies of the data a
   verification sees. Validators are pure functions of snapshots: they never
   touch the database, the network or the filesystem. That is what makes them
   unit-testable and what keeps an untrusted artifact from reaching application
   code paths.
2. **Results** (``ValidatorResult`` etc.) — the structured output every
   validator must produce. Unknown extra fields are ignored rather than fatal,
   but missing fields, invalid statuses and out-of-range confidence are
   enforced.

The honesty rules are structural, not aspirational:

* Every result carries a :class:`~app.models.enums.VerificationMethod` label
  saying *how* it was reached. An ``AI_ASSESSMENT`` result can never count as
  independent evidence for the claim it explains.
* Every result carries ``limitations`` — what was *not* checked. An empty
  limitations list on an unverified claim is a bug, not a virtue.
* ``UNVERIFIED`` is the default verdict. A check that could not run is never
  reported as passing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar, Literal
from uuid import UUID

from app.models.enums import (
    AcademicDomain,
    VerificationLevel,
    VerificationMethod,
    VerificationSeverity,
    VerificationStatus,
)
from pydantic import BaseModel, ConfigDict, Field

#: Qualitative confidence bands. The engine does not invent decimal confidence
#: percentages it cannot justify; deterministic checks report ``HIGH`` only when
#: they actually executed, heuristics report at most ``MODERATE``, and anything
#: that did not run reports ``NONE`` with an explicit limitation.
Confidence = Literal["HIGH", "MODERATE", "LOW", "NONE"]
CONFIDENCE_HIGH: Confidence = "HIGH"
CONFIDENCE_MODERATE: Confidence = "MODERATE"
CONFIDENCE_LOW: Confidence = "LOW"
CONFIDENCE_NONE: Confidence = "NONE"


class ArtifactSnapshot(BaseModel):
    """A frozen, bounded view of one artifact to verify."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    title: str = Field(max_length=240)
    artifact_type: str = Field(max_length=30)
    content: str
    revision: int = Field(ge=1)
    worker_name: str | None = None
    metadata_json: dict[str, Any] | None = None


class RequirementSnapshot(BaseModel):
    """A frozen assignment requirement (authoritative, instructor-stated)."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    code: str = Field(max_length=40)
    title: str = Field(max_length=240)
    description: str | None = None
    is_required: bool = True
    priority: str = Field(default="MEDIUM", max_length=20)


class CriterionSnapshot(BaseModel):
    """A frozen rubric criterion (authoritative when from ``evaluation_criteria``)."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    title: str = Field(max_length=240)
    description: str | None = None
    weight: Decimal = Field(ge=0, le=100)
    authoritative: bool = True


class DeliverableSnapshot(BaseModel):
    """A frozen deliverable (what the student must hand in)."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    title: str = Field(max_length=240)
    artifact_type: str = Field(default="DOCUMENT", max_length=30)
    is_required: bool = True


class AssignmentSnapshot(BaseModel):
    """Everything verification needs to know about the assignment."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    workspace_id: UUID
    title: str = Field(max_length=240)
    description: str | None = None
    #: Effective classified types, e.g. ``["PROGRAMMING", "REPORT"]``. Empty when
    #: the assignment has not been analysed yet; validators then run only the
    #: type-agnostic checks and say so.
    assignment_types: list[str] = Field(default_factory=list)
    academic_domain: str | None = None
    requirements: list[RequirementSnapshot] = Field(default_factory=list)
    criteria: list[CriterionSnapshot] = Field(default_factory=list)
    deliverables: list[DeliverableSnapshot] = Field(default_factory=list)


class ValidatorFinding(BaseModel):
    """One problem (or observation) a validator found."""

    model_config = ConfigDict(extra="ignore")

    severity: VerificationSeverity = VerificationSeverity.MEDIUM
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2000)
    requirement_codes: list[str] = Field(default_factory=list)
    artifact_ids: list[UUID] = Field(default_factory=list)
    recommendation: str | None = Field(default=None, max_length=1000)
    #: Set only for findings produced without a real check. A heuristic finding
    #: must say so; it must never be written as if it were observed fact.
    heuristic: bool = False


class ValidatorEvidence(BaseModel):
    """Evidence a validator collected for its conclusions.

    ``content`` is a bounded, self-contained record (a test output, a recomputed
    statistic, a parsed citation list) — never an AI's paraphrase of what it
    believes. An AI's explanation of its own reasoning is not evidence.
    """

    model_config = ConfigDict(extra="ignore")

    kind: str = Field(max_length=40)
    source: str = Field(max_length=200)
    method: VerificationMethod = VerificationMethod.DETERMINISTIC
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    content: str = Field(default="", max_length=4000)
    requirement_codes: list[str] = Field(default_factory=list)
    artifact_ids: list[UUID] = Field(default_factory=list)


class RequirementVerdict(BaseModel):
    """One requirement's verification outcome with traceability.

    ``evidence_refs`` index into the validator result's ``evidence`` list, so
    every verdict is auditable back to the artifact text or check output that
    produced it.
    """

    model_config = ConfigDict(extra="ignore")

    requirement_id: UUID
    code: str = Field(max_length=40)
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    explanation: str = Field(max_length=1000)
    evidence_refs: list[int] = Field(default_factory=list)


class ValidatorDeclaration(BaseModel):
    """What a validator is, before it ever runs.

    The registry and the pipeline make every scheduling decision from this
    declaration; validators are never selected by hardcoding ``if domain ==``
    branches in the pipeline.
    """

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=80)
    #: Bumped whenever the check's logic changes meaningfully. Cached results
    #: from a different version are never reused.
    version: int = Field(ge=1, default=1)
    level: VerificationLevel
    #: ``None`` means any domain; otherwise the exact set this validator covers.
    domains: frozenset[AcademicDomain] | None = None
    assignment_types: frozenset[str] | None = None
    artifact_types: frozenset[str] | None = None
    determinism: Literal["deterministic", "heuristic", "ai_assisted"] = "deterministic"
    requires_external: bool = False
    #: Whether the validator needs the (optional) sandbox execution gateway.
    requires_execution: bool = False
    description: str = Field(min_length=1, max_length=500)
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)


class ValidatorResult(BaseModel):
    """The complete output of one validator execution."""

    model_config = ConfigDict(extra="ignore")

    validator: str = Field(max_length=80)
    version: int = Field(ge=1)
    level: VerificationLevel
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    summary: str = Field(default="", max_length=2000)
    method: VerificationMethod = VerificationMethod.DETERMINISTIC
    #: Qualitative, not a decimal. See the module docstring.
    confidence: Confidence = CONFIDENCE_NONE
    executed: bool = False
    #: What was NOT checked. Non-empty unless every input was fully checked.
    limitations: list[str] = Field(default_factory=list)
    findings: list[ValidatorFinding] = Field(default_factory=list)
    evidence: list[ValidatorEvidence] = Field(default_factory=list)
    requirement_verdicts: list[RequirementVerdict] = Field(default_factory=list)


class VerificationContext:
    """What a validator may reach.

    Deliberately narrow, mirroring ``ToolContext``: snapshots of the assignment
    and artifacts, and — only when a deployment enabled it — the sandbox
    execution gateway. There is no session, no request and no network client on
    this object; a validator cannot touch the database or the host.
    """

    __slots__ = ("assignment", "artifacts", "execution", "artifact_ids", "requirement_ids")

    def __init__(
        self,
        assignment: AssignmentSnapshot,
        artifacts: list[ArtifactSnapshot],
        *,
        execution: Any | None = None,
        artifact_ids: frozenset[UUID] | None = None,
        requirement_ids: frozenset[UUID] | None = None,
    ) -> None:
        self.assignment = assignment
        self.artifacts = artifacts
        #: Present only when the deployment enabled the Phase 7 sandbox.
        self.execution = execution
        #: Partial-verification scopes. ``None`` means "no narrowing".
        self.artifact_ids = artifact_ids
        self.requirement_ids = requirement_ids

    def scoped_artifacts(self) -> list[ArtifactSnapshot]:
        if self.artifact_ids is None:
            return list(self.artifacts)
        return [a for a in self.artifacts if a.id in self.artifact_ids]

    def scoped_requirements(self) -> list[RequirementSnapshot]:
        reqs = self.assignment.requirements
        if self.requirement_ids is None:
            return list(reqs)
        return [r for r in reqs if r.id in self.requirement_ids]


class VerificationValidator:
    """Base class for validators.

    Subclasses set :attr:`declaration` and implement :meth:`verify`. They must
    be side-effect free with respect to application state and must catch their
    own domain errors — a validator that crashes returns a ``FAILED`` result
    with a limitation, never a silent pass (the pipeline enforces the latter
    even for a misbehaving validator).
    """

    declaration: ClassVar[ValidatorDeclaration]

    #: Cheap, honest filter the registry applies before invoking ``verify``.
    def applies_to(self, ctx: VerificationContext) -> bool:  # noqa: PLR6301
        return True

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        raise NotImplementedError


def not_applicable_result(validator: VerificationValidator, reason: str) -> ValidatorResult:
    """A typed "nothing to check" result for validators whose inputs are absent."""
    d = validator.declaration
    return ValidatorResult(
        validator=d.name,
        version=d.version,
        level=d.level,
        status=VerificationStatus.NOT_APPLICABLE,
        summary=reason,
        confidence=CONFIDENCE_NONE,
        executed=False,
        limitations=[reason],
    )
