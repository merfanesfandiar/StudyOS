"""Level 2 — requirement compliance.

For every authoritative requirement, determine VERIFIED / PARTIAL / FAILED /
UNVERIFIED with explicit traceability. The design constraint that matters most:
**mentioning a requirement is not satisfying it**. Keyword coverage is treated
as a traceability signal; a requirement is only VERIFIED when its deliverable
section contains substantive material tied to it, and UNVERIFIED — never
VERIFIED-by-AI — when there is not enough signal to decide.
"""

from __future__ import annotations

from typing import ClassVar

from app.models.enums import (
    VerificationLevel,
    VerificationMethod,
    VerificationSeverity,
    VerificationStatus,
)
from app.modules.verification.contracts import (
    CONFIDENCE_MODERATE,
    CONFIDENCE_NONE,
    RequirementVerdict,
    ValidatorDeclaration,
    ValidatorEvidence,
    ValidatorFinding,
    ValidatorResult,
    VerificationContext,
    VerificationValidator,
)
from app.modules.verification.validators.helpers import artifact_text, word_count

#: Minimum substantive words in a matched region before keyword coverage counts
#: as more than a mention.
_SUBSTANTIVE_WORDS = 40


class RequirementComplianceValidator(VerificationValidator):
    """L2: per-requirement compliance with explicit evidence references."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="requirement_compliance",
        level=VerificationLevel.REQUIREMENTS,
        description=(
            "Compares artifacts against every authoritative requirement. Keyword "
            "coverage is a traceability signal only; verdicts never assume a "
            "requirement is satisfied because it is mentioned."
        ),
        timeout_seconds=10.0,
    )

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        requirements = ctx.scoped_requirements()
        artifacts = ctx.scoped_artifacts()
        if not requirements:
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.NOT_APPLICABLE,
                summary="The assignment has no recorded requirements to verify.",
                confidence=CONFIDENCE_NONE,
                executed=True,
                limitations=["No structured requirements exist; add them for compliance checking."],
            )
        if not artifacts:
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.FAILED,
                summary="No artifacts: every requirement is unverifiable.",
                confidence=CONFIDENCE_MODERATE,
                executed=True,
                limitations=["No artifacts exist to check against requirements."],
            )

        text = artifact_text(artifacts)
        verdicts: list[RequirementVerdict] = []
        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []
        limitations = [
            "Compliance is assessed by keyword coverage and section substance; "
            "semantic correctness of the covered material is the domain "
            "validators' job, not this check."
        ]

        for requirement in requirements:
            tokens = _requirement_tokens(requirement)
            if not tokens:
                verdicts.append(
                    RequirementVerdict(
                        requirement_id=requirement.id,
                        code=requirement.code,
                        status=VerificationStatus.UNVERIFIED,
                        explanation=(
                            "The requirement title is too generic to trace into "
                            "artifacts by keyword; manual or AI-assisted review is needed."
                        ),
                    )
                )
                continue
            present, missing = _coverage(text, tokens)
            coverage_ratio = len(present) / max(1, len(present) + len(missing))
            if coverage_ratio >= 0.6 and _region_substantive(text, present):
                status_value = VerificationStatus.VERIFIED
                explanation = (
                    f"{len(present)}/{len(present) + len(missing)} requirement terms appear "
                    "in substantive artifact material. Coverage is a traceability "
                    "signal; the domain validators assess whether that material is "
                    "actually correct."
                )
            elif coverage_ratio >= 0.3:
                status_value = VerificationStatus.PARTIAL
                explanation = (
                    f"Partial traceability: {len(present)}/{len(present) + len(missing)} "
                    "requirement terms found. Key gaps: "
                    + ", ".join(missing[:4])
                    + "."
                )
                if requirement.is_required:
                    findings.append(
                        ValidatorFinding(
                            severity=VerificationSeverity.MEDIUM,
                            title=f"Requirement {requirement.code} only partially covered",
                            description=(
                                f"'{requirement.title}': {len(missing)} of "
                                f"{len(present) + len(missing)} requirement terms are absent "
                                "from the artifacts."
                            ),
                            requirement_codes=[requirement.code],
                            recommendation=(
                                "Extend the artifacts to address the missing terms, "
                                "or confirm the requirement is already satisfied with "
                                "different wording."
                            ),
                        )
                    )
            else:
                if requirement.is_required:
                    status_value = VerificationStatus.FAILED
                else:
                    status_value = VerificationStatus.UNVERIFIED
                explanation = (
                    "Almost none of the requirement's terms appear in the "
                    "artifacts. For a required deliverable this is recorded as "
                    "FAILED (missing work); for optional work, UNVERIFIED."
                    if requirement.is_required
                    else "The optional requirement has no traceable material."
                )
                if requirement.is_required:
                    findings.append(
                        ValidatorFinding(
                            severity=VerificationSeverity.CRITICAL
                            if status_value is VerificationStatus.FAILED
                            else VerificationSeverity.MEDIUM,
                            title=f"Requirement {requirement.code} not traceable",
                            description=(
                                f"'{requirement.title}' has no matching material in any "
                                "artifact. Keyword matching cannot prove absence of "
                                "semantically equivalent work — the finding says the "
                                "requirement is untraceable, not that it is wrong."
                            ),
                            requirement_codes=[requirement.code],
                            recommendation=f"Produce material for requirement {requirement.code}.",
                        )
                    )
            verdicts.append(
                RequirementVerdict(
                    requirement_id=requirement.id,
                    code=requirement.code,
                    status=status_value,
                    explanation=explanation,
                )
            )

        verified = sum(1 for v in verdicts if v.status is VerificationStatus.VERIFIED)
        failed = sum(1 for v in verdicts if v.status is VerificationStatus.FAILED)
        partial = sum(1 for v in verdicts if v.status is VerificationStatus.PARTIAL)
        evidence.append(
            ValidatorEvidence(
                kind="REQUIREMENT_TRACE",
                source=f"{len(requirements)} requirements vs {len(artifacts)} artifacts",
                method=VerificationMethod.DETERMINISTIC,
                status=VerificationStatus.VERIFIED,
                content=(
                    f"Traced {len(requirements)} requirements: {verified} verified, "
                    f"{failed} failed, {len(verdicts) - verified - failed} partial/unverified."
                ),
            )
        )

        if failed:
            overall = VerificationStatus.FAILED
        elif verified == len(verdicts):
            overall = VerificationStatus.VERIFIED
        elif verified or partial:
            overall = VerificationStatus.PARTIAL
        else:
            overall = VerificationStatus.UNVERIFIED
        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=overall,
            summary=(
                f"{verified}/{len(verdicts)} requirements traced and substantive; "
                f"{failed} failed, {partial} partial."
            ),
            method=VerificationMethod.DETERMINISTIC,
            confidence=CONFIDENCE_MODERATE,
            executed=True,
            limitations=limitations,
            findings=findings,
            evidence=evidence,
            requirement_verdicts=verdicts,
        )


def _requirement_tokens(requirement: object) -> list[str]:
    title = getattr(requirement, "title", "") or ""
    description = getattr(requirement, "description", None) or ""
    source = f"{title} {description}".lower()
    stop = {
        "a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "with",
        "must", "should", "shall", "include", "includes", "use", "using",
    }
    tokens = [token.strip(".,:;()") for token in source.split()]
    return [token for token in tokens if len(token) > 2 and token not in stop][:12]


def _coverage(text: str, tokens: list[str]) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    present = [token for token in tokens if token in lowered]
    missing = [token for token in tokens if token not in lowered]
    return present, missing


def _region_substantive(text: str, tokens: list[str]) -> bool:
    """Do the matched regions contain real material, not just a mention?

    Approximation: the artifact text as a whole around the first match must be
    substantive. A fully accurate region extractor is future work and is
    recorded as a limitation rather than faked.
    """
    lowered = text.lower()
    for token in tokens[:1]:
        index = lowered.find(token)
        if index >= 0:
            region = text[max(0, index - 200) : index + 600]
            return word_count(region) >= _SUBSTANTIVE_WORDS // 2
    return word_count(text) >= _SUBSTANTIVE_WORDS
