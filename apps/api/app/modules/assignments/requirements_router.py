"""Requirement and dependency endpoints.

Requirements are the only child resource with a graph, so this router also owns
the dependency rules: no self-links, no duplicates, no cycles, no references
outside the assignment.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Assignment, RequirementDependency, User
from app.models.enums import AuditEventType, RequirementStatus
from app.models.identifiers import requirement_code
from app.modules.assignments.requirements import (
    add_dependency,
    add_requirement,
    ensure_valid_parent,
    get_requirement,
    load_requirements,
)
from app.modules.assignments.service import (
    load_owned_assignment,
    record_specification_change,
)
from app.modules.assignments.specification import (
    build_dependency_graph,
    requirement_response,
)
from app.modules.assignments.specification import (
    dependency_response as _dependency_response,
)
from app.schemas.assignments import (
    DependencyCreate,
    DependencyResponse,
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
)
from app.schemas.specification import DependencyGraph

router = APIRouter(prefix="/api/v1/assignments", tags=["Requirements"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

COMPLETED_STATUSES = frozenset({RequirementStatus.COMPLETED, RequirementStatus.VERIFIED})


def code_index(assignment: Assignment) -> dict[UUID, str]:
    return {item.id: requirement_code(item.sequence) for item in assignment.requirements}


def _dependency(dependency: RequirementDependency, assignment: Assignment) -> DependencyResponse:
    return _dependency_response(
        dependency,
        code_index(assignment),
        {item.id: item.title for item in assignment.requirements},
    )


@router.get(
    "/{assignment_id}/requirements",
    response_model=list[RequirementResponse],
    summary="List assignment requirements",
)
async def list_requirements(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> list[RequirementResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [requirement_response(item) for item in assignment.requirements]


@router.post(
    "/{assignment_id}/requirements",
    response_model=RequirementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a requirement",
    description=(
        "Each requirement receives a stable reference such as REQ-001 from a per-assignment "
        "sequence that is never reused, so later tasks, files and tests can point at it."
    ),
)
async def create_requirement(
    assignment_id: UUID,
    payload: RequirementCreate,
    user: CurrentUser,
    db: Db,
) -> RequirementResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    parent_id = await ensure_valid_parent(assignment, None, payload.parent_id, db)
    requirement = await add_requirement(
        assignment,
        db,
        title=payload.title.strip(),
        description=payload.description,
        priority=payload.priority,
        type=payload.type,
        status=payload.status,
        is_required=payload.is_required,
        position=payload.position,
        parent_id=parent_id,
    )
    code = requirement_code(requirement.sequence)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.REQUIREMENT_CREATED,
        entity_type="AssignmentRequirement",
        entity_id=requirement.id,
        change_summary=f"Added requirement {code}",
        metadata={"code": code, "priority": requirement.priority, "type": requirement.type},
    )
    await db.commit()
    return requirement_response(requirement)


@router.patch(
    "/{assignment_id}/requirements/{requirement_id}",
    response_model=RequirementResponse,
    summary="Update a requirement",
    description=(
        "Accepts any requirement field, including `position` for reordering, `parent_id` for "
        "nesting and `status` for progress. Nesting under a descendant is rejected."
    ),
)
async def update_requirement(
    assignment_id: UUID,
    requirement_id: UUID,
    payload: RequirementUpdate,
    user: CurrentUser,
    db: Db,
) -> RequirementResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = await get_requirement(assignment, requirement_id, db)
    code = requirement_code(requirement.sequence)
    changes = payload.model_dump(exclude_unset=True)
    was_completed = requirement.status in {item.value for item in COMPLETED_STATUSES}

    if changes.get("title") is not None:
        requirement.title = str(changes["title"]).strip()
    if "description" in changes:
        requirement.description = changes["description"]
    for field in ("priority", "type", "status"):
        if changes.get(field) is not None:
            setattr(requirement, field, changes[field].value)
    if changes.get("is_required") is not None:
        requirement.is_required = bool(changes["is_required"])
    if changes.get("position") is not None:
        requirement.position = int(changes["position"])
    if "parent_id" in changes:
        requirement.parent_id = await ensure_valid_parent(
            assignment, requirement.id, changes["parent_id"], db
        )

    if not changes:
        return requirement_response(requirement)

    is_completed = requirement.status in {item.value for item in COMPLETED_STATUSES}
    event_type = (
        AuditEventType.REQUIREMENT_COMPLETED
        if is_completed and not was_completed
        else AuditEventType.REQUIREMENT_UPDATED
    )
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=event_type,
        entity_type="AssignmentRequirement",
        entity_id=requirement.id,
        change_summary=f"Updated requirement {code}",
        metadata={"code": code, "fields": sorted(changes)},
    )
    await db.commit()
    return requirement_response(requirement)


@router.delete(
    "/{assignment_id}/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a requirement",
    description=(
        "Dependency edges pointing at the requirement are removed with it. Child requirements are "
        "not deleted silently: the request is rejected so nothing is lost by accident."
    ),
)
async def delete_requirement(
    assignment_id: UUID,
    requirement_id: UUID,
    user: CurrentUser,
    db: Db,
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = await get_requirement(assignment, requirement_id, db)
    children = [item for item in assignment.requirements if item.parent_id == requirement.id]
    if children:
        raise AppError(
            409,
            "REQUIREMENT_HAS_CHILDREN",
            "This requirement has nested requirements. Move or delete them first.",
            {"children": [requirement_code(child.sequence) for child in children]},
        )
    code = requirement_code(requirement.sequence)
    dependents = [
        requirement_code(item.sequence)
        for item in assignment.requirements
        if any(dependency.depends_on_id == requirement.id for dependency in item.dependencies)
    ]
    # delete-orphan cascade: dropping it from the collection deletes the row.
    assignment.requirements.remove(requirement)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.REQUIREMENT_DELETED,
        entity_type="AssignmentRequirement",
        entity_id=requirement_id,
        change_summary=f"Deleted requirement {code}",
        metadata={"code": code, "was_dependency_for": dependents},
    )
    await db.commit()


@router.post(
    "/{assignment_id}/requirements/{requirement_id}/dependencies",
    response_model=DependencyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a requirement dependency",
    description=(
        "Declares that the requirement cannot start before another one exists. Rejects "
        "self-dependencies, duplicates, unknown requirements and any edge that would "
        "create a cycle."
    ),
)
async def create_dependency(
    assignment_id: UUID,
    requirement_id: UUID,
    payload: DependencyCreate,
    user: CurrentUser,
    db: Db,
) -> DependencyResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = await get_requirement(assignment, requirement_id, db)
    dependency = await add_dependency(
        assignment,
        requirement,
        depends_on_id=payload.depends_on_id,
        note=payload.note,
        db=db,
    )
    codes = code_index(assignment)
    depends_on_code = codes[dependency.depends_on_id]
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.REQUIREMENT_UPDATED,
        entity_type="AssignmentRequirement",
        entity_id=requirement.id,
        change_summary=f"{codes[requirement.id]} now depends on {depends_on_code}",
        metadata={"depends_on": depends_on_code},
    )
    await db.commit()
    return _dependency(dependency, assignment)


@router.get(
    "/{assignment_id}/requirements/{requirement_id}/dependencies",
    response_model=list[DependencyResponse],
    summary="List the prerequisites of one requirement",
)
async def list_dependencies(
    assignment_id: UUID, requirement_id: UUID, user: CurrentUser, db: Db
) -> list[DependencyResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = await get_requirement(assignment, requirement_id, db)
    return [_dependency(item, assignment) for item in requirement.dependencies]


@router.delete(
    "/{assignment_id}/requirements/{requirement_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a requirement dependency",
)
async def delete_dependency(
    assignment_id: UUID,
    requirement_id: UUID,
    dependency_id: UUID,
    user: CurrentUser,
    db: Db,
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = await get_requirement(assignment, requirement_id, db)
    dependency = await db.scalar(
        select(RequirementDependency).where(
            RequirementDependency.id == dependency_id,
            RequirementDependency.requirement_id == requirement.id,
        )
    )
    if dependency is None:
        raise AppError(404, "DEPENDENCY_NOT_FOUND", "Dependency not found.")
    codes = code_index(assignment)
    summary = f"{codes[requirement.id]} no longer depends on {codes[dependency.depends_on_id]}"
    removed_code = codes[dependency.depends_on_id]
    requirement.dependencies.remove(dependency)
    await db.flush()
    # Reload so the readiness report is computed without the removed edge.
    assignment.requirements = await load_requirements(assignment.id, db)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.REQUIREMENT_UPDATED,
        entity_type="AssignmentRequirement",
        entity_id=requirement.id,
        change_summary=summary,
        metadata={"removed_dependency": removed_code},
    )
    await db.commit()


@router.get(
    "/{assignment_id}/requirements/dependency-graph",
    response_model=DependencyGraph,
    summary="Get the requirement dependency graph",
    description=(
        "Returns nodes, edges, a depth per node and a safe execution order. The graph is always "
        "acyclic because cycle-creating dependencies are rejected on write."
    ),
)
async def dependency_graph(assignment_id: UUID, user: CurrentUser, db: Db) -> DependencyGraph:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirements = await load_requirements(assignment.id, db)
    return build_dependency_graph(requirements)
