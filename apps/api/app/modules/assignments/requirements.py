"""Requirement service: identity, ordering, dependencies and cycles.

Requirements are the backbone of traceability, so two rules are enforced here
rather than in a router:

* ``sequence`` is assigned once per assignment and never reused, which is what
  makes ``REQ-003`` a stable reference for future tasks, files and tests.
* the dependency graph is always acyclic, checked with an iterative depth-first
  search so a large specification cannot blow the Python stack.
"""

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import Assignment, AssignmentRequirement, RequirementDependency
from app.models.enums import RequirementPriority, RequirementStatus, RequirementType
from app.models.identifiers import requirement_code

#: Guard for the "two writers picked the same sequence" race.
SEQUENCE_ATTEMPTS = 5


async def load_requirements(assignment_id: UUID, db: AsyncSession) -> list[AssignmentRequirement]:
    result = await db.execute(
        select(AssignmentRequirement)
        .where(AssignmentRequirement.assignment_id == assignment_id)
        .options(
            selectinload(AssignmentRequirement.dependencies),
            selectinload(AssignmentRequirement.dependents),
        )
        .order_by(AssignmentRequirement.position, AssignmentRequirement.sequence)
    )
    return list(result.scalars().unique().all())


async def get_requirement(
    assignment: Assignment, requirement_id: UUID, db: AsyncSession
) -> AssignmentRequirement:
    requirement = await db.scalar(
        select(AssignmentRequirement).where(
            AssignmentRequirement.id == requirement_id,
            AssignmentRequirement.assignment_id == assignment.id,
        )
    )
    if requirement is None:
        raise AppError(404, "REQUIREMENT_NOT_FOUND", "Requirement not found.")
    return requirement


async def next_sequence(assignment: Assignment, db: AsyncSession) -> int:
    """Hand out the next requirement number atomically.

    The counter lives on the assignment row and only ever moves forward, so
    deleting REQ-004 does not hand REQ-004 to the next requirement. The
    ``UPDATE ... RETURNING`` is the real guard against two concurrent inserts.
    """
    return (
        await db.scalar(
            update(Assignment)
            .where(Assignment.id == assignment.id)
            .values(requirement_sequence=Assignment.requirement_sequence + 1)
            .returning(Assignment.requirement_sequence)
        )
        or 0
    )


async def add_requirement(
    assignment: Assignment,
    db: AsyncSession,
    *,
    title: str,
    description: str | None,
    priority: RequirementPriority,
    type: RequirementType,
    status: RequirementStatus,
    is_required: bool,
    position: int | None = None,
    parent_id: UUID | None = None,
) -> AssignmentRequirement:
    """Insert a requirement, allocating a stable sequence number.

    The unique ``(assignment_id, sequence)`` constraint is the real guard; the
    retry loop turns a concurrent insert into the next free number instead of a
    409 for the user.
    """
    candidate = await next_sequence(assignment, db)
    for _ in range(SEQUENCE_ATTEMPTS):
        requirement = AssignmentRequirement(
            assignment_id=assignment.id,
            sequence=candidate,
            title=title,
            description=description,
            priority=priority.value,
            type=type.value,
            status=status.value,
            is_required=is_required,
            position=candidate if position is None else position,
            parent_id=parent_id,
        )
        try:
            async with db.begin_nested():
                db.add(requirement)
                await db.flush()
        except IntegrityError:
            candidate += 1
            continue
        assignment.requirements.append(requirement)
        return requirement
    raise AppError(
        409,
        "REQUIREMENT_SEQUENCE_CONFLICT",
        "Could not allocate a requirement number. Please try again.",
    )


async def ensure_valid_parent(
    assignment: Assignment,
    requirement_id: UUID | None,
    parent_id: UUID | None,
    db: AsyncSession,
) -> UUID | None:
    """Validate a proposed parent requirement and return its id.

    A parent must belong to the same assignment, must not be the requirement
    itself, and must not be one of its descendants - otherwise the hierarchy
    could loop.
    """
    if parent_id is None:
        return None
    if requirement_id is not None and parent_id == requirement_id:
        raise AppError(422, "INVALID_PARENT", "A requirement cannot be its own parent.")
    parent = await db.scalar(
        select(AssignmentRequirement).where(
            AssignmentRequirement.id == parent_id,
            AssignmentRequirement.assignment_id == assignment.id,
        )
    )
    if parent is None:
        raise AppError(404, "REQUIREMENT_NOT_FOUND", "Parent requirement not found.")
    if requirement_id is not None and await _has_ancestor(parent, requirement_id, db):
        raise AppError(
            422,
            "INVALID_PARENT",
            "A requirement cannot be nested under one of its own children.",
        )
    return parent.id


async def _has_ancestor(
    candidate: AssignmentRequirement, ancestor_id: UUID, db: AsyncSession
) -> bool:
    """Walk up from ``candidate`` looking for ``ancestor_id``."""
    seen: set[UUID] = set()
    current: AssignmentRequirement | None = candidate
    while current is not None and current.parent_id is not None:
        if current.parent_id == ancestor_id:
            return True
        if current.parent_id in seen:
            return True
        seen.add(current.parent_id)
        current = await db.scalar(
            select(AssignmentRequirement).where(AssignmentRequirement.id == current.parent_id)
        )
    return False


