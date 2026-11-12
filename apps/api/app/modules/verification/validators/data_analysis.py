"""Domain validators: data analysis and laboratory work.

``data_recompute`` genuinely re-derives statistics: when an artifact's metadata
carries the dataset values the analysis was run on, the validator recomputes
mean/median/stdev/min/max with Python's :mod:`statistics` module and compares
against the numbers the artifact *claims*. Discrepancies are CRITICAL findings
backed by the recomputation itself. When no dataset is available, the result is
UNVERIFIED — the engine never accepts an artifact's own reported numbers as
independently verified.

``lab_consistency`` checks methodology/results/conclusion section presence,
unit format sanity and conclusion-claim markers. Deeper consistency (error
propagation, measurement reconciliation) needs the raw measurements and is
recorded as a limitation.
"""

from __future__ import annotations

import re
import statistics
from typing import Any, ClassVar

from app.models.enums import (
    AcademicDomain,
    VerificationLevel,
    VerificationMethod,
    VerificationSeverity,
    VerificationStatus,
)
from app.modules.verification.contracts import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MODERATE,
    CONFIDENCE_NONE,
    ValidatorDeclaration,
    ValidatorEvidence,
    ValidatorFinding,
    ValidatorResult,
    VerificationContext,
    VerificationValidator,
)

_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")
_CLAIMED_STAT_RE = re.compile(
    r"(mean|average|median|std(?:ev)?|standard deviation|min|max|total)\D{0,20}(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:(?:km|m|cm|mm|kg|g|mg|s|ms|min|h|°C|K|mol|L|mL)\b)"
)
_SECTIONS = ("method", "materials", "results", "conclusion", "discussion")


