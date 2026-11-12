"""Level 1 — structural validation.

Cheap, fully deterministic checks that gate everything else: do artifacts
exist, are they readable, are required deliverables represented, are titles
sane. A structural failure is at least ``HIGH`` severity, because verifying
correctness is meaningless when the deliverable itself is absent or unreadable.
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
    CONFIDENCE_HIGH,
    CONFIDENCE_MODERATE,
    ValidatorDeclaration,
    ValidatorEvidence,
    ValidatorFinding,
    ValidatorResult,
    VerificationContext,
    VerificationValidator,
)


class StructuralValidator(VerificationValidator):
    """L1: artifact presence, readability and required-deliverable coverage."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="structural",
        level=VerificationLevel.STRUCTURAL,
        description=(
            "Checks artifacts exist, are non-empty, titles are valid, and every "
            "required deliverable has a plausible artifact. Deterministic."
        ),
        timeout_seconds=5.0,
    )

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        assignment = ctx.assignment
        artifacts = ctx.scoped_artifacts()
        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []
        limitations: list[str] = []
        status = VerificationStatus.VERIFIED

        if not artifacts:
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.FAILED,
                summary="No artifacts: nothing has been produced yet.",
                confidence=CONFIDENCE_HIGH,
                executed=True,
                limitations=["No artifacts exist to verify."],
                findings=[
                    ValidatorFinding(
                        severity=VerificationSeverity.CRITICAL,
                        title="No artifacts produced",
                        description=(
                            "The assignment has no artifacts to verify. Correctness "
                            "cannot be assessed for work that does not exist."
                        ),
                        recommendation="Produce the required deliverables before verification.",
                    )
                ],
            )

        # 1. Empty artifacts.
        empties = [a for a in artifacts if not a.content.strip()]
        for artifact in empties:
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.HIGH,
                    title=f"Artifact '{artifact.title}' is empty",
                    description="The artifact exists but its content is empty.",
                    artifact_ids=[artifact.id],
                    recommendation="Fill in the artifact content or remove the placeholder.",
                )
            )
        if empties:
            status = VerificationStatus.PARTIAL

        # 2. Duplicate titles: a likely accidental copy, not two deliverables.
        seen: dict[str, list[str]] = {}
        for artifact in artifacts:
            seen.setdefault(artifact.title.strip().lower(), []).append(artifact.title)
        for title, originals in seen.items():
            if len(originals) > 1:
                findings.append(
                    ValidatorFinding(
                        severity=VerificationSeverity.MEDIUM,
                        title=f"Duplicate artifact title: '{originals[0]}'",
                        description=(
                            "Multiple artifacts share this title, which suggests an "
                            "accidental duplicate rather than two distinct deliverables."
                        ),
                        artifact_ids=[a.id for a in artifacts if a.title.strip().lower() == title],
                        recommendation="Rename or merge the duplicated artifacts.",
                    )
                )

        # 3. Required deliverables without a plausible artifact.
        # Plausibility is keyword overlap — a traceability signal, not proof.
        # When it fails the verdict is PARTIAL with the heuristic recorded,
        # never a FAILED claim that the deliverable is "definitely missing".
        for deliverable in assignment.deliverables:
            if not deliverable.is_required:
                continue
            tokens = [t for t in deliverable.title.lower().split() if t not in _STOPWORDS]
            matched = False
            for artifact in artifacts:
                haystack = f"{artifact.title}\n{artifact.content[:2000]}".lower()
                if any(token in haystack for token in tokens):
                    matched = True
                    break
            if not matched:
                findings.append(
                    ValidatorFinding(
                        severity=VerificationSeverity.HIGH,
                        title=f"Required deliverable not found: '{deliverable.title}'",
                        description=(
                            "No artifact matches this required deliverable by title or "
                            "content keywords. The match is keyword-based, so an artifact "
                            "with unrelated wording could still satisfy it — that is "
                            "recorded as a limitation rather than certainty."
                        ),
                        recommendation=(
                            f"Add an artifact for '{deliverable.title}' or confirm an "
                            "existing artifact covers it under another name."
                        ),
                    )
                )
                status = VerificationStatus.PARTIAL
                limitations.append(
                    f"Deliverable matching is keyword-based; '{deliverable.title}' "
                    "may be covered by differently worded artifacts."
                )

        evidence.append(
            ValidatorEvidence(
                kind="STRUCTURAL_SCAN",
                source=f"{len(artifacts)} artifacts, {len(assignment.deliverables)} deliverables",
                method=VerificationMethod.DETERMINISTIC,
                status=VerificationStatus.VERIFIED,
                content=(
                    f"Checked {len(artifacts)} artifacts: {len(empties)} empty; "
                    f"{len(assignment.deliverables)} required deliverables matched by keyword."
                ),
            )
        )

        confidence = (
            CONFIDENCE_HIGH if status is VerificationStatus.VERIFIED else CONFIDENCE_MODERATE
        )
        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=status,
            summary=f"{len(artifacts)} artifacts structurally checked: {len(findings)} findings.",
            method=VerificationMethod.DETERMINISTIC,
            confidence=confidence,
            executed=True,
            limitations=limitations or [
                "Title/keyword heuristic only; no semantic matching."
            ],
            findings=findings,
            evidence=evidence,
        )


_STOPWORDS = {"a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "with"}
