"""Structural evaluation metrics for the analyzer.

Every metric is factual and structural. The point is to detect regressions in
classification, extraction, grounding and schema validity, not to reward a prose
style.

Two properties matter more than the numbers themselves:

* **A metric must be able to fail.** ``hallucination_rate`` used to be defined as
  ``1 - evidence_grounding``, which is zero for any output whose evidence ids
  resolve -- and the mock always produced resolvable ids, so the score was a
  tautology. Grounding is now counted per assertion, so an output that claims a
  fact is explicit without traceable evidence is counted as ungrounded.
* **A metric must be able to detect damage.** :func:`discrimination` deliberately
  corrupts a good analysis and asserts the checks reject it. A suite that scores
  1.0 while accepting every mutation is not measuring anything, so the report
  carries the mutation-detection rate alongside the quality rates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.evaluation.metrics_types import (
    AssertionTally,
    DiscriminationResult,
    FixtureResult,
    MutationResult,
)
from app.models.enums import EvidenceSourceType, SourceKind
from app.schemas.analysis import AnalyzerOutput, Evidence

__all__ = [
    "AssertionTally",
    "DiscriminationResult",
    "EvaluationReport",
    "FixtureResult",
    "MutationResult",
    "all_confidences_valid",
    "coverage_of",
    "discrimination",
    "tally_grounding",
]

#: Sources whose claims must be traceable to a real record. A claim may still be
#: an inference, but then it says so instead of pretending to be explicit.
_NEEDS_RESOLVABLE_ID = frozenset(
    {
        EvidenceSourceType.REQUIREMENT,
        EvidenceSourceType.CONSTRAINT,
        EvidenceSourceType.CRITERION,
        EvidenceSourceType.DELIVERABLE,
        EvidenceSourceType.RESOURCE,
    }
)

#: Kinds that assert something the student may act on.
_ASSERTION_KINDS = (
    "requirement",
    "deliverable",
    "ambiguity",
    "contradiction",
    "missing_information",
    "risk",
    "assumption",
)

_STOPWORDS = frozenset(
    """a an and are as at be by for from in is it its of on or that the their this to with
    must should each every all any using use used""".split()
)


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in _STOPWORDS
    }


def coverage_of(required: list[str], produced: list[str]) -> float:
    """Fraction of ``required`` items that ``produced`` substantively covers.

    Measured against the brief's own wording, so it can legitimately fall short:
    an analyzer that misses half the stated requirements scores 0.5, not 1.0.
    """
    if not required:
        return 1.0
    produced_tokens = set().union(*(_tokens(item) for item in produced)) if produced else set()
    if not produced_tokens:
        return 0.0
    hits = 0
    for item in required:
        wanted = _tokens(item)
        if not wanted:
            continue
        # Substantial overlap, not a single shared common word.
        if len(wanted & produced_tokens) / len(wanted) >= 0.6:
            hits += 1
    return round(hits / len(required), 4)


def _resolves(
    evidence: Evidence, allowed_by_source: dict[EvidenceSourceType, frozenset[str]]
) -> bool:
    needed = allowed_by_source.get(evidence.source_type)
    if needed is None:
        # TITLE/DESCRIPTION/COURSE/USER_NOTE/INFERENCE carry no id to resolve.
        return True
    if not evidence.source_id:
        return False
    return evidence.source_id in needed


def _claims_explicitly(source: str | None) -> bool:
    return source == SourceKind.EXPLICIT.value


def tally_grounding(
    output: AnalyzerOutput, allowed_by_source: dict[EvidenceSourceType, frozenset[str]]
) -> AssertionTally:
    """Count assertions and how many are traceable to a real source.

    An assertion is ungrounded when it carries evidence that does not resolve, or
    when it presents itself as explicit while citing nothing. An inference that
    admits it is an inference is honest, not a hallucination, so it is not counted.
    """
    total = 0
    grounded = 0
    offenders: list[str] = []

    def check(label: str, evidence: list[Evidence], source: str | None) -> None:
        nonlocal total, grounded
        total += 1
        if evidence:
            resolved = all(_resolves(item, allowed_by_source) for item in evidence)
            if resolved:
                grounded += 1
            else:
                offenders.append(f"{label}: dangling evidence reference")
            return
        if _claims_explicitly(source):
            offenders.append(f"{label}: claimed explicit with no evidence")
            return
        grounded += 1

    for requirement in output.normalized_requirements:
        check(f"requirement {requirement.key}", requirement.evidence, requirement.source)
    for deliverable_item in output.deliverables:
        check(
            f"deliverable {deliverable_item.key}",
            deliverable_item.evidence,
            deliverable_item.uncertainty,
        )
    for ambiguity in output.ambiguities:
        check(f"ambiguity {ambiguity.key}", ambiguity.evidence, None)
    for contradiction in output.contradictions:
        check(f"contradiction {contradiction.key}", contradiction.evidence, None)
    for missing in output.missing_information:
        check(f"missing {missing.key}", missing.evidence, None)
    for risk in output.risks:
        check(f"risk {risk.key}", risk.evidence, None)
    for assumption in output.assumptions:
        check(f"assumption {assumption.key}", assumption.evidence, None)

    return AssertionTally(
        total=total,
        grounded=grounded,
        ungrounded=total - grounded,
        offenders=offenders,
    )


def all_confidences_valid(output: AnalyzerOutput) -> bool:
    values: list[float] = [output.confidence]
    values.extend(item.confidence for item in output.assignment_types)
    values.extend(item.confidence for item in output.academic_domains)
    values.extend(item.confidence for item in output.normalized_requirements)
    values.extend(item.confidence for item in output.deliverables)
    values.extend(item.confidence for item in output.risks)
    values.extend(item.confidence for item in output.work_areas)
    return all(0.0 <= value <= 1.0 for value in values)


def discrimination(
    output: AnalyzerOutput, allowed_by_source: dict[EvidenceSourceType, frozenset[str]]
) -> list[MutationResult]:
    """Corrupt a good analysis and confirm the checks notice.

    Each mutation is a defect a real system could ship: a requirement that claims
    to be explicit with nothing behind it, and evidence pointing at a requirement
    that does not exist. If a mutation survives, the corresponding check is blind.
    """
    import copy

    results: list[MutationResult] = []

    stripped = copy.deepcopy(output)
    stripped.normalized_requirements[0].evidence = []
    stripped.normalized_requirements[0].source = SourceKind.EXPLICIT
    results.append(
        MutationResult(
            name="explicit_claim_without_evidence",
            caught=tally_grounding(stripped, allowed_by_source).ungrounded > 0,
        )
    )

    dangling = copy.deepcopy(output)
    target = dangling.normalized_requirements[0]
    if target.evidence:
        target.evidence[0].source_id = "00000000-0000-0000-0000-00000000dead"
        results.append(
            MutationResult(
                name="evidence_points_at_a_missing_requirement",
                caught=tally_grounding(dangling, allowed_by_source).ungrounded > 0,
            )
        )

    mislabelled = copy.deepcopy(output)
    mislabelled.normalized_requirements[0].evidence = []
    mislabelled.normalized_requirements[0].source = SourceKind.AI_INFERENCE
    results.append(
        MutationResult(
            name="honest_inference_is_not_a_hallucination",
            # The inverse control: this mutation must NOT be counted, otherwise the
            # metric would flag honest uncertainty instead of invented facts.
            caught=tally_grounding(mislabelled, allowed_by_source).ungrounded == 0,
        )
    )
    return results


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    results: list[FixtureResult]
    mutations: list[MutationResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def classification_accuracy(self) -> float:
        return self._rate("classification_hit")

    @property
    def requirement_coverage(self) -> float:
        """Mean share of the brief's own requirements the analyzer surfaced."""
        return self._mean("requirement_coverage")

    @property
    def deliverable_recall(self) -> float:
        return self._rate("deliverable_hit")

    @property
    def ambiguity_detection(self) -> float:
        return self._rate("ambiguity_hit")

    @property
    def contradiction_detection(self) -> float:
        return self._rate("contradiction_hit")

    @property
    def dependency_recall(self) -> float:
        return self._rate("dependency_hit")

    @property
    def rubric_recall(self) -> float:
        return self._rate("rubric_hit")

    @property
    def evidence_grounding(self) -> float:
        return self._ratio("grounded", "assertions")

    @property
    def schema_validity(self) -> float:
        return self._rate("schema_valid")

    @property
    def hallucination_rate(self) -> float:
        """Share of assertions that are not traceable to a real source."""
        return self._ratio("ungrounded", "assertions")

    @property
    def assertions(self) -> int:
        return sum(result.assertions for result in self.results)

    @property
    def mutation_detection_rate(self) -> float:
        if not self.mutations:
            return 0.0
        return round(sum(1 for item in self.mutations if item.caught) / len(self.mutations), 4)

    def _rate(self, attribute: str) -> float:
        if not self.results:
            return 0.0
        hits = sum(1 for r in self.results if getattr(r, attribute))
        return round(hits / len(self.results), 4)

    def _mean(self, attribute: str) -> float:
        values = [
            float(value) for r in self.results if (value := getattr(r, attribute)) is not None
        ]
        if not values:
            return 0.0
        return round(sum(values) / len(values), 4)

    def _ratio(self, field: str, total: str) -> float:
        denominator = sum(int(getattr(r, total)) for r in self.results)
        if not denominator:
            return 0.0
        return round(sum(int(getattr(r, field)) for r in self.results) / denominator, 4)

    def summary(self) -> dict[str, float | int]:
        return {
            "fixtures": self.total,
            "passed": self.passed,
            "classification_accuracy": self.classification_accuracy,
            "requirement_coverage": self.requirement_coverage,
            "deliverable_recall": self.deliverable_recall,
            "ambiguity_detection": self.ambiguity_detection,
            "contradiction_detection": self.contradiction_detection,
            "dependency_recall": self.dependency_recall,
            "rubric_recall": self.rubric_recall,
            "schema_validity": self.schema_validity,
            "assertions": self.assertions,
            "evidence_grounding": self.evidence_grounding,
            "hallucination_rate": self.hallucination_rate,
            "mutations": len(self.mutations),
            "mutation_detection_rate": self.mutation_detection_rate,
        }
