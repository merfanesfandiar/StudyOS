"""Agent Workspace: conversations and conversation messages.

Two tables back the persistent workspace thread layer:

* ``conversations`` — one student↔Agent thread, tenant-scoped, optionally
  bound to a course and/or assignment (both ``SET NULL`` on delete so the
  conversation survives the resource it was bound to).
* ``conversation_messages`` — append-mostly messages ordered by a
  time-ordered UUID id (the cursor protocol is "everything after id X").
  User edits never rewrite history: the prior content is kept in
  ``edit_history_json`` and ``edited_revision`` is bumped.

Conversations are never hard-deleted by application code; ``DELETED`` is a
soft state excluded from listings.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_workspace_conversations"
down_revision: str | None = "0017_phase10_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("assignment_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_preview", sa.String(length=300), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','ARCHIVED','DELETED')",
            name="ck_conversations_status",
        ),
    )
    op.create_index(
        "ix_conversations_workspace_id", "conversations", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_conversations_workspace_status_last",
        "conversations",
        ["workspace_id", "status", "last_message_at"],
        unique=False,
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"], unique=False)
    op.create_index("ix_conversations_assignment_id", "conversations", ["assignment_id"], unique=False)

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("edited_revision", sa.Integer(), nullable=False),
        sa.Column("edit_history_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "role IN ('USER','AGENT','SYSTEM')",
            name="ck_conversation_messages_role",
        ),
        sa.CheckConstraint(
            "kind IN ('TEXT','ARTIFACT','VERIFICATION','RUN_SUMMARY','SYSTEM_NOTICE')",
            name="ck_conversation_messages_kind",
        ),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_messages_workspace_id",
        "conversation_messages",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
