from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_workspace, get_owned_course
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Assignment, Course, User, Workspace
from app.models.enums import AuditEventType
from app.schemas.courses import CourseCreate, CourseResponse, CourseUpdate
from app.services.events import record_audit

router = APIRouter(prefix="/api/v1/courses", tags=["Courses"])


def course_response(course: Course, assignment_count: int = 0) -> CourseResponse:
    return CourseResponse(
        id=str(course.id),
        workspace_id=str(course.workspace_id),
        name=course.name,
        code=course.code,
        description=course.description,
        created_at=course.created_at,
        updated_at=course.updated_at,
        assignment_count=assignment_count,
    )


@router.get("", response_model=list[CourseResponse], summary="List workspace courses")
async def list_courses(
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> list[CourseResponse]:
    result = await db.execute(
        select(Course, func.count(Assignment.id))
        .outerjoin(Assignment, Assignment.course_id == Course.id)
        .where(Course.workspace_id == workspace.id)
        .group_by(Course.id)
        .order_by(Course.created_at.desc())
    )
    return [course_response(course, count) for course, count in result.all()]


@router.post(
    "",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a course",
)
async def create_course(
    payload: CourseCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    course = Course(
        workspace_id=workspace.id,
        name=payload.name,
        code=payload.code,
        description=payload.description,
    )
    db.add(course)
    try:
        await db.flush()
        await record_audit(
            db,
            user_id=user.id,
            workspace_id=workspace.id,
            event_type=AuditEventType.COURSE_CREATED,
            entity_type="Course",
            entity_id=course.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(
            409, "COURSE_CODE_EXISTS", "A course with this code already exists in the workspace."
        ) from exc
    await db.refresh(course)
    return course_response(course)


@router.get("/{course_id}", response_model=CourseResponse, summary="Get a course")
async def get_course(
    course_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    course = await get_owned_course(course_id, user, db)
    count = await db.scalar(
        select(func.count(Assignment.id)).where(Assignment.course_id == course.id)
    )
    return course_response(course, count or 0)


@router.patch("/{course_id}", response_model=CourseResponse, summary="Update a course")
async def update_course(
    course_id: UUID,
    payload: CourseUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    course = await get_owned_course(course_id, user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    try:
        await record_audit(
            db,
            user_id=user.id,
            workspace_id=course.workspace_id,
            event_type=AuditEventType.COURSE_UPDATED,
            entity_type="Course",
            entity_id=course.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(
            409, "COURSE_CODE_EXISTS", "A course with this code already exists in the workspace."
        ) from exc
    await db.refresh(course)
    count = await db.scalar(
        select(func.count(Assignment.id)).where(Assignment.course_id == course.id)
    )
    return course_response(course, count or 0)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a course")
async def delete_course(
    course_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    course = await get_owned_course(course_id, user, db)
    assignment_count = await db.scalar(
        select(func.count(Assignment.id)).where(Assignment.course_id == course.id)
    )
    if assignment_count:
        raise AppError(
            409, "COURSE_HAS_ASSIGNMENTS", "Delete or move the course assignments first."
        )
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=course.workspace_id,
        event_type=AuditEventType.COURSE_DELETED,
        entity_type="Course",
        entity_id=course.id,
    )
    await db.delete(course)
    await db.commit()
