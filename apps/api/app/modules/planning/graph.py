"""Deterministic validation of a proposed plan's task graph.

The model is not the authority on graph correctness. A language model will
happily emit ``T1 -> T2 -> T1``, reference a requirement that does not exist, or
leave a required deliverable with no task producing it. This module is the
authority, and the service refuses to persist a plan that has not passed it.

Every check here is deterministic and explainable. That is deliberate: a student
who is told their plan is invalid deserves to know exactly which edge is
responsible, not a confidence number.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import SourceKind
from app.schemas.analysis import PlanningContractResponse
from app.schemas.planning import MAX_MILESTONES, PlannerOutput


class PlanGraphError(ValueError):
    """A plan cannot be persisted because its graph is not sound.

    ``violations`` is a list of short, human-readable strings rather than a
    single message, so a caller can report all the problems at once instead of
    making the student fix them one round trip at a time.
    """

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(self.violations) or "invalid plan graph")


@dataclass(slots=True)
class ValidatedGraph:
    """The result of validating a plan against a planning contract."""

    #: Task keys in a valid topological order, predecessors first.
    order: list[str]
    #: Requirement keys that no task addresses.
    orphan_requirements: list[str] = field(default_factory=list)
    #: Deliverable keys that no task contributes to.
    orphan_deliverables: list[str] = field(default_factory=list)
    #: Non-fatal observations worth surfacing to the student.
    warnings: list[str] = field(default_factory=list)


def detect_cycle(dependencies: Mapping[str, Iterable[str]]) -> list[str] | None:
    """Return one cycle as a key list, or ``None`` when the graph is acyclic.

    ``dependencies`` maps a task to the tasks it depends on. A cycle is the same
    set of nodes whichever direction the edges are read, so the traversal only has
    to follow them consistently.

    Iterative depth-first search with an explicit stack. Recursion is avoided
    because a plan is bounded by ``planning_max_task_count``, but a generated
    graph should never be able to exhaust the interpreter stack regardless.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = dict.fromkeys(dependencies, WHITE)
    path: list[str] = []

    for root in dependencies:
        if colour[root] != WHITE:
            continue
        # (node, iterator over its prerequisites) so the stack is resumable.
        stack: list[tuple[str, Iterable[str]]] = [(root, iter(dependencies.get(root, ())))]
        colour[root] = GREY
        path.append(root)
        while stack:
            node, successors = stack[-1]
            advanced = False
            for child in successors:
                if child not in colour:
                    # An edge to an unknown node is a dangling reference, not a
                    # cycle. It is reported separately by validate_graph.
                    continue
                if colour[child] == GREY:
                    start = path.index(child)
                    return [*path[start:], child]
                if colour[child] == WHITE:
                    colour[child] = GREY
                    path.append(child)
                    stack.append((child, iter(dependencies.get(child, ()))))
                    advanced = True
                    break
            if not advanced:
                colour[node] = BLACK
                path.pop()
                stack.pop()
    return None


