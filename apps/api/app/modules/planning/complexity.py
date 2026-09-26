"""Deterministic complexity scoring for planning.

Routing a plan to a model tier on a vibe is how you end up with an unexplainable
bill. This scores the planning contract on factors a human can check, returns the
factor list alongside the level, and lets the router explain itself.

The score is a weighted sum clamped to 0-100. The weights are deliberately
boring and ordered by how much each factor actually changes planning difficulty:
breadth (how many separate things) and dependency depth (how much sequencing
there is) dominate. Depth matters more than breadth in practice, because a wide
plan with a shallow graph is parallelisable and a narrow deep plan is a queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import ComplexityLevel, QuestionStatus, ScopeLevel
from app.schemas.analysis import PlanningContractResponse

#: Scope level -> points. UNKNOWN is treated as MEDIUM: an unclear scope is not
#: free, it just is not confidently large.
_SCOPE_POINTS = {
    ScopeLevel.NOT_APPLICABLE: 0,
    ScopeLevel.LOW: 4,
    ScopeLevel.MEDIUM: 9,
    ScopeLevel.HIGH: 15,
    ScopeLevel.UNKNOWN: 9,
}

#: Band boundaries on the 0-100 score.
_THRESHOLDS = (
    (25.0, ComplexityLevel.LOW),
    (50.0, ComplexityLevel.MEDIUM),
    (75.0, ComplexityLevel.HIGH),
)


@dataclass(slots=True)
class ComplexityScore:
    """A complexity verdict plus the arithmetic that produced it."""

    level: ComplexityLevel
    score: float
    factors: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        """How far the score sits from the nearest band boundary, as 0.0-1.0.

        Used to decide whether the router can act on a borderline score. A score
        sitting exactly on a boundary is not a basis for overriding a student's
        FAST preference.
        """
        if self.score < _THRESHOLDS[0][0]:
            edge = _THRESHOLDS[0][0]
        elif self.score < _THRESHOLDS[-1][0]:
            edge = min(
                abs(self.score - _THRESHOLDS[0][0]),
                abs(self.score - _THRESHOLDS[1][0]),
                abs(self.score - _THRESHOLDS[2][0]),
            )
        else:
            edge = _THRESHOLDS[-1][0]
        return round(min(1.0, edge / 12.5), 3)


def longest_dependency_chain(contract: PlanningContractResponse) -> int:
    """Length of the longest chain of contract dependencies, in nodes.

    Computed on the analyzer's own dependency edges rather than on the contract
    text, so it is exact. Iterative to stay clear of recursion limits.
    """
    successors: dict[str, list[str]] = {}
    nodes: set[str] = set()
    for edge in contract.dependencies:
        nodes.add(edge.predecessor)
        nodes.add(edge.successor)
        successors.setdefault(edge.predecessor, []).append(edge.successor)
    for node in nodes:
        successors.setdefault(node, [])

    depth: dict[str, int] = {}

    def depth_of(node: str, seen: frozenset[str]) -> int:
        if node in depth:
            return depth[node]
        if node in seen:  # the analyzer should not emit cycles; do not hang if it does
            return 1
        children = successors.get(node, [])
        if not children:
            depth[node] = 1
            return 1
        best = 1 + max(depth_of(child, seen | {node}) for child in children)
        depth[node] = best
        return best

    return max((depth_of(node, frozenset()) for node in nodes), default=0)


def score_complexity(contract: PlanningContractResponse) -> ComplexityScore:
    """Score how hard this assignment is to plan, and say why."""
    score = 0.0
    factors: list[str] = []

    requirement_count = len(contract.requirements)
    breadth = min(30.0, requirement_count * 2.2)
    score += breadth
    factors.append(f"{requirement_count} requirements (breadth +{breadth:.1f})")

    deliverable_count = len(contract.deliverables)
    assembly = min(20.0, deliverable_count * 3.3)
    score += assembly
    factors.append(f"{deliverable_count} deliverables (+{assembly:.1f})")

    depth = longest_dependency_chain(contract)
    # Depth is the strongest single signal, so it is worth up to 25 on its own.
    sequencing = min(25.0, max(0, depth - 1) * 4.2)
    score += sequencing
    if depth > 1:
        factors.append(f"dependency chain {depth} deep (+{sequencing:.1f})")

    scope = contract.scope
    scope_points = float(
        _SCOPE_POINTS.get(scope.overall, 9) + _SCOPE_POINTS.get(scope.technical_complexity.level, 0)
    )
    scope_points = min(20.0, scope_points)
    score += scope_points
    factors.append(
        f"overall scope {scope.overall.value}, "
        f"technical {scope.technical_complexity.level.value} (+{scope_points:.1f})"
    )

    open_questions = sum(
        1 for item in contract.clarification_questions if item.status == QuestionStatus.OPEN
    )
    uncertainty = min(15.0, open_questions * 2.5)
    score += uncertainty
    if open_questions:
        factors.append(f"{open_questions} unanswered clarifications (+{uncertainty:.1f})")

    verification = min(10.0, len(contract.verification_strategy.items) * 1.7)
    score += verification
    if verification:
        factors.append(
            f"{len(contract.verification_strategy.items)} verification items (+{verification:.1f})"
        )

    score = round(max(0.0, min(100.0, score)), 1)
    level = ComplexityLevel.VERY_HIGH
    for boundary, candidate in _THRESHOLDS:
        if score < boundary:
            level = candidate
            break
    return ComplexityScore(level=level, score=score, factors=factors)
