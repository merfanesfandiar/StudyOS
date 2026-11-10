from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_workspace
from app.db.session import get_db
from app.models import Assignment, Course, Notification, User, Workspace
from app.models.enums import AssignmentStatus
from app.modules.assignments.service import SPECIFICATION_LOADERS, assignment_list_item
from app.schemas.notifications import DashboardResponse

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])

#: States where the student still has work in front of them. Phase 1 called
#: this "active"; the specification engine replaced that with a readiness gate,
#: so a draft that nobody has finished now counts here too.
IN_PROGRESS: frozenset[AssignmentStatus] = frozenset(
    {
        AssignmentStatus.DRAFT,
        AssignmentStatus.INCOMPLETE,
        AssignmentStatus.READY_FOR_ANALYSIS,
        AssignmentStatus.ANALYSIS_IN_PROGRESS,
        AssignmentStatus.ANALYZED,
    }
)


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
        .options(*SPECIFICATION_LOADERS)
        # Bounded deliberately: this is a summary the home page renders, not a
        # bulk export. Every assignment here is eagerly loaded with its full
        # specification, so an uncapped read would scan the whole workspace on
        # every dashboard visit and grow linearly with use. The cap only needs
        # to exceed what the UI can render; older rows are reachable through
        # the assignment list, which is filtered and paginated properly.
        .limit(500)
    )
    assignments = list(result.scalars().unique().all())
    items = [assignment_list_item(assignment) for assignment in assignments]

    upcoming = [
        item
        for item, assignment in zip(items, assignments, strict=True)
        if is_upcoming(assignment.deadline)
        and AssignmentStatus(assignment.status)
        not in {AssignmentStatus.COMPLETED, AssignmentStatus.ARCHIVED}
    ]
    upcoming.sort(key=lambda item: item.deadline or datetime.max.replace(tzinfo=UTC))

    states = [AssignmentStatus(assignment.status) for assignment in assignments]
    in_progress = sum(state in IN_PROGRESS for state in states)
    ready = sum(state is AssignmentStatus.READY_FOR_ANALYSIS for state in states)
    incomplete = sum(
        state in {AssignmentStatus.DRAFT, AssignmentStatus.INCOMPLETE} for state in states
    )
    completed = sum(state is AssignmentStatus.COMPLETED for state in states)

    courses_count = await db.scalar(
        select(func.count(Course.id)).where(Course.workspace_id == workspace.id)
    )
    assignments_count = len(assignments)
    unread_count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    completion_percentage = round((completed / assignments_count) * 100) if assignments_count else 0
    # Aggregate in SQL over the whole workspace, not over the 500-row window the
    # page can render. The window is a rendering bound; using it for an average
    # silently turned "your average readiness" into "the average of the newest
    # 500 assignments" once a workspace grew past the cap.
    readiness_average = await db.scalar(
        select(func.avg(Assignment.readiness_score)).where(
            Assignment.workspace_id == workspace.id
        )
    )
    average_readiness_score = round(float(readiness_average or 0))
    return DashboardResponse(
        upcoming_assignments=upcoming,
        recent_assignments=items[:5],
        courses_count=courses_count or 0,
        assignments_count=assignments_count,
        in_progress_assignments_count=in_progress,
        ready_assignments_count=ready,
        incomplete_assignments_count=incomplete,
        completed_assignments_count=completed,
        completion_percentage=completion_percentage,
        average_readiness_score=average_readiness_score,
        unread_notifications_count=unread_count or 0,
    )
