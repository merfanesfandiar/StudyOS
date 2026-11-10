"""Phase 8: human-in-the-loop interactions.

Generalize checkpoints into durable interactions with separate response
history, operation binding, risk/priority, expiration, and ownership checks.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_phase8_interactions"
down_revision: str | None = "0012_phase7_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_interactions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("checkpoint_id", sa.Uuid()),
        sa.Column("owner_id", sa.Uuid()),
        sa.Column("interaction_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("risk", sa.String(10), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("context", sa.Text()),
        sa.Column("options", sa.JSON()),
        sa.Column("operation_binding", sa.JSON(), nullable=False),
        sa.Column("ui", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(500)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["plan_tasks.id"], name="fk_agent_interaction_task", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["checkpoint_id"], ["agent_checkpoints.id"], name="fk_agent_interaction_checkpoint", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('PENDING','SUBMITTED','ACCEPTED','REJECTED','EXPIRED','CANCELLED')",
            name="agent_interactions_status_valid",
        ),
        sa.CheckConstraint("risk IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="agent_interactions_risk_valid"),
        sa.CheckConstraint("priority IN ('LOW','NORMAL','HIGH','URGENT')", name="agent_interactions_priority_valid"),
        sa.CheckConstraint(
            "interaction_type IN ('CLARIFICATION','USER_DECISION','PLAN_APPROVAL','TASK_APPROVAL',"
            "'TOOL_PERMISSION','EXECUTION_APPROVAL','ARTIFACT_REVIEW','ARTIFACT_APPROVAL',"
            "'DESTRUCTIVE_ACTION_APPROVAL','EXTERNAL_ACTION_APPROVAL','CONFLICT_RESOLUTION',"
            "'EXCEPTION_RESOLUTION','OTHER')",
            name="agent_interactions_type_valid",
        ),
    )
    op.create_index("ix_agent_interactions_run_id", "agent_interactions", ["run_id"])
    op.create_index("ix_agent_interactions_assignment_id", "agent_interactions", ["assignment_id"])
    op.create_index("ix_agent_interactions_workspace_id", "agent_interactions", ["workspace_id"])
    op.create_index("ix_agent_interactions_run_status", "agent_interactions", ["run_id", "status"])
    op.create_index("ix_agent_interactions_status", "agent_interactions", ["status"])
    op.create_index("ix_agent_interactions_checkpoint_id", "agent_interactions", ["checkpoint_id"])
    op.create_index("ix_agent_interactions_owner_id", "agent_interactions", ["owner_id"])
    op.create_index("ix_agent_interactions_expires_at", "agent_interactions", ["expires_at"])

    op.create_table(
        "agent_interaction_responses",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("interaction_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("responder_id", sa.Uuid()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response_type", sa.String(30)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("artifacts", sa.JSON()),
        sa.Column("diff", sa.JSON()),
        sa.Column("operation_binding_snapshot", sa.JSON(), nullable=False),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["interaction_id"], ["agent_interactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["responder_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("interaction_id", "version", name="uq_agent_interaction_response_version"),
        sa.CheckConstraint("status IN ('SUBMITTED','ACCEPTED','REJECTED')", name="agent_interaction_responses_status_valid"),
    )
    op.create_index("ix_agent_interaction_responses_interaction_id", "agent_interaction_responses", ["interaction_id"])
    op.create_index("ix_agent_interaction_responses_run_id", "agent_interaction_responses", ["run_id"])
    op.create_index("ix_agent_interaction_responses_responder_id", "agent_interaction_responses", ["responder_id"])


def downgrade() -> None:
    op.drop_table("agent_interaction_responses")
    op.drop_table("agent_interactions")
