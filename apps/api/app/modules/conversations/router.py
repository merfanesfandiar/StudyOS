"""HTTP surface for workspace conversations.

Routes are tenant-scoped through the caller's workspace membership; the
service layer owns every authorisation decision, the router only shapes
requests and responses.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Conversation, User
from app.models.enums import ConversationRole, MessageKind
from app.schemas.common import Page, error_responses

from . import service
from .schemas import (
    ConversationCreateRequest,
    ConversationListQuery,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageCreateRequest,
    MessageEditRequest,
    MessagePageResponse,
    MessageResponse,
)

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(prefix="/api/v1/conversations", tags=["Agent Workspace"])


def _model(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse.model_validate(conversation)


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=201,
    summary="Create a conversation, optionally bound to a course/assignment",
    responses=error_responses(404, 422),
)
async def create_conversation(
    body: ConversationCreateRequest,
    user: CurrentUser,
    db: Db,
) -> ConversationResponse:
    conversation = await service.create_conversation(
        user,
        db,
        title=body.title,
        course_id=body.course_id,
        assignment_id=body.assignment_id,
    )
    await db.commit()
    return _model(conversation)


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="List conversations (paged, searchable)",
    responses=error_responses(422),
)
async def list_conversations(
    user: CurrentUser,
    db: Db,
    query: Annotated[ConversationListQuery, Query()],
) -> ConversationListResponse:
    items, total = await service.list_conversations(
        user,
        db,
        page=query.page,
        page_size=query.page_size,
        q=query.q,
        status=query.status,
    )
    pages = max(1, -(-(total or 0) // query.page_size))
    return ConversationListResponse(
        items=[_model(c) for c in items],
        page=Page(page=query.page, page_size=query.page_size, total=total, pages=pages),
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Conversation detail",
    responses=error_responses(404),
)
async def get_conversation(
    conversation_id: UUID, user: CurrentUser, db: Db
) -> ConversationResponse:
    conversation = await service.load_owned_conversation(conversation_id, user, db)
    return _model(conversation)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Rename, archive/restore, or rebind a conversation",
    responses=error_responses(404, 422),
)
async def update_conversation(
    conversation_id: UUID,
    body: ConversationUpdateRequest,
    user: CurrentUser,
    db: Db,
) -> ConversationResponse:
    conversation = await service.load_owned_conversation(conversation_id, user, db)
    conversation = await service.update_conversation(
        conversation,
        user,
        db,
        title=body.title,
        status=body.status,
        course_id=body.course_id,
        assignment_id=body.assignment_id,
        course_provided="course_id" in body.model_fields_set,
        assignment_provided="assignment_id" in body.model_fields_set,
    )
    await db.commit()
    return _model(conversation)


@router.delete(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Soft-delete a conversation (history is kept, listing hides it)",
    responses=error_responses(404),
)
async def delete_conversation(
    conversation_id: UUID, user: CurrentUser, db: Db
) -> ConversationResponse:
    conversation = await service.load_owned_conversation(conversation_id, user, db)
    await service.soft_delete_conversation(conversation, db)
    await db.commit()
    return _model(conversation)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessagePageResponse,
    summary="Cursor-paged message window (initial view, history, or incremental)",
    responses=error_responses(404, 422),
)
async def list_messages(
    conversation_id: UUID,
    user: CurrentUser,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[UUID | None, Query(description="Walk back: ids strictly before")] = None,
    after: Annotated[UUID | None, Query(description="Incremental: ids strictly after")] = None,
) -> MessagePageResponse:
    conversation = await service.load_owned_conversation(conversation_id, user, db)
    if before is not None and after is not None:
        raise AppError(422, "CURSOR_CONFLICT", "Use either before or after, not both.")
    items, has_more = await service.list_messages(
        conversation,
        db,
        limit=limit,
        before=before,
        after=after,
    )
    return MessagePageResponse(
        conversation_id=conversation.id,
        items=[MessageResponse.model_validate(m) for m in items],
        next_before_cursor=items[0].id if has_more and items else None,
        has_more_history=has_more,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    summary="Post a user message",
    responses=error_responses(404, 422),
)
async def post_message(
    conversation_id: UUID,
    body: MessageCreateRequest,
    user: CurrentUser,
    db: Db,
) -> MessageResponse:
    conversation = await service.load_owned_conversation(conversation_id, user, db)
    message = await service.add_message(
        conversation,
        db,
        role=ConversationRole.USER,
        kind=MessageKind.TEXT,
        content=body.content,
    )
    await db.commit()
    return MessageResponse.model_validate(message)


@router.patch(
    "/{conversation_id}/messages/{message_id}",
    response_model=MessageResponse,
    summary="Edit the most recent user message (prior content preserved)",
    responses=error_responses(404, 422),
)
async def edit_message(
    conversation_id: UUID,
    message_id: UUID,
    body: MessageEditRequest,
    user: CurrentUser,
    db: Db,
) -> MessageResponse:
    conversation = await service.load_owned_conversation(conversation_id, user, db)
    message = await service.edit_last_user_message(
        conversation, message_id, user, db, content=body.content
    )
    await db.commit()
    return MessageResponse.model_validate(message)
