"""Constraints, evaluation criteria and deliverables.

These three resources share the same shape: an owned list, a create that
appends in position order, a partial update and a delete. Criteria are the only
one with a cross-field rule, because their weights must add up to exactly 100.
"""

from collections.abc import Sequence
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    Assignment,
    AssignmentConstraint,
    Deliverable,
    EvaluationCriterion,
    User,
)
from app.models.enums import AuditEventType
from app.modules.assignments.service import (
    load_owned_assignment,
    record_specification_change,
)
from app.modules.assignments.specification import (
    constraint_response,
    criterion_response,
    deliverable_response,
)
from app.modules.assignments.validation import (
    criteria_total,
    ensure_criteria_total,
    ensure_no_duplicate_titles,
    ensure_weight,
)
from app.schemas.assignments import (
    ConstraintCreate,
    ConstraintResponse,
    ConstraintUpdate,
    CriterionCreate,
    CriterionResponse,
    CriterionUpdate,
    DeliverableCreate,
    DeliverableResponse,
    DeliverableUpdate,
)

router = APIRouter(prefix="/api/v1/assignments", tags=["Specification"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

async def _load_child[Child: (AssignmentConstraint, EvaluationCriterion, Deliverable)](
    assignment: Assignment,
    child_id: UUID,
    model: type[Child],
    db: AsyncSession,
    *,
    code: str,
    label: str,
) -> Child:
    child = await db.scalar(
        select(model).where(model.id == child_id, model.assignment_id == assignment.id)
    )
    if child is None:
        raise AppError(404, code, f"{label} not found.")
    return child


def _position(existing: Sequence[Any], requested: int | None) -> int:
    """Append to the end unless the client sent an explicit position."""
    if requested is not None:
        return requested
    return max((item.position for item in existing), default=-1) + 1


# --- constraints -----------------------------------------------------------


@router.get(
    "/{assignment_id}/constraints",
    response_model=list[ConstraintResponse],
    summary="List constraints",
)
async def list_constraints(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> list[ConstraintResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [constraint_response(item) for item in assignment.constraints]


@router.post(
    "/{assignment_id}/constraints",
    response_model=ConstraintResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a constraint",
    description=(
        "A rule the solution must respect, for example a time limit or a forbidden library. "
        "Constraints never block readiness on their own; a missing constraint is only a warning."
    ),
)
async def create_constraint(
    assignment_id: UUID, payload: ConstraintCreate, user: CurrentUser, db: Db
) -> ConstraintResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    ensure_no_duplicate_titles(
        [item.title for item in assignment.constraints] + [payload.title], entity="Constraint"
    )
    constraint = AssignmentConstraint(
        assignment_id=assignment.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        value=payload.value,
        type=payload.type.value,
        severity=payload.severity.value,
        position=_position(assignment.constraints, payload.position),
    )
    db.add(constraint)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.CONSTRAINT_CREATED,
        entity_type="AssignmentConstraint",
        entity_id=constraint.id,
        change_summary=f"Added constraint {constraint.title}",
        metadata={"type": constraint.type, "severity": constraint.severity},
    )
    await db.commit()
    return constraint_response(constraint)


@router.patch(
    "/{assignment_id}/constraints/{constraint_id}",
    response_model=ConstraintResponse,
    summary="Update a constraint",
)
async def update_constraint(
    assignment_id: UUID,
    constraint_id: UUID,
    payload: ConstraintUpdate,
    user: CurrentUser,
    db: Db,
) -> ConstraintResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    constraint = await _load_child(
        assignment,
        constraint_id,
        AssignmentConstraint,
        db,
        code="CONSTRAINT_NOT_FOUND",
        label="Constraint",
    )
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("title") is not None:
        others = [
            item.title
            for item in assignment.constraints
            if item.id != constraint.id
            and item.title.casefold() == str(changes["title"]).strip().casefold()
        ]
        if others:
            raise AppError(
                409, "DUPLICATE_CONSTRAINT_TITLE", "A constraint with that title already exists."
            )
        constraint.title = str(changes["title"]).strip()
    if changes.get("description") is not None:
        constraint.description = str(changes["description"]).strip()
    if "value" in changes:
        constraint.value = changes["value"]
    for field in ("type", "severity"):
        if changes.get(field) is not None:
            setattr(constraint, field, changes[field].value)
    if changes.get("position") is not None:
        constraint.position = int(changes["position"])
    if not changes:
        return constraint_response(constraint)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.CONSTRAINT_UPDATED,
        entity_type="AssignmentConstraint",
        entity_id=constraint.id,
        change_summary=f"Updated constraint {constraint.title}",
        metadata={"fields": sorted(changes)},
    )
    await db.commit()
    return constraint_response(constraint)


@router.delete(
    "/{assignment_id}/constraints/{constraint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a constraint",
)
async def delete_constraint(
    assignment_id: UUID, constraint_id: UUID, user: CurrentUser, db: Db
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    constraint = await _load_child(
        assignment,
        constraint_id,
        AssignmentConstraint,
        db,
        code="CONSTRAINT_NOT_FOUND",
        label="Constraint",
    )
    title = constraint.title
    assignment.constraints.remove(constraint)
    await db.delete(constraint)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.CONSTRAINT_DELETED,
        entity_type="AssignmentConstraint",
        entity_id=constraint_id,
        change_summary=f"Deleted constraint {title}",
    )
    await db.commit()


# --- evaluation criteria ---------------------------------------------------


@router.get(
    "/{assignment_id}/criteria",
    response_model=list[CriterionResponse],
    summary="List evaluation criteria",
)
async def list_criteria(assignment_id: UUID, user: CurrentUser, db: Db) -> list[CriterionResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [criterion_response(item) for item in assignment.criteria]


@router.post(
    "/{assignment_id}/criteria",
    response_model=CriterionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an evaluation criterion",
    description=(
        "Weights are percentages with at most two decimals and must add up to exactly 100. A "
        "partial total is accepted while building the specification, but the assignment cannot "
        "be marked ready until the total is 100."
    ),
)
async def create_criterion(
    assignment_id: UUID, payload: CriterionCreate, user: CurrentUser, db: Db
) -> CriterionResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    ensure_no_duplicate_titles(
        [item.title for item in assignment.criteria] + [payload.title], entity="Criterion"
    )
    criterion = EvaluationCriterion(
        assignment_id=assignment.id,
        title=payload.title.strip(),
        description=payload.description,
        weight=ensure_weight(payload.weight),
        position=_position(assignment.criteria, payload.position),
    )
    db.add(criterion)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.CRITERION_CREATED,
        entity_type="EvaluationCriterion",
        entity_id=criterion.id,
        change_summary=f"Added criterion {criterion.title} ({criterion.weight}%)",
        metadata={"weight": str(criterion.weight)},
    )
    await db.commit()
    return criterion_response(criterion)


@router.patch(
    "/{assignment_id}/criteria/{criterion_id}",
    response_model=CriterionResponse,
    summary="Update an evaluation criterion",
    description=(
        "The new weight is validated against the rest of the assignment. When the assignment is "
        "already ready or analysed, a weight change that breaks the total of 100 sends the "
        "assignment back to INCOMPLETE."
    ),
)
async def update_criterion(
    assignment_id: UUID,
    criterion_id: UUID,
    payload: CriterionUpdate,
    user: CurrentUser,
    db: Db,
) -> CriterionResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    criterion = await _load_child(
        assignment,
        criterion_id,
        EvaluationCriterion,
        db,
        code="CRITERION_NOT_FOUND",
        label="Criterion",
    )
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("title") is not None:
        title = str(changes["title"]).strip()
        if any(
            item.id != criterion.id and item.title.casefold() == title.casefold()
            for item in assignment.criteria
        ):
            raise AppError(
                409, "DUPLICATE_CRITERION_TITLE", "A criterion with that title already exists."
            )
        criterion.title = title
    if "description" in changes:
        criterion.description = changes["description"]
    if changes.get("weight") is not None:
        criterion.weight = ensure_weight(changes["weight"])
    if changes.get("position") is not None:
        criterion.position = int(changes["position"])
    if not changes:
        return criterion_response(criterion)
    ensure_criteria_total(assignment.criteria, required=False)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.CRITERION_UPDATED,
        entity_type="EvaluationCriterion",
        entity_id=criterion.id,
        change_summary=f"Updated criterion {criterion.title}",
        metadata={
            "fields": sorted(changes),
            "weight": str(criterion.weight),
            "total": str(criteria_total(assignment.criteria)),
        },
    )
    await db.commit()
    return criterion_response(criterion)


@router.delete(
    "/{assignment_id}/criteria/{criterion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an evaluation criterion",
)
async def delete_criterion(
    assignment_id: UUID, criterion_id: UUID, user: CurrentUser, db: Db
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    criterion = await _load_child(
        assignment,
        criterion_id,
        EvaluationCriterion,
        db,
        code="CRITERION_NOT_FOUND",
        label="Criterion",
    )
    title = criterion.title
    assignment.criteria.remove(criterion)
    await db.delete(criterion)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.CRITERION_DELETED,
        entity_type="EvaluationCriterion",
        entity_id=criterion_id,
        change_summary=f"Deleted criterion {title}",
    )
    await db.commit()


# --- deliverables ----------------------------------------------------------


@router.get(
    "/{assignment_id}/deliverables",
    response_model=list[DeliverableResponse],
    summary="List deliverables",
)
async def list_deliverables(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> list[DeliverableResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [deliverable_response(item) for item in assignment.deliverables]


@router.post(
    "/{assignment_id}/deliverables",
    response_model=DeliverableResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a deliverable",
    description="Something the student must hand in: report, source archive, slides, demo, ...",
)
async def create_deliverable(
    assignment_id: UUID, payload: DeliverableCreate, user: CurrentUser, db: Db
) -> DeliverableResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    ensure_no_duplicate_titles(
        [item.title for item in assignment.deliverables] + [payload.title], entity="Deliverable"
    )
    deliverable = Deliverable(
        assignment_id=assignment.id,
        title=payload.title.strip(),
        description=payload.description,
        type=payload.type.value,
        status=payload.status.value,
        is_required=payload.is_required,
        position=_position(assignment.deliverables, payload.position),
    )
    db.add(deliverable)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.DELIVERABLE_CREATED,
        entity_type="Deliverable",
        entity_id=deliverable.id,
        change_summary=f"Added deliverable {deliverable.title}",
        metadata={"type": deliverable.type, "required": deliverable.is_required},
    )
    await db.commit()
    return deliverable_response(deliverable)


@router.patch(
    "/{assignment_id}/deliverables/{deliverable_id}",
    response_model=DeliverableResponse,
    summary="Update a deliverable",
)
async def update_deliverable(
    assignment_id: UUID,
    deliverable_id: UUID,
    payload: DeliverableUpdate,
    user: CurrentUser,
    db: Db,
) -> DeliverableResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    deliverable = await _load_child(
        assignment,
        deliverable_id,
        Deliverable,
        db,
        code="DELIVERABLE_NOT_FOUND",
        label="Deliverable",
    )
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("title") is not None:
        title = str(changes["title"]).strip()
        if any(
            item.id != deliverable.id and item.title.casefold() == title.casefold()
            for item in assignment.deliverables
        ):
            raise AppError(
                409, "DUPLICATE_DELIVERABLE_TITLE", "A deliverable with that title already exists."
            )
        deliverable.title = title
    if "description" in changes:
        deliverable.description = changes["description"]
    for field in ("type", "status"):
        if changes.get(field) is not None:
            setattr(deliverable, field, changes[field].value)
    if changes.get("is_required") is not None:
        deliverable.is_required = bool(changes["is_required"])
    if changes.get("position") is not None:
        deliverable.position = int(changes["position"])
    if not changes:
        return deliverable_response(deliverable)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.DELIVERABLE_UPDATED,
        entity_type="Deliverable",
        entity_id=deliverable.id,
        change_summary=f"Updated deliverable {deliverable.title}",
        metadata={"fields": sorted(changes)},
    )
    await db.commit()
    return deliverable_response(deliverable)


@router.delete(
    "/{assignment_id}/deliverables/{deliverable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a deliverable",
)
async def delete_deliverable(
    assignment_id: UUID, deliverable_id: UUID, user: CurrentUser, db: Db
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    deliverable = await _load_child(
        assignment,
        deliverable_id,
        Deliverable,
        db,
        code="DELIVERABLE_NOT_FOUND",
        label="Deliverable",
    )
    title = deliverable.title
    assignment.deliverables.remove(deliverable)
    await db.delete(deliverable)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.DELIVERABLE_DELETED,
        entity_type="Deliverable",
        entity_id=deliverable_id,
        change_summary=f"Deleted deliverable {title}",
    )
    await db.commit()
