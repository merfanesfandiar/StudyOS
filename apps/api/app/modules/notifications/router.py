from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Notification, User
from app.schemas.common import Page, PageParams, PageResponse, error_responses
from app.schemas.notifications import NotificationResponse

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.get(
    "",
    response_model=PageResponse[NotificationResponse],
    summary="List in-app notifications",
    responses=error_responses(422),
)
async def list_notifications(
    params: Annotated[PageParams, Query()],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PageResponse[NotificationResponse]:
    total = await db.scalar(
        select(func.count(Notification.id)).where(Notification.user_id == user.id)
    )
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(params.offset)
        .limit(params.limit)
    )
    pages = max(1, -(-(total or 0) // params.page_size))
    return PageResponse(
        items=[NotificationResponse.model_validate(item) for item in result.scalars().all()],
        page=Page(page=params.page, page_size=params.page_size, total=total or 0, pages=pages),
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark a notification read",
    responses=error_responses(404, 422),
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
