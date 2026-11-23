"""Conversation persistence for the Agent Workspace.

Design constraints (see docs/architecture/agent-workspace.md):

* Conversations are the durable container the workspace UI renders. They do
  not duplicate the agent event stream, artifacts, or verification reports —
  reference messages point at those records via ``metadata_json``.
* Tenant isolation follows the house pattern: every query joins
  ``WorkspaceMember`` on the denormalised ``workspace_id``; an invisible id is
  a 404, never a leak.
* The runtime has no free-form chat responder. ``AGENT`` messages are written
  only by the run-completion bridge (real backend outcomes) — nothing in this
  module invents agent prose.
* Deletion is soft: rows keep their history and are excluded from listings.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    AcademicWorkPlan,
    Assignment,
    Conversation,
    ConversationMessage,
    Course,
    User,
    VerificationRun,
    WorkspaceMember,
)
from app.models.enums import ConversationRole, ConversationStatus, MessageKind

logger = logging.getLogger("studyos")

PREVIEW_MAX = 300
MAX_EDIT_HISTORY = 10


async def _workspace_id_for(user: User, db: AsyncSession) -> UUID:
    """The caller's primary workspace, same resolution the shell uses."""
    result = await db.execute(
        select(WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.asc())
        .limit(1)
    )
    workspace_id = result.scalar_one_or_none()
    if workspace_id is None:
        raise AppError(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    return workspace_id


async def _owned_assignment(assignment_id: UUID, user: User, db: AsyncSession) -> Assignment:
    result = await db.execute(
        select(Assignment)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Assignment.workspace_id)
        .where(Assignment.id == assignment_id, WorkspaceMember.user_id == user.id)
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise AppError(404, "ASSIGNMENT_NOT_FOUND", "Assignment not found.")
    return assignment


async def _owned_course(course_id: UUID, user: User, db: AsyncSession) -> Course:
    result = await db.execute(
        select(Course)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Course.workspace_id)
        .where(Course.id == course_id, WorkspaceMember.user_id == user.id)
    )
    course = result.scalar_one_or_none()
    if course is None:
        raise AppError(404, "COURSE_NOT_FOUND", "Course not found.")
    return course


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


async def create_conversation(
    user: User,
    db: AsyncSession,
    *,
    title: str,
    course_id: UUID | None,
    assignment_id: UUID | None,
) -> Conversation:
    workspace_id = await _workspace_id_for(user, db)
    if assignment_id is not None:
        assignment = await _owned_assignment(assignment_id, user, db)
        workspace_id = assignment.workspace_id
        if course_id is None:
            course_id = assignment.course_id
    if course_id is not None:
        await _owned_course(course_id, user, db)
    conversation = Conversation(
        workspace_id=workspace_id,
        user_id=user.id,
        course_id=course_id,
        assignment_id=assignment_id,
        title=title[:200],
        status=ConversationStatus.ACTIVE.value,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def load_owned_conversation(
    conversation_id: UUID, user: User, db: AsyncSession, *, include_deleted: bool = False
) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Conversation.workspace_id)
        .where(
            Conversation.id == conversation_id,
            WorkspaceMember.user_id == user.id,
            *([] if include_deleted else [Conversation.status != ConversationStatus.DELETED.value]),
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise AppError(404, "CONVERSATION_NOT_FOUND", "Conversation not found.")
    return conversation


async def list_conversations(
    user: User,
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    q: str | None,
    status: str | None,
) -> tuple[list[Conversation], int]:
    """Paged, searched conversation list for the sidebar.

    ``status=None`` means "everything not deleted" — the archived drawer is an
    explicit opt-in via ``status=ARCHIVED``, matching the UI's intent.
    """
    base = (
        select(Conversation)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Conversation.workspace_id)
        .where(WorkspaceMember.user_id == user.id)
    )
    if status is not None:
        base = base.where(Conversation.status == status)
    else:
        # Default listing = active conversations only. Archived ones live in
        # the explicit archive drawer; deleted ones are gone from every view.
        base = base.where(Conversation.status == ConversationStatus.ACTIVE.value)
    if q:
        like = f"%{q.strip()[:100]}%"
        base = base.where(Conversation.title.ilike(like) | Conversation.last_preview.ilike(like))

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.scalars(
        base.order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.all()), total or 0


