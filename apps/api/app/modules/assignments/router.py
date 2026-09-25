from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user, get_current_workspace
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    Assignment,
    AssignmentConstraint,
    AssignmentRequirement,
    EvaluationCriterion,
    User,
    Workspace,
)
from app.models.enums import AssignmentStatus, AuditEventType
from app.modules.assignments.service import (
    assignment_response,
    get_course_in_workspace,
    load_owned_assignment,
    validate_assignment_state,
)
from app.schemas.assignments import (
    AssignmentCreate,
    AssignmentResponse,
    AssignmentUpdate,
    ConstraintCreate,
    ConstraintResponse,
    ConstraintUpdate,
    CriterionCreate,
    CriterionResponse,
    CriterionUpdate,
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
)
from app.services.events import record_audit
from app.storage import get_storage

router = APIRouter(prefix="/api/v1/assignments", tags=["Assignments"])


@router.get("", response_model=list[AssignmentResponse], summary="List assignments")
async def list_assignments(
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[AssignmentResponse]:
    result = await db.execute(
        select(Assignment)
        .where(Assignment.workspace_id == workspace.id)
        .order_by(Assignment.created_at.desc())
        .options(
            selectinload(Assignment.course),
            selectinload(Assignment.requirements),
            selectinload(Assignment.constraints),
            selectinload(Assignment.criteria),
            selectinload(Assignment.documents),
        )
    )
    return [assignment_response(assignment) for assignment in result.scalars().unique().all()]


@router.post(
    "",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an assignment draft",
)
async def create_assignment(
    payload: AssignmentCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    course_id = payload.course_id
    course = await get_course_in_workspace(course_id, workspace.id, db)
    assignment = Assignment(
        workspace_id=workspace.id,
        course_id=course.id,
        title=payload.title.strip(),
        description=payload.description,
        deadline=payload.deadline,
        status=payload.status.value,
    )
    db.add(assignment)
    await db.flush()
    validate_assignment_state(assignment)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=workspace.id,
        event_type=AuditEventType.ASSIGNMENT_CREATED,
        entity_type="Assignment",
        entity_id=assignment.id,
    )
    await db.commit()
    return assignment_response(await load_owned_assignment(assignment.id, user.id, db))


@router.get("/{assignment_id}", response_model=AssignmentResponse, summary="Get an assignment")
async def get_assignment(
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    return assignment_response(await load_owned_assignment(assignment_id, user.id, db))


@router.patch("/{assignment_id}", response_model=AssignmentResponse, summary="Update an assignment")
async def update_assignment(
    assignment_id: UUID,
    payload: AssignmentUpdate,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    changes = payload.model_dump(exclude_unset=True)
    if "course_id" in changes and changes["course_id"] is not None:
        course = await get_course_in_workspace(changes["course_id"], workspace.id, db)
        assignment.course_id = course.id
    for field in ("title", "description", "deadline", "status"):
        if field in changes:
            value = changes[field]
            if field == "status" and value is not None:
                value = value.value
            if field == "title" and value is not None:
                value = value.strip()
            setattr(assignment, field, value)
    validate_assignment_state(assignment)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        event_type=AuditEventType.ASSIGNMENT_UPDATED,
        entity_type="Assignment",
        entity_id=assignment.id,
    )
    await db.commit()
    return assignment_response(await load_owned_assignment(assignment.id, user.id, db))


@router.post(
    "/{assignment_id}/finalize", response_model=AssignmentResponse, summary="Finalize an assignment"
)
async def finalize_assignment(
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    assignment.status = AssignmentStatus.ACTIVE.value
    validate_assignment_state(assignment)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        event_type=AuditEventType.ASSIGNMENT_UPDATED,
        entity_type="Assignment",
        entity_id=assignment.id,
        metadata={"finalized": True},
    )
    await db.commit()
    return assignment_response(await load_owned_assignment(assignment.id, user.id, db))


@router.delete(
    "/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an assignment"
)
async def delete_assignment(
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    storage = get_storage()
    for document in assignment.documents:
        storage.delete(document.storage_key)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        event_type=AuditEventType.ASSIGNMENT_DELETED,
        entity_type="Assignment",
        entity_id=assignment.id,
    )
    await db.delete(assignment)
    await db.commit()


@router.get(
    "/{assignment_id}/requirements",
    response_model=list[RequirementResponse],
    summary="List assignment requirements",
)
async def list_requirements(
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RequirementResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [RequirementResponse.model_validate(item) for item in assignment.requirements]


@router.post(
    "/{assignment_id}/requirements",
    response_model=RequirementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an assignment requirement",
)
async def create_requirement(
    assignment_id: UUID,
    payload: RequirementCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RequirementResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = AssignmentRequirement(
        assignment_id=assignment.id,
        title=payload.title.strip(),
        description=payload.description,
        priority=payload.priority.value,
        type=payload.type.value,
    )
    db.add(requirement)
    await db.commit()
    await db.refresh(requirement)
    return RequirementResponse.model_validate(requirement)


@router.patch(
    "/{assignment_id}/requirements/{requirement_id}",
    response_model=RequirementResponse,
    summary="Update an assignment requirement",
)
async def update_requirement(
    assignment_id: UUID,
    requirement_id: UUID,
    payload: RequirementUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RequirementResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = next(
        (item for item in assignment.requirements if item.id == requirement_id), None
    )
    if requirement is None:
        raise AppError(404, "REQUIREMENT_NOT_FOUND", "Requirement not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(requirement, field, value.value if hasattr(value, "value") else value)
    await db.commit()
    await db.refresh(requirement)
    return RequirementResponse.model_validate(requirement)


@router.delete(
    "/{assignment_id}/requirements/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an assignment requirement",
)
async def delete_requirement(
    assignment_id: UUID,
    requirement_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    requirement = next(
        (item for item in assignment.requirements if item.id == requirement_id), None
    )
    if requirement is None:
        raise AppError(404, "REQUIREMENT_NOT_FOUND", "Requirement not found.")
    if assignment.status != AssignmentStatus.DRAFT.value:
        validate_assignment_state(assignment)
    await db.delete(requirement)
    await db.commit()


@router.get(
    "/{assignment_id}/constraints",
    response_model=list[ConstraintResponse],
    summary="List assignment constraints",
)
async def list_constraints(
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConstraintResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [ConstraintResponse.model_validate(item) for item in assignment.constraints]


@router.post(
    "/{assignment_id}/constraints",
    response_model=ConstraintResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an assignment constraint",
)
async def create_constraint(
    assignment_id: UUID,
    payload: ConstraintCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConstraintResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    constraint = AssignmentConstraint(
        assignment_id=assignment.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        value=payload.value,
    )
    db.add(constraint)
    await db.commit()
    await db.refresh(constraint)
    return ConstraintResponse.model_validate(constraint)


@router.patch(
    "/{assignment_id}/constraints/{constraint_id}",
    response_model=ConstraintResponse,
    summary="Update an assignment constraint",
)
async def update_constraint(
    assignment_id: UUID,
    constraint_id: UUID,
    payload: ConstraintUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConstraintResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    constraint = next((item for item in assignment.constraints if item.id == constraint_id), None)
    if constraint is None:
        raise AppError(404, "CONSTRAINT_NOT_FOUND", "Constraint not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(constraint, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(constraint)
    return ConstraintResponse.model_validate(constraint)


@router.delete(
    "/{assignment_id}/constraints/{constraint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an assignment constraint",
)
async def delete_constraint(
    assignment_id: UUID,
    constraint_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    constraint = next((item for item in assignment.constraints if item.id == constraint_id), None)
    if constraint is None:
        raise AppError(404, "CONSTRAINT_NOT_FOUND", "Constraint not found.")
    await db.delete(constraint)
    await db.commit()


@router.get(
    "/{assignment_id}/criteria",
    response_model=list[CriterionResponse],
    summary="List evaluation criteria",
)
async def list_criteria(
    assignment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CriterionResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [CriterionResponse.model_validate(item) for item in assignment.criteria]


@router.post(
    "/{assignment_id}/criteria",
    response_model=CriterionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an evaluation criterion",
)
async def create_criterion(
    assignment_id: UUID,
    payload: CriterionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CriterionResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    criterion = EvaluationCriterion(
        assignment_id=assignment.id,
        title=payload.title.strip(),
        description=payload.description,
        weight=payload.weight,
    )
    db.add(criterion)
    await db.flush()
    assignment.criteria.append(criterion)
    if assignment.status != AssignmentStatus.DRAFT.value:
        validate_assignment_state(assignment)
    await db.commit()
    await db.refresh(criterion)
    return CriterionResponse.model_validate(criterion)


@router.patch(
    "/{assignment_id}/criteria/{criterion_id}",
    response_model=CriterionResponse,
    summary="Update an evaluation criterion",
)
async def update_criterion(
    assignment_id: UUID,
    criterion_id: UUID,
    payload: CriterionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CriterionResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    criterion = next((item for item in assignment.criteria if item.id == criterion_id), None)
    if criterion is None:
        raise AppError(404, "CRITERION_NOT_FOUND", "Evaluation criterion not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(criterion, field, value)
    if assignment.status != AssignmentStatus.DRAFT.value:
        validate_assignment_state(assignment)
    await db.commit()
    await db.refresh(criterion)
    return CriterionResponse.model_validate(criterion)


@router.delete(
    "/{assignment_id}/criteria/{criterion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an evaluation criterion",
)
async def delete_criterion(
    assignment_id: UUID,
    criterion_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    criterion = next((item for item in assignment.criteria if item.id == criterion_id), None)
    if criterion is None:
        raise AppError(404, "CRITERION_NOT_FOUND", "Evaluation criterion not found.")
    if assignment.status != AssignmentStatus.DRAFT.value:
        projected_total = sum(
            (item.weight for item in assignment.criteria if item.id != criterion_id),
            Decimal("0.00"),
        )
        if projected_total != Decimal("100.00"):
            raise AppError(
                422,
                "CRITERIA_TOTAL_INVALID",
                "Evaluation criteria must total exactly 100% for finalized assignments.",
            )
    await db.delete(criterion)
    await db.commit()
