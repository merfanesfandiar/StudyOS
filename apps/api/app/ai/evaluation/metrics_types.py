"""Value objects shared by the evaluation metrics and the runner.

Kept apart from :mod:`app.ai.evaluation.metrics` so a report can be constructed from
stored numbers without importing the scoring logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AssertionTally:
    """How many actionable claims an analysis made and how many were traceable."""

    total: int
    grounded: int
    ungrounded: int
    offenders: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MutationResult:
    """Whether a deliberately corrupted analysis was rejected by the checks."""

    name: str
    caught: bool


@dataclass(frozen=True, slots=True)
class DiscriminationResult:
    results: list[MutationResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def caught(self) -> int:
        return sum(1 for item in self.results if item.caught)

    @property
    def rate(self) -> float:
        if not self.results:
            return 0.0
        return round(self.caught / len(self.results), 4)

    @property
    def blind_spots(self) -> list[str]:
        return [item.name for item in self.results if not item.caught]


@dataclass(frozen=True, slots=True)
class FixtureResult:
    """Per-fixture outcome. ``requirement_coverage`` is a rate, not a boolean."""

    name: str
    schema_valid: bool
    classification_hit: bool
    requirement_coverage: float | None
    deliverable_hit: bool
    ambiguity_hit: bool
    contradiction_hit: bool
    dependency_hit: bool
    rubric_hit: bool
    confidence_valid: bool
    assertions: int = 0
    grounded: int = 0
    ungrounded: int = 0
    details: list[str] = field(default_factory=list)
    offenders: list[str] = field(default_factory=list)

    @property
    def evidence_grounded(self) -> bool:
        """No assertion is untraceable. Quality is measured by rate, not by this."""
        return self.ungrounded == 0

    @property
    def passed(self) -> bool:
        return all(
            [
                self.schema_valid,
                self.classification_hit,
                self.requirement_coverage is not None and self.requirement_coverage >= 0.99,
                self.deliverable_hit,
                self.ambiguity_hit,
                self.contradiction_hit,
                self.dependency_hit,
                self.rubric_hit,
                self.confidence_valid,
                self.evidence_grounded,
            ]
        )