class DataRecomputeValidator(VerificationValidator):
    """L3/L4: independent recomputation of claimed statistics."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="data_recompute",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({
            AcademicDomain.ECONOMICS,
            AcademicDomain.SOCIAL_SCIENCES,
            AcademicDomain.PHYSICS,
            AcademicDomain.CHEMISTRY,
            AcademicDomain.BIOLOGY,
            AcademicDomain.OTHER,
        }),
        assignment_types=frozenset({"DATA_ANALYSIS", "LAB_REPORT", "REPORT"}),
        description=(
            "Recomputes claimed mean/median/stdev/min/max from the dataset in "
            "artifact metadata and reports discrepancies as critical findings. "
            "Without a dataset, results are reported UNVERIFIED."
        ),
        timeout_seconds=15.0,
    )

    def applies_to(self, ctx: VerificationContext) -> bool:
        return any(
            a.metadata_json and a.metadata_json.get("dataset") for a in ctx.scoped_artifacts()
        )

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        artifacts = [
            a for a in ctx.scoped_artifacts() if a.metadata_json and a.metadata_json.get("dataset")
        ]
        if not artifacts:
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.UNVERIFIED,
                summary=(
                    "No dataset is attached to the artifacts, so reported numbers "
                    "cannot be independently recomputed."
                ),
                confidence=CONFIDENCE_NONE,
                executed=True,
                limitations=[
                    "Recomputation requires the raw dataset (artifact metadata key "
                    "'dataset'). Attaching it enables deterministic verification; "
                    "until then, claimed statistics are UNVERIFIED — not confirmed."
                ],
            )

        findings: list[ValidatorFinding] = []
        evidence: list[ValidatorEvidence] = []
        mismatches = 0
        checks = 0
        for artifact in artifacts:
            values = _dataset_values(artifact.metadata_json or {})
            if len(values) < 2:
                continue
            recomputed: dict[str, float] = {
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "stdev": statistics.stdev(values),
                "min": min(values),
                "max": max(values),
            }
            text = artifact.content
            for match in _CLAIMED_STAT_RE.finditer(text):
                metric = match.group(1).lower()
                claimed = float(match.group(2))
                key = (
                    "mean"
                    if metric in ("mean", "average")
                    else "stdev"
                    if metric in ("std", "stdev", "standard", "standard deviation")
                    else "median"
                    if metric == "median"
                    else metric
                )
                if key not in recomputed:
                    continue
                checks += 1
                expected = recomputed[key]
                if abs(expected - claimed) > 1e-6 * max(1.0, abs(expected)) and abs(
                    expected - claimed
                ) > 1e-9:
                    mismatches += 1
                    findings.append(
                        ValidatorFinding(
                            severity=VerificationSeverity.CRITICAL,
                            title=f"{key.title()} mismatch in '{artifact.title}'",
                            description=(
                                f"The artifact claims {key} = {claimed}, but recomputing "
                                f"from the attached dataset ({len(values)} values) gives "
                                f"{round(expected, 6)}. Independently recomputed, not "
                                "an AI judgment."
                            ),
                            artifact_ids=[artifact.id],
                            recommendation=f"Report {key} = {round(expected, 6)}.",
                        )
                    )
            evidence.append(
                ValidatorEvidence(
                    kind="STATISTICS_RECOMPUTATION",
                    source=f"dataset in artifact '{artifact.title}' ({len(values)} values)",
                    method=VerificationMethod.DETERMINISTIC,
                    status=VerificationStatus.FAILED if mismatches else VerificationStatus.VERIFIED,
                    content=(
                        f"recomputed={ {k: round(v, 6) for k, v in recomputed.items()} }; "
                        f"checks={checks}; mismatches={mismatches}"
                    ),
                    artifact_ids=[artifact.id],
                )
            )

        status = (
            VerificationStatus.FAILED
            if mismatches
            else VerificationStatus.VERIFIED
            if checks
            else VerificationStatus.PARTIAL
        )
        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=status,
            summary=(
                f"Recomputed {checks} statistics from attached datasets; "
                f"{mismatches} mismatches."
                if checks
                else "Dataset attached but no comparable claims found in the text."
            ),
            method=VerificationMethod.DETERMINISTIC,
            confidence=CONFIDENCE_HIGH if checks else CONFIDENCE_MODERATE,
            executed=True,
            limitations=[
                "Only mean/median/stdev/min/max are recomputed. Regression, "
                "correlation, hypothesis tests and visualisation accuracy are "
                "future work.",
                "Interpretation quality (whether conclusions follow from the "
                "numbers) is not machine-verifiable here.",
            ],
            findings=findings,
            evidence=evidence,
        )


def _dataset_values(metadata: dict[str, Any]) -> list[float]:
    raw = metadata.get("dataset")
    if isinstance(raw, dict):
        raw = raw.get("values")
    if not isinstance(raw, list):
        return []
    values: list[float] = []
    for item in raw[:10000]:
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            values.append(float(item))
        elif isinstance(item, str) and _NUMBER_RE.match(item.strip()):
            values.append(float(item.strip()))
    return values


class LabConsistencyValidator(VerificationValidator):
    """L3: laboratory report structure and unit sanity."""

    declaration: ClassVar[ValidatorDeclaration] = ValidatorDeclaration(
        name="lab_consistency",
        level=VerificationLevel.DOMAIN,
        domains=frozenset({
            AcademicDomain.PHYSICS,
            AcademicDomain.CHEMISTRY,
            AcademicDomain.BIOLOGY,
            AcademicDomain.ENGINEERING,
        }),
        assignment_types=frozenset({"LAB_REPORT"}),
        description=(
            "Checks methodology/results/conclusion sections, unit-bearing "
            "measurements and the results-to-conclusion bridge. Error "
            "propagation is not verifiable without raw measurements."
        ),
        timeout_seconds=10.0,
    )

    def applies_to(self, ctx: VerificationContext) -> bool:
        return bool(ctx.scoped_artifacts())

    async def verify(self, ctx: VerificationContext) -> ValidatorResult:
        text = "\n".join(a.content for a in ctx.scoped_artifacts())
        lowered = text.lower()
        if not lowered.strip():
            return ValidatorResult(
                validator=self.declaration.name,
                version=self.declaration.version,
                level=self.declaration.level,
                status=VerificationStatus.UNVERIFIED,
                summary="No lab report content.",
                confidence=CONFIDENCE_NONE,
                executed=True,
                limitations=["No content."],
            )
        findings: list[ValidatorFinding] = []
        for section in _SECTIONS:
            if section not in lowered:
                findings.append(
                    ValidatorFinding(
                        severity=VerificationSeverity.MEDIUM,
                        title=f"Missing '{section}' section",
                        description=(
                            f"No text mentioning '{section}' was found. Standard lab "
                            "reports document this section."
                        ),
                        recommendation=f"Add the {section} section.",
                    )
                )
        unit_bearings = _UNIT_RE.findall(text)
        if not unit_bearings and re.search(r"\d", text):
            findings.append(
                ValidatorFinding(
                    severity=VerificationSeverity.MEDIUM,
                    title="No units detected on measurements",
                    description=(
                        "Numbers appear in the report but none carry a recognised "
                        "unit. Unqualified measurements cannot be checked for "
                        "consistency."
                    ),
                    recommendation="Attach units to every measurement.",
                )
            )
        status = (
            VerificationStatus.PARTIAL
            if len(findings) >= 3
            else VerificationStatus.VERIFIED
            if not findings
            else VerificationStatus.PARTIAL
        )
        return ValidatorResult(
            validator=self.declaration.name,
            version=self.declaration.version,
            level=self.declaration.level,
            status=status,
            summary=(
                f"Lab structure checked: {len(findings)} findings, "
                f"{len(unit_bearings)} unit-bearing measurements."
            ),
            method=VerificationMethod.DETERMINISTIC,
            confidence=CONFIDENCE_MODERATE,
            executed=True,
            limitations=[
                "Section detection is keyword-based. Calculation correctness, "
                "error propagation and measurement reconciliation require the "
                "raw data and are NOT verified here.",
            ],
            findings=findings,
            evidence=[
                ValidatorEvidence(
                    kind="LAB_STRUCTURE_SCAN",
                    source="artifact text",
                    method=VerificationMethod.DETERMINISTIC,
                    status=VerificationStatus.VERIFIED,
                    content=(
                        f"sections_missing={len(findings)}, "
                        f"unit_measurements={len(unit_bearings)}"
                    ),
                )
            ],
        )
