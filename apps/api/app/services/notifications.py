from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.models.enums import NotificationType


async def create_notification(
    db: AsyncSession,
    *,
    user_id: UUID,
    notification_type: NotificationType,
    title: str,
    message: str,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        type=notification_type.value,
        title=title,
        message=message,
    )
    db.add(notification)
    return notification
