"""Rubric evaluation (Level 5) — weighted scoring with honest semantics.

Rules this module enforces structurally:

* Scores are **estimates**, labelled as such. Nothing here is an instructor
  grade; the report says "estimated quality" everywhere a score appears.
* Weighted averages are computed only when the rubric's weights are complete
  and unambiguous. A partial or non-numeric rubric produces per-criterion
  results *without* a weighted total, plus an explicit ambiguity note — the
  engine never invents grading rules to fill gaps.
* Every criterion score must point at evidence: requirement verdicts and
  validator results from the pipeline report. A criterion with no supporting
  evidence scores ``UNVERIFIED``, not zero — zero would be a fabricated fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.models.enums import VerificationStatus
from app.modules.verification.contracts import (
    CriterionSnapshot,
)
from app.modules.verification.pipeline import PipelineReport

#: Score scale. Normalised to [0, 1] per criterion; the presentation layer may
#: render any scale it wants, but the engine stores the normalised value plus
#: the scale label so a "0–4 rubric" is never confused with a percentage.
SCORE_SCALE = "NORMALISED_0_1"


@dataclass(slots=True)
class CriterionScore:
    criterion_id: str
    title: str
    weight: Decimal | None
    status: VerificationStatus
    score: float | None
    justification: str
    evidence_refs: list[str] = field(default_factory=list)
    improvement: str | None = None


@dataclass(slots=True)
class RubricResult:
    scale: str = SCORE_SCALE
    criteria: list[CriterionScore] = field(default_factory=list)
    #: Present only when every criterion has a weight and a score. Absent means
    #: "the rubric did not permit a total", never "total = 0".
    weighted_total: float | None = None
    ambiguities: list[str] = field(default_factory=list)
    estimated: bool = True

    @property
    def evaluated_count(self) -> int:
        return sum(1 for c in self.criteria if c.status is not VerificationStatus.UNVERIFIED)


def evaluate_rubric(
    criteria: list[CriterionSnapshot],
    report: PipelineReport,
    requirement_status: dict[str, VerificationStatus],
) -> RubricResult:
    """Score each criterion against pipeline evidence.

    ``requirement_status`` maps requirement code → verdict. Criteria that name
    requirements are scored from those verdicts; criteria without a link are
    scored from the aggregate domain evidence.
    """
    result = RubricResult()
    if not criteria:
        result.ambiguities.append(
            "No rubric criteria are recorded for this assignment, so no rubric "
            "score is produced. Adding criteria enables Level 5 evaluation."
        )
        return result

    weights_missing = [c.title for c in criteria if c.weight is None]
    if weights_missing:
        result.ambiguities.append(
            f"{len(weights_missing)} criterion/criteria lack a stated weight "
            f"({', '.join(weights_missing[:5])}); no weighted total can be "
            "computed without inventing grading rules."
        )
    zero_weights = [c.title for c in criteria if c.weight is not None and c.weight == 0]
    if zero_weights:
        result.ambiguities.append(
            f"{len(zero_weights)} criterion/criteria have zero weight "
            f"({', '.join(zero_weights[:5])}); the rubric should state a real weight."
        )

    domain_ok = report.overall_status is VerificationStatus.VERIFIED
    domain_partial = report.overall_status is VerificationStatus.PARTIAL
    domain_failed = report.overall_status is VerificationStatus.FAILED

    for criterion in criteria:
        linked_codes = _linked_requirements(criterion)
        linked = [code for code in linked_codes if code in requirement_status]
        if linked:
            verdict = _worst(requirement_status[code] for code in linked)
            score = _status_score(verdict)
            justification = (
                f"Scored from {len(linked)} linked requirement verdict(s) "
                f"({', '.join(linked)}), worst outcome '{verdict.value}'."
            )
            evidence_refs = [f"requirement:{code}" for code in linked]
        else:
            score = _status_score(
                VerificationStatus.VERIFIED
                if domain_ok
                else VerificationStatus.PARTIAL
                if domain_partial
                else VerificationStatus.FAILED
                if domain_failed
                else VerificationStatus.UNVERIFIED
            )
            justification = (
                "Scored from aggregate verification evidence (domain and "
                "structural results), no requirement link recorded for this "
                "criterion."
            )
            evidence_refs = [f"validator:{r.validator}" for r in report.results][:5]
        improvement = (
            "Address the failing/partial requirements linked to this criterion."
            if score is not None and score < 0.9
            else None
        )
        if score is None:
            result.criteria.append(
                CriterionScore(
                    criterion_id=str(criterion.id),
                    title=criterion.title,
                    weight=criterion.weight,
                    status=VerificationStatus.UNVERIFIED,
                    score=None,
                    justification=(
                        "No verification evidence connects to this criterion; "
                        "scored UNVERIFIED rather than 0 to avoid fabricating a fact."
                    ),
                    improvement="Produce verifiable evidence for this criterion.",
                )
            )
            continue
        status = _score_status(score)
        result.criteria.append(
            CriterionScore(
                criterion_id=str(criterion.id),
                title=criterion.title,
                weight=criterion.weight,
                status=status,
                score=score,
                justification=justification,
                evidence_refs=evidence_refs,
                improvement=improvement,
            )
        )

    scorable = [c for c in result.criteria if c.score is not None and c.weight is not None]
    if len(scorable) == len(criteria) and criteria:
        total_weight = sum(float(c.weight or 0) for c in scorable)
        if total_weight > 0:
            weighted = sum(
                float(c.score or 0.0) * float(c.weight or 0) for c in scorable
            )
            result.weighted_total = weighted / total_weight
        else:
            result.ambiguities.append("All weights are zero; no weighted total is meaningful.")
    return result


def _linked_requirements(criterion: CriterionSnapshot) -> list[str]:
    """Requirement codes mentioned in the criterion description, if any."""
    description = (criterion.description or "").lower()
    import re

    codes = re.findall(r"\breq[-_ ]?(\d{1,3})\b", description)
    return [f"REQ-{code.zfill(3)}" for code in codes]


def _worst(statuses: Any) -> VerificationStatus:
    order = [
        VerificationStatus.UNVERIFIED,
        VerificationStatus.NOT_APPLICABLE,
        VerificationStatus.VERIFIED,
        VerificationStatus.PARTIAL,
        VerificationStatus.FAILED,
    ]
    worst = VerificationStatus.UNVERIFIED
    for status in statuses:
        if order.index(status) > order.index(worst):
            worst = status
    return worst


def _status_score(status: VerificationStatus) -> float | None:
    """Normalised score per status. UNVERIFIED → None (no fabricated number)."""
    return {
        VerificationStatus.VERIFIED: 1.0,
        VerificationStatus.PARTIAL: 0.5,
        VerificationStatus.FAILED: 0.0,
    }.get(status)


def _score_status(score: float) -> VerificationStatus:
    if score >= 0.99:
        return VerificationStatus.VERIFIED
    if score > 0:
        return VerificationStatus.PARTIAL
    return VerificationStatus.FAILED
