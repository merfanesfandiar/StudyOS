from datetime import datetime
from uuid import UUID

from app.schemas.assignments import AssignmentSummary
from app.schemas.common import APIModel


class DashboardResponse(APIModel):
    upcoming_assignments: list[AssignmentSummary]
    recent_assignments: list[AssignmentSummary]
    courses_count: int
    assignments_count: int
    active_assignments_count: int
    completed_assignments_count: int
    completion_percentage: int
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
