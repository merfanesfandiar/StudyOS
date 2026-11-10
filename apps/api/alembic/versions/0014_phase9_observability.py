"""Phase 9: observability, audit trail, and operational intelligence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_phase9_observability"
down_revision: str | None = "0013_phase8_interactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_events") as batch_op:
        batch_op.alter_column("event_type", type_=sa.String(60), existing_type=sa.String(40), existing_nullable=False)
        batch_op.add_column(sa.Column("workspace_id", sa.Uuid()))
        batch_op.add_column(sa.Column("assignment_id", sa.Uuid()))
        batch_op.add_column(sa.Column("user_id", sa.Uuid()))
        batch_op.add_column(sa.Column("correlation_id", sa.String(64)))
        batch_op.add_column(sa.Column("causation_id", sa.String(64)))
        batch_op.add_column(sa.Column("trace_id", sa.String(64)))
        batch_op.add_column(sa.Column("span_id", sa.String(32)))
        batch_op.add_column(sa.Column("severity", sa.String(20), nullable=False, server_default="INFO"))
        batch_op.add_column(sa.Column("source_component", sa.String(40), nullable=False, server_default="agent.runtime"))
        batch_op.add_column(sa.Column("outcome", sa.String(30)))
        batch_op.add_column(sa.Column("duration_ms", sa.Integer()))
        batch_op.add_column(sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_agent_events_run_type", "agent_events", ["run_id", "event_type"])
    op.create_index("ix_agent_events_correlation_id", "agent_events", ["correlation_id"])
    op.create_index("ix_agent_events_trace_id", "agent_events", ["trace_id"])

    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.add_column(sa.Column("agent_run_id", sa.Uuid()))
        batch_op.add_column(sa.Column("action", sa.String(80)))
        batch_op.add_column(sa.Column("target_type", sa.String(80)))
        batch_op.add_column(sa.Column("target_id", sa.Uuid()))
        batch_op.add_column(sa.Column("actor_type", sa.String(20), nullable=False, server_default="user"))
        batch_op.add_column(sa.Column("outcome", sa.String(30)))
        batch_op.add_column(sa.Column("reason", sa.String(200)))
        batch_op.add_column(sa.Column("correlation_id", sa.String(64)))
        batch_op.add_column(sa.Column("policy_code", sa.String(80)))
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_column("policy_code")
        batch_op.drop_column("correlation_id")
        batch_op.drop_column("reason")
        batch_op.drop_column("outcome")
        batch_op.drop_column("actor_type")
        batch_op.drop_column("target_id")
        batch_op.drop_column("target_type")
        batch_op.drop_column("action")
        batch_op.drop_column("agent_run_id")

    op.drop_index("ix_agent_events_trace_id", table_name="agent_events")
    op.drop_index("ix_agent_events_correlation_id", table_name="agent_events")
    op.drop_index("ix_agent_events_run_type", table_name="agent_events")
    with op.batch_alter_table("agent_events") as batch_op:
        batch_op.drop_column("recorded_at")
        batch_op.drop_column("schema_version")
        batch_op.drop_column("duration_ms")
        batch_op.drop_column("outcome")
        batch_op.drop_column("source_component")
        batch_op.drop_column("severity")
        batch_op.drop_column("span_id")
        batch_op.drop_column("trace_id")
        batch_op.drop_column("causation_id")
        batch_op.drop_column("correlation_id")
        batch_op.drop_column("user_id")
        batch_op.drop_column("assignment_id")
        batch_op.drop_column("workspace_id")
        batch_op.alter_column("event_type", type_=sa.String(40), existing_type=sa.String(60), existing_nullable=False)