def topological_order(dependencies: Mapping[str, Iterable[str]]) -> list[str]:
    """Order tasks so every task comes after the tasks it depends on.

    ``dependencies`` maps a task to the tasks it *depends on*, matching the
    ``depends_on`` convention used everywhere else in the domain. Kahn's algorithm
    over the reversed edges, with ties broken by key so the order is deterministic:
    a nondeterministic order would make two runs over the same input produce
    different plans, which defeats the idempotency the service relies on.
    """
    unmet: dict[str, int] = {key: 0 for key in dependencies}
    dependents: dict[str, list[str]] = {key: [] for key in dependencies}
    for node, prerequisites in dependencies.items():
        for prerequisite in prerequisites:
            if prerequisite in dependents:
                dependents[prerequisite].append(node)
                unmet[node] += 1

    ready = sorted(key for key, count in unmet.items() if count == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for dependent in sorted(dependents[node]):
            unmet[dependent] -= 1
            if unmet[dependent] == 0:
                # Keep `ready` sorted so ties resolve alphabetically.
                ready.append(dependent)
                ready.sort()
    return order


def validate_graph(
    plan: PlannerOutput,
    contract: PlanningContractResponse,
    *,
    max_task_count: int = 60,
) -> ValidatedGraph:
    """Check a proposed plan against its contract and against graph soundness.

    Raises ``PlanGraphError`` for anything that makes the plan unsound. Returns a
    ``ValidatedGraph`` for everything else, including the warnings worth showing.
    """
    violations: list[str] = []
    warnings: list[str] = []

    keys = [task.key for task in plan.tasks]
    key_set = set(keys)
    if len(key_set) != len(keys):
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        violations.append(f"duplicate task keys: {', '.join(duplicates)}")

    if len(plan.tasks) > max_task_count:
        violations.append(
            f"plan has {len(plan.tasks)} tasks, which is over the limit of {max_task_count}"
        )
    if len(plan.milestones) > MAX_MILESTONES:
        violations.append(
            f"plan has {len(plan.milestones)} milestones, which is over the "
            f"limit of {MAX_MILESTONES}"
        )

    # Edges. A dangling edge names a task that does not exist, which is a
    # different problem from a cycle and gets its own message.
    edges: dict[str, list[str]] = {key: [] for key in key_set}
    for task in plan.tasks:
        for dependency in task.depends_on:
            if dependency == task.key:
                violations.append(f"task {task.key} depends on itself")
            elif dependency not in key_set:
                violations.append(f"task {task.key} depends on unknown task {dependency}")
            elif dependency not in edges[task.key]:
                edges[task.key].append(dependency)

    cycle = detect_cycle(edges)
    if cycle is not None:
        violations.append(f"dependency cycle: {' -> '.join(cycle)}")

    # Traceability. The contract's keys are the vocabulary, so an unknown key
    # means the model invented a reference.
    requirement_keys = {item.key for item in contract.requirements}
    deliverable_keys = {item.key for item in contract.deliverables}
    covered_requirements: set[str] = set()
    covered_deliverables: set[str] = set()

    for task in plan.tasks:
        for reference in task.related_requirements:
            if reference not in requirement_keys:
                violations.append(f"task {task.key} references unknown requirement {reference}")
            else:
                covered_requirements.add(reference)
        for reference in task.related_deliverables:
            if reference not in deliverable_keys:
                violations.append(f"task {task.key} references unknown deliverable {reference}")
            else:
                covered_deliverables.add(reference)

    for milestone in plan.milestones:
        for reference in milestone.task_keys:
            if reference not in key_set:
                violations.append(f"milestone {milestone.key} references unknown task {reference}")
    for point in plan.verification_points:
        for reference in point.task_keys:
            if reference not in key_set:
                violations.append(
                    f"verification point {point.key} references unknown task {reference}"
                )
    for risk in plan.risks:
        for reference in risk.related_task_keys:
            if reference not in key_set:
                violations.append(f"risk {risk.key} references unknown task {reference}")

    # Orphan checks. A required requirement with no task means the plan does not
    # actually cover the brief, which is the single most important thing to catch.
    required_requirements = {
        item.key
        for item in contract.requirements
        if item.required and item.source_kind == SourceKind.EXPLICIT
    }
    orphan_requirements = sorted(required_requirements - covered_requirements)
    if orphan_requirements:
        violations.append(
            "no task addresses required requirement(s): " + ", ".join(orphan_requirements)
        )

    required_deliverables = {item.key for item in contract.deliverables if item.required}
    orphan_deliverables = sorted(required_deliverables - covered_deliverables)
    if orphan_deliverables:
        violations.append(
            "no task contributes to required deliverable(s): " + ", ".join(orphan_deliverables)
        )

    # Warnings: things that are legal but worth telling the student.
    if not plan.verification_points:
        warnings.append("the plan states no verification points")
    unlinked = sorted(key for key in key_set if not edges.get(key))
    if len(unlinked) == len(key_set) and len(key_set) > 1:
        warnings.append("the task graph has no dependencies; every task could start at once")
    order = topological_order(edges)

    # Enforcement. Everything collected above is fatal, and the plan is refused
    # rather than repaired: a silently repaired plan is a plan the student did not
    # review. Reporting every violation at once keeps the retry loop short.
    if violations:
        raise PlanGraphError(violations)

    return ValidatedGraph(
        order=order,
        orphan_requirements=orphan_requirements,
        orphan_deliverables=orphan_deliverables,
        warnings=warnings,
    )


def validate_edited_graph(
    tasks: Sequence[Mapping[str, Any]],
    edges: Sequence[tuple[str, str]],
) -> list[str]:
    """Validate a hand-edited graph before it is persisted.

    Same soundness rules as ``validate_graph``, but over already-persisted data
    where there is no contract to check against. Used by the task PATCH and
    DELETE endpoints, because a student editing dependencies by hand can create
    exactly the same cycle a model could.
    """
    violations: list[str] = []
    keys = [str(task["key"]) for task in tasks]
    key_set = set(keys)
    if len(key_set) != len(keys):
        violations.append("duplicate task keys in the plan")

    graph: dict[str, list[str]] = {key: [] for key in key_set}
    for predecessor, successor in edges:
        if predecessor not in key_set:
            violations.append(f"dependency references unknown task {predecessor}")
            continue
        if successor not in key_set:
            violations.append(f"dependency references unknown task {successor}")
            continue
        if predecessor == successor:
            violations.append(f"task {predecessor} cannot depend on itself")
            continue
        if successor not in graph[predecessor]:
            graph[predecessor].append(successor)

    cycle = detect_cycle(graph)
    if cycle is not None:
        violations.append(f"dependency cycle: {' -> '.join(cycle)}")
    return violations
