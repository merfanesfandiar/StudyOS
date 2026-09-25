from datetime import datetime
from uuid import UUID

from app.schemas.assignments import AssignmentListItem
from app.schemas.common import APIModel


class DashboardResponse(APIModel):
    """Dashboard numbers.

    Assignments are listed with their readiness row so the dashboard can show
    how far along each specification is, not just whether it is open.
    """

    upcoming_assignments: list[AssignmentListItem]
    recent_assignments: list[AssignmentListItem]
    courses_count: int
    assignments_count: int
    in_progress_assignments_count: int
    ready_assignments_count: int
    incomplete_assignments_count: int
    completed_assignments_count: int
    completion_percentage: int
    average_readiness_score: int
    unread_notifications_count: int


class NotificationCreate(APIModel):
    type: str
    title: str
    message: str


class NotificationResponse(APIModel):
    id: UUID
    type: str
    title: str
    message: str
    read_at: datetime | None
    created_at: datetime
