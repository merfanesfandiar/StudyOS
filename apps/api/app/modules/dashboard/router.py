from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_user, get_current_workspace
from app.db.session import get_db
from app.models import Assignment, Course, Notification, User, Workspace
from app.models.enums import AssignmentStatus
from app.modules.assignments.service import assignment_summary
from app.schemas.notifications import DashboardResponse

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


def is_upcoming(deadline: datetime | None) -> bool:
    if deadline is None:
        return False
    now = datetime.now(UTC)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return deadline >= now


@router.get("", response_model=DashboardResponse, summary="Get dashboard data")
async def dashboard(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    result = await db.execute(
        select(Assignment)
        .where(Assignment.workspace_id == workspace.id)
        .order_by(Assignment.created_at.desc())
        .options(selectinload(Assignment.course))
    )
    assignments = list(result.scalars().unique().all())
    upcoming = [
        assignment_summary(assignment)
        for assignment in assignments
        if is_upcoming(assignment.deadline)
        and assignment.status
        not in {
            AssignmentStatus.COMPLETED.value,
            AssignmentStatus.ARCHIVED.value,
        }
    ]
    upcoming.sort(key=lambda item: item.deadline or datetime.max.replace(tzinfo=UTC))
    recent = [assignment_summary(assignment) for assignment in assignments[:5]]
    courses_count = await db.scalar(
        select(func.count(Course.id)).where(Course.workspace_id == workspace.id)
    )
    assignments_count = len(assignments)
    active_count = sum(item.status == AssignmentStatus.ACTIVE.value for item in assignments)
    completed_count = sum(item.status == AssignmentStatus.COMPLETED.value for item in assignments)
    unread_count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    completion_percentage = (
        round((completed_count / assignments_count) * 100) if assignments_count else 0
    )
    return DashboardResponse(
        upcoming_assignments=upcoming[:5],
        recent_assignments=recent,
        courses_count=courses_count or 0,
        assignments_count=assignments_count,
        active_assignments_count=active_count,
        completed_assignments_count=completed_count,
        completion_percentage=completion_percentage,
        unread_notifications_count=unread_count or 0,
    )
