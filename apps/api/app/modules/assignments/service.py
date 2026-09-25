from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import Assignment, Course, WorkspaceMember
from app.models.enums import AssignmentStatus
from app.schemas.assignments import AssignmentResponse, AssignmentSummary


async def load_owned_assignment(assignment_id: UUID, user_id: UUID, db: AsyncSession) -> Assignment:
    result = await db.execute(
        select(Assignment)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Assignment.workspace_id)
        .where(Assignment.id == assignment_id, WorkspaceMember.user_id == user_id)
        .options(
            selectinload(Assignment.course),
            selectinload(Assignment.requirements),
            selectinload(Assignment.constraints),
            selectinload(Assignment.criteria),
            selectinload(Assignment.documents),
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise AppError(404, "ASSIGNMENT_NOT_FOUND", "Assignment not found.")
    return assignment


def assignment_response(assignment: Assignment) -> AssignmentResponse:
    total = sum((criterion.weight for criterion in assignment.criteria), Decimal("0.00"))
    return AssignmentResponse(
        id=str(assignment.id),
        workspace_id=str(assignment.workspace_id),
        course_id=str(assignment.course_id),
        course_name=assignment.course.name,
        course_code=assignment.course.code,
        title=assignment.title,
        description=assignment.description,
        deadline=assignment.deadline,
        status=AssignmentStatus(assignment.status),
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
        requirements=assignment.requirements,
        constraints=assignment.constraints,
        criteria=assignment.criteria,
        documents=assignment.documents,
        criteria_total=total,
    )


def assignment_summary(assignment: Assignment) -> AssignmentSummary:
    return AssignmentSummary(
        id=str(assignment.id),
        course_id=str(assignment.course_id),
        course_name=assignment.course.name,
        course_code=assignment.course.code,
        title=assignment.title,
        deadline=assignment.deadline,
        status=AssignmentStatus(assignment.status),
    )


def validate_assignment_state(assignment: Assignment) -> None:
    if assignment.status != AssignmentStatus.ACTIVE.value:
        return
    if assignment.deadline is None:
        raise AppError(
            422, "DEADLINE_REQUIRED", "A deadline is required before finalizing an assignment."
        )
    total = sum((criterion.weight for criterion in assignment.criteria), Decimal("0.00"))
    if total != Decimal("100.00"):
        raise AppError(
            422,
            "CRITERIA_TOTAL_INVALID",
            "Evaluation criteria must total exactly 100% before finalizing an assignment.",
            {"total": str(total)},
        )


async def get_course_in_workspace(course_id: UUID, workspace_id: UUID, db: AsyncSession) -> Course:
    course = await db.scalar(
        select(Course).where(Course.id == course_id, Course.workspace_id == workspace_id)
    )
    if course is None:
        raise AppError(404, "COURSE_NOT_FOUND", "Course not found.")
    return course
