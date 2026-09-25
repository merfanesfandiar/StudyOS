from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Notification, User
from app.schemas.notifications import NotificationResponse

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationResponse], summary="List in-app notifications")
async def list_notifications(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[NotificationResponse]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    return [NotificationResponse.model_validate(item) for item in result.scalars().all()]


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark a notification read",
)
async def mark_notification_read(
    notification_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    notification = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if notification is None:
        raise AppError(404, "NOTIFICATION_NOT_FOUND", "Notification not found.")
    notification.read_at = notification.read_at or datetime.now(UTC)
    await db.commit()
    await db.refresh(notification)
    return NotificationResponse.model_validate(notification)
