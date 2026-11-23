"""API contracts for the Agent Workspace conversation layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.schemas.common import APIModel, Page, PageParams, PageResponse


class ConversationCreateRequest(APIModel):
    """Create a conversation, optionally bound to a course and/or assignment.

    Bindings are validated server-side against workspace membership; an
    invalid or invisible course/assignment id is a 404, never a silent drop.
    """

    title: str = Field(default="New conversation", min_length=1, max_length=200)
    course_id: UUID | None = None
    assignment_id: UUID | None = None


class ConversationUpdateRequest(APIModel):
    """Partial update: rename, archive/restore, or (re)bind the context.

    Exactly the fields supplied change. Passing ``assignment_id: null`` clears
    the binding (visible, honest semantics — the workspace shows an empty
    context panel afterwards).
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = Field(default=None, pattern="^(ACTIVE|ARCHIVED)$")
    course_id: UUID | None = None
    assignment_id: UUID | None = None

    model_config = APIModel.model_config

    @model_validator(mode="before")
    @classmethod
    def _reject_noop(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data:
            raise ValueError("At least one field must be provided.")
        return data


class ConversationListQuery(PageParams):
    """Query parameters for the conversation list.

    A dedicated model (extending the shared pagination params) because FastAPI
    0.115 expands at most one query-model per endpoint and refuses to combine
    one with separate ``Query()`` parameters.
    """

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, pattern="^(ACTIVE|ARCHIVED)$")


class ConversationResponse(APIModel):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    course_id: UUID | None
    assignment_id: UUID | None
    title: str
    status: str
    last_preview: str | None
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(PageResponse[ConversationResponse]):
    page: Page


class MessageCreateRequest(APIModel):
    """Post a message to a conversation.

    The backend persists what the user said; it never fabricates an agent
    reply in the same response. Agent-facing content arrives from real
    backend events (run outcomes, notices), delivered via subsequent reads.
    """

    content: str = Field(min_length=1, max_length=8000)
    kind: str = Field(default="TEXT", pattern="^(TEXT)$")


class MessageEditRequest(APIModel):
    """Edit a user message.

    Semantics (explicit, never a silent rewrite): only the conversation's
    most recent USER message can be edited; the prior content is preserved in
    the message's edit history and ``edited_revision`` is bumped.
    """

    content: str = Field(min_length=1, max_length=8000)


class MessageResponse(APIModel):
    id: UUID
    conversation_id: UUID
    role: str
    kind: str
    content: str
    metadata_json: dict[str, Any]
    edited_revision: int
    edit_history_json: list[dict[str, Any]]
    created_at: datetime


class MessagePageResponse(APIModel):
    """Cursor-paged message window.

    ``items`` is ordered oldest→newest. ``next_before_cursor`` walks further
    back in history; ``after_cursor`` echoes the id the client should use for
    the next incremental read (its newest message id).
    """

    conversation_id: UUID
    items: list[MessageResponse]
    next_before_cursor: UUID | None
    has_more_history: bool
