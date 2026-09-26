"""Structural evaluation metrics for the analyzer.

No stylistic comparison: every metric is factual and structural. The point is to
detect regressions in classification, extraction, grounding and schema validity,
not to reward a particular prose style.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.analysis import AnalyzerOutput


@dataclass(frozen=True, slots=True)
class FixtureResult:
    name: str
    schema_valid: bool
    classification_hit: bool
    requirement_hit: bool
    deliverable_hit: bool
    ambiguity_hit: bool
    contradiction_hit: bool
    dependency_hit: bool
    rubric_hit: bool
    evidence_grounded: bool
    confidence_valid: bool
    details: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(
            [
                self.schema_valid,
                self.classification_hit,
                self.requirement_hit,
                self.deliverable_hit,
                self.ambiguity_hit,
                self.contradiction_hit,
                self.dependency_hit,
                self.rubric_hit,
                self.evidence_grounded,
                self.confidence_valid,
            ]
        )


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    results: list[FixtureResult]

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
    def requirement_recall(self) -> float:
        return self._rate("requirement_hit")

    @property
    def deliverable_recall(self) -> float:
        return self._rate("deliverable_hit")

    @property
    def ambiguity_rate(self) -> float:
        return self._rate("ambiguity_hit")

    @property
    def contradiction_rate(self) -> float:
        return self._rate("contradiction_hit")

    @property
    def dependency_recall(self) -> float:
        return self._rate("dependency_hit")

    @property
    def rubric_recall(self) -> float:
        return self._rate("rubric_hit")

    @property
    def evidence_grounding(self) -> float:
        return self._rate("evidence_grounded")

    @property
    def schema_validity(self) -> float:
        return self._rate("schema_valid")

    @property
    def hallucination_rate(self) -> float:
        return 1.0 - self.evidence_grounding

    def _rate(self, attribute: str) -> float:
        if not self.results:
            return 0.0
        hits = sum(1 for result in self.results if getattr(result, attribute))
        return round(hits / len(self.results), 4)

    def summary(self) -> dict[str, float | int]:
        return {
            "fixtures": self.total,
            "passed": self.passed,
            "classification_accuracy": self.classification_accuracy,
            "requirement_recall": self.requirement_recall,
            "deliverable_recall": self.deliverable_recall,
            "ambiguity_rate": self.ambiguity_rate,
            "contradiction_rate": self.contradiction_rate,
            "dependency_recall": self.dependency_recall,
            "rubric_recall": self.rubric_recall,
            "evidence_grounding": self.evidence_grounding,
            "schema_validity": self.schema_validity,
            "hallucination_rate": self.hallucination_rate,
        }


def all_confidences_valid(output: AnalyzerOutput) -> bool:
    values: list[float] = [output.confidence]
    values.extend(item.confidence for item in output.assignment_types)
    values.extend(item.confidence for item in output.academic_domains)
    values.extend(item.confidence for item in output.normalized_requirements)
    values.extend(item.confidence for item in output.deliverables)
    values.extend(item.confidence for item in output.risks)
    values.extend(item.confidence for item in output.work_areas)
    return all(0.0 <= value <= 1.0 for value in values)