async def update_conversation(
    conversation: Conversation,
    user: User,
    db: AsyncSession,
    *,
    title: str | None,
    status: str | None,
    course_id: UUID | None,
    assignment_id: UUID | None,
    course_provided: bool,
    assignment_provided: bool,
) -> Conversation:
    if title is not None:
        conversation.title = title[:200]
    if status is not None:
        conversation.status = status
    if course_provided:
        if course_id is not None:
            await _owned_course(course_id, user, db)
        conversation.course_id = course_id
    if assignment_provided:
        if assignment_id is not None:
            assignment = await _owned_assignment(assignment_id, user, db)
            if assignment.workspace_id != conversation.workspace_id:
                raise AppError(
                    422, "CROSS_WORKSPACE_BINDING", "Assignment is in another workspace."
                )
        conversation.assignment_id = assignment_id
    await db.flush()
    return conversation


async def soft_delete_conversation(conversation: Conversation, db: AsyncSession) -> None:
    """Soft delete: history is kept, the row disappears from listings."""
    conversation.status = ConversationStatus.DELETED.value
    await db.flush()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _preview(content: str) -> str:
    collapsed = " ".join(content.split())
    return collapsed[:PREVIEW_MAX]


async def _touch_conversation(
    conversation: Conversation, message: ConversationMessage
) -> None:
    conversation.last_message_at = datetime.now(UTC)
    conversation.last_message_id = message.id
    conversation.last_preview = _preview(message.content)


async def add_message(
    conversation: Conversation,
    db: AsyncSession,
    *,
    role: ConversationRole,
    kind: MessageKind,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> ConversationMessage:
    message = ConversationMessage(
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        role=role.value,
        kind=kind.value,
        content=content,
        metadata_json=metadata or {},
    )
    db.add(message)
    await db.flush()
    await _touch_conversation(conversation, message)
    return message


async def list_messages(
    conversation: Conversation,
    db: AsyncSession,
    *,
    limit: int,
    before: UUID | None,
    after: UUID | None,
) -> tuple[list[ConversationMessage], bool]:
    """Cursor window over the conversation, ordered oldest→newest.

    Without a cursor the window is the most recent ``limit`` messages (the
    initial chat view). ``after`` returns everything newer — used after a
    refresh or reconnect. ``before`` walks back through history.
    """
    stmt = select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.workspace_id == conversation.workspace_id,
    )
    if after is not None:
        stmt = stmt.where(ConversationMessage.id > after).order_by(ConversationMessage.id.asc())
    elif before is not None:
        stmt = stmt.where(ConversationMessage.id < before).order_by(
            ConversationMessage.id.desc()
        )
    else:
        # No cursor: the initial view is the most recent window, oldest→newest.
        stmt = stmt.order_by(ConversationMessage.id.desc())
    rows = list((await db.scalars(stmt.limit(limit + 1))).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not (after is not None):
        rows.reverse()
    return rows, has_more


async def edit_last_user_message(
    conversation: Conversation, message_id: UUID, user: User, db: AsyncSession, *, content: str
) -> ConversationMessage:
    """Apply the documented edit semantics.

    Only the most recent USER message may be edited, and the prior content is
    preserved: history is never silently rewritten. AGENT/SYSTEM messages are
    not editable at all — they are records of what the backend actually did.
    """
    message = await db.get(ConversationMessage, message_id)
    if (
        message is None
        or message.conversation_id != conversation.id
        or message.workspace_id != conversation.workspace_id
    ):
        raise AppError(404, "MESSAGE_NOT_FOUND", "Message not found.")
    if message.role != ConversationRole.USER.value:
        raise AppError(
            422, "MESSAGE_NOT_EDITABLE", "Only your own messages can be edited."
        )
    latest = await db.scalar(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.role == ConversationRole.USER.value,
        )
        .order_by(ConversationMessage.id.desc())
        .limit(1)
    )
    if latest is None or latest.id != message.id:
        raise AppError(
            422,
            "MESSAGE_NOT_LATEST",
            "Only the most recent message can be edited; send a new message instead.",
        )
    history = list(message.edit_history_json)
    history.append(
        {"revision": message.edited_revision, "content": message.content}
    )
    message.edit_history_json = history[-MAX_EDIT_HISTORY:]
    message.edited_revision = message.edited_revision + 1
    message.content = content
    await db.flush()
    await _touch_conversation(conversation, message)
    return message


