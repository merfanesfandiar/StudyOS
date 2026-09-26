"""Phase 3: universal academic assignment intelligence.

Adds the analysis layer: immutable AI analyses, analysis runs, clarification
questions and user-correctable classifications. No authoritative specification
table is modified: an analysis is an interpretation that references the
assignment and the immutable specification version it was computed against.

Every table cascades from ``assignments`` so an analysis can never outlive the
assignment it describes, and user references are ``SET NULL`` so deleting a
student account does not delete academic work.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase3_analysis"
down_revision: str | None = "0002_phase2_specification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assignment_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("specification_version", sa.Integer(), nullable=False),
        sa.Column("specification_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("edited_payload", sa.JSON(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assignment_id", "idempotency_key", name="uq_analysis_assignment_idempotency"
        ),
    )
    op.create_index(
        "ix_assignment_analyses_assignment_id", "assignment_analyses", ["assignment_id"]
    )
    op.create_index("ix_assignment_analyses_status", "assignment_analyses", ["status"])
    op.create_index(
        "ix_assignment_analyses_assignment_stale",
        "assignment_analyses",
        ["assignment_id", "is_stale"],
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("specification_version", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["assignment_analyses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["triggered_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_assignment_id", "analysis_runs", ["assignment_id"])
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])
    op.create_index(
        "ix_analysis_runs_assignment_started", "analysis_runs", ["assignment_id", "started_at"]
    )
    op.create_index("ix_analysis_runs_idempotency_key", "analysis_runs", ["idempotency_key"])

    op.create_table(
        "analysis_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_by_id", sa.Uuid(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["assignment_analyses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["answered_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "code", name="uq_analysis_question_code"),
    )
    op.create_index("ix_analysis_questions_analysis_id", "analysis_questions", ["analysis_id"])
    op.create_index("ix_analysis_questions_status", "analysis_questions", ["status"])

    op.create_table(
        "analysis_classifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["assignment_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "kind", "value", "source", name="uq_analysis_classification"
        ),
    )
    op.create_index(
        "ix_analysis_classifications_analysis_id", "analysis_classifications", ["analysis_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_classifications_analysis_id", table_name="analysis_classifications")
    op.drop_table("analysis_classifications")

    op.drop_index("ix_analysis_questions_status", table_name="analysis_questions")
    op.drop_index("ix_analysis_questions_analysis_id", table_name="analysis_questions")
    op.drop_table("analysis_questions")

    op.drop_index("ix_analysis_runs_idempotency_key", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_assignment_started", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_assignment_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")

    op.drop_index("ix_assignment_analyses_assignment_stale", table_name="assignment_analyses")
    op.drop_index("ix_assignment_analyses_status", table_name="assignment_analyses")
    op.drop_index("ix_assignment_analyses_assignment_id", table_name="assignment_analyses")
    op.drop_table("assignment_analyses")