async def add_dependency(
    assignment: Assignment,
    requirement: AssignmentRequirement,
    *,
    depends_on_id: UUID,
    note: str | None,
    db: AsyncSession,
) -> RequirementDependency:
    """Link a requirement to a prerequisite, rejecting anything that cycles."""
    if depends_on_id == requirement.id:
        raise AppError(422, "SELF_DEPENDENCY", "A requirement cannot depend on itself.")
    depends_on = await db.scalar(
        select(AssignmentRequirement).where(
            AssignmentRequirement.id == depends_on_id,
            AssignmentRequirement.assignment_id == assignment.id,
        )
    )
    if depends_on is None:
        raise AppError(404, "REQUIREMENT_NOT_FOUND", "Dependency requirement not found.")

    existing = await db.scalar(
        select(RequirementDependency).where(
            RequirementDependency.requirement_id == requirement.id,
            RequirementDependency.depends_on_id == depends_on_id,
        )
    )
    if existing is not None:
        raise AppError(
            409,
            "DUPLICATE_DEPENDENCY",
            "That dependency already exists.",
            {
                "requirement": requirement_code(requirement.sequence),
                "depends_on": requirement_code(depends_on.sequence),
            },
        )

    requirements = await load_requirements(assignment.id, db)
    graph = dependency_graph(requirements)
    graph[requirement.id].add(depends_on.id)
    if cycle := detect_cycle(graph):
        codes = codes_by_id(requirements)
        cycle_codes = [codes.get(node, str(node)) for node in cycle]
        raise AppError(
            422,
            "DEPENDENCY_CYCLE",
            "That dependency would create a cycle: " + " -> ".join(cycle_codes),
            {"cycle": cycle_codes},
        )

    dependency = RequirementDependency(
        assignment_id=assignment.id,
        requirement_id=requirement.id,
        depends_on_id=depends_on.id,
        note=note,
    )
    db.add(dependency)
    await db.flush()
    requirement.dependencies.append(dependency)
    depends_on.dependents.append(dependency)
    return dependency


def dependency_graph(requirements: Sequence[AssignmentRequirement]) -> dict[UUID, set[UUID]]:
    """Return ``{requirement_id: {ids that must exist first}}``."""
    graph: dict[UUID, set[UUID]] = {requirement.id: set() for requirement in requirements}
    for requirement in requirements:
        for dependency in requirement.dependencies:
            graph[requirement.id].add(dependency.depends_on_id)
    return graph


def detect_cycle(graph: dict[UUID, set[UUID]]) -> list[UUID] | None:
    """Return one dependency cycle, or ``None`` when the graph is acyclic.

    Iterative colour-marking DFS: white = unvisited, grey = on the current path,
    black = fully explored. Iterative rather than recursive so a deep
    specification cannot exhaust the Python stack.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[UUID, int] = dict.fromkeys(graph, WHITE)

    def neighbours(node: UUID) -> list[UUID]:
        return sorted((item for item in graph.get(node, set()) if item in graph), key=str)

    for start in graph:
        if colour[start] != WHITE:
            continue
        colour[start] = GREY
        path: list[UUID] = [start]
        pending: list[Iterable[UUID]] = [iter(neighbours(start))]
        while path:
            descended = False
            for neighbour in pending[-1]:
                if colour[neighbour] == GREY:
                    cycle_start = path.index(neighbour)
                    return [*path[cycle_start:], neighbour]
                if colour[neighbour] == WHITE:
                    colour[neighbour] = GREY
                    path.append(neighbour)
                    pending.append(iter(neighbours(neighbour)))
                    descended = True
                    break
            if not descended:
                colour[path.pop()] = BLACK
                pending.pop()
    return None


def execution_order(
    graph: dict[UUID, set[UUID]], rank: dict[UUID, int] | None = None
) -> list[UUID]:
    """Kahn topological order, so a future planner has a safe starting order.

    ``rank`` breaks ties between requirements that are equally free to run, so
    the order follows the numbering the student sees instead of a random id.
    """
    order_key = (lambda node: (rank.get(node, 0), str(node))) if rank else (lambda node: str(node))
    indegree = {node: len(dependencies) for node, dependencies in graph.items()}
    dependents: dict[UUID, list[UUID]] = {node: [] for node in graph}
    for node, dependencies in graph.items():
        for dependency in dependencies:
            if dependency in dependents:
                dependents[dependency].append(node)

    ready = sorted((node for node, degree in indegree.items() if degree == 0), key=order_key)
    order: list[UUID] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for dependent in sorted(dependents[node], key=order_key):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort(key=order_key)
    return order


def max_depth(graph: dict[UUID, set[UUID]]) -> dict[UUID, int]:
    """Longest distance from a node with no dependencies, cycle-safe."""
    depths: dict[UUID, int] = {}

    def resolve(node: UUID, seen: frozenset[UUID]) -> int:
        if node in depths:
            return depths[node]
        if node in seen:
            return 0
        dependencies = [dep for dep in graph.get(node, set()) if dep in graph]
        if not dependencies:
            depths[node] = 0
            return 0
        depth = 1 + max(resolve(dep, seen | {node}) for dep in dependencies)
        depths[node] = depth
        return depth

    for node in graph:
        resolve(node, frozenset())
    return depths


def codes_by_id(requirements: Iterable[AssignmentRequirement]) -> dict[UUID, str]:
    return {requirement.id: requirement_code(requirement.sequence) for requirement in requirements}