# ---------------------------------------------------------------------------
# Run-completion bridge (called by the agent runtime)
# ---------------------------------------------------------------------------


async def record_run_outcome(db: AsyncSession, run: Any) -> None:
    """Bridge a finished agent run into any conversation bound to it.

    This is the one place AGENT-authored chat content is produced: a factual
    run summary (status, task counts, verification pointer) built from the
    run record — never model prose, never fabricated progress. Every failure
    here is swallowed: the run's own terminal state must not be affected by a
    conversation hiccup. Idempotent per (run, status): a replayed transition
    must not duplicate the summary message.
    """
    try:
        assignment_id = getattr(run, "assignment_id", None)
        if assignment_id is None:
            return
        rows = await db.scalars(
            select(Conversation).where(
                Conversation.assignment_id == assignment_id,
                Conversation.status == ConversationStatus.ACTIVE.value,
            )
        )
        conversations = list(rows.all())
        if not conversations:
            return

        status = getattr(run, "status", "")
        # Portable dedupe: JSON membership filtering differs between SQLite
        # (tests) and Postgres (production), so compare in Python — the
        # candidate set is bounded by the bound conversations' summaries.
        summaries = list(
            await db.scalars(
                select(ConversationMessage)
                .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
                .where(
                    Conversation.assignment_id == assignment_id,
                    ConversationMessage.role == ConversationRole.AGENT.value,
                    ConversationMessage.kind == MessageKind.RUN_SUMMARY.value,
                )
            )
        )
        if any(
            m.metadata_json.get("run_id") == str(run.id)
            and m.metadata_json.get("kind_detail") == status
            for m in summaries
        ):
            return
        counts: dict[str, int] = {}
        try:
            from app.modules.agent.selection import progress
            from app.modules.agent.service import _task_nodes

            if run.plan_id is not None:
                plan = await db.get(AcademicWorkPlan, run.plan_id)
                if plan is not None:
                    counts = progress(await _task_nodes(db, plan))
        except Exception:  # pragma: no cover - summary stays best-effort
            counts = {}

        lines = [f"Run **{status}**."]
        if counts:
            lines.append(
                f"Completed {counts.get('completed', 0)} of {counts.get('total', 0)} tasks."
            )
        metadata: dict[str, Any] = {"run_id": str(run.id), "kind_detail": status}
        verification_run_id = await db.scalar(
            select(VerificationRun.id)
            .where(VerificationRun.agent_run_id == run.id)
            .order_by(VerificationRun.created_at.desc())
            .limit(1)
        )
        if verification_run_id:
            metadata["verification_run_id"] = str(verification_run_id)
            lines.append("A verification report for this run is available.")
        content = "\n\n".join(lines)
        for conversation in conversations:
            await add_message(
                conversation,
                db,
                role=ConversationRole.AGENT,
                kind=MessageKind.RUN_SUMMARY,
                content=content,
                metadata=metadata,
            )
        await db.flush()
    except Exception:
        logger.exception("Recording run outcome in conversations failed; run %s", run.id)
