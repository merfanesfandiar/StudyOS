"""Phase 10: verification runs, findings, evidence, requirement results, rubric scores.

Five tables back the Academic Verification Engine:

* ``verification_runs`` — one pipeline execution, tenant-scoped, idempotency-
  keyed per assignment, with an aggregated verdict and bounded summary JSON.
* ``verification_findings`` — per-validator findings with severity and
  traceability to requirements/artifacts.
* ``verification_evidence`` — method-labelled evidence records (deterministic,
  tool-assisted, external). AI explanations never qualify.
* ``verification_requirement_results`` — per-requirement verdicts.
* ``verification_rubric_scores`` — per-criterion estimated scores (never
  instructor grades).

All children cascade from their run; requirement and criterion references use
RESTRICT-free cascade from their own side so deleting an assignment removes
everything consistently.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_phase10_verification"
down_revision: str | None = "0016_token_revocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("previous_run_id", sa.Uuid(), nullable=True),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("scope_kind", sa.String(length=20), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=True),
        sa.Column("completion_percentage", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_verification_runs_status",
        ),
        sa.CheckConstraint(
            "scope_kind IN ('FULL','PARTIAL','ARTIFACT','REQUIREMENT','RE_VERIFICATION')",
            name="ck_verification_runs_scope_kind",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["previous_run_id"], ["verification_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "idempotency_key", name="uq_verification_run_idempotency"),
    )
    op.create_index("ix_verification_runs_assignment_id", "verification_runs", ["assignment_id"])
    op.create_index("ix_verification_runs_workspace_id", "verification_runs", ["workspace_id"])
    op.create_index(
        "ix_verification_runs_assignment_status", "verification_runs", ["assignment_id", "status"]
    )
    op.create_index("ix_verification_runs_created_at", "verification_runs", ["created_at"])
    op.create_index("ix_verification_runs_status", "verification_runs", ["status"])

    op.create_table(
        "verification_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("validator_name", sa.String(length=80), nullable=False),
        sa.Column("validator_version", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("requirement_codes", sa.JSON(), nullable=True),
        sa.Column("artifact_ids", sa.JSON(), nullable=True),
        sa.Column("heuristic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["verification_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_findings_run_id", "verification_findings", ["run_id"])
    op.create_index(
        "ix_verification_findings_run_severity", "verification_findings", ["run_id", "severity"]
    )

    op.create_table(
        "verification_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("validator_name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("artifact_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["verification_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_evidence_run_id", "verification_evidence", ["run_id"])
    op.create_index("ix_verification_evidence_run_kind", "verification_evidence", ["run_id", "kind"])

    op.create_table(
        "verification_requirement_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_code", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["verification_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["assignment_requirements.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "requirement_id", name="uq_verification_req_result"),
    )
    op.create_index(
        "ix_verification_req_results_run_id", "verification_requirement_results", ["run_id"]
    )
    op.create_index(
        "ix_verification_req_results_requirement_id",
        "verification_requirement_results",
        ["requirement_id"],
    )

    op.create_table(
        "verification_rubric_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("criterion_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("improvement", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["verification_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["criterion_id"], ["evaluation_criteria.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "criterion_id", name="uq_verification_rubric_score"),
    )
    op.create_index(
        "ix_verification_rubric_scores_run_id", "verification_rubric_scores", ["run_id"]
    )


def downgrade() -> None:
    op.drop_table("verification_rubric_scores")
    op.drop_table("verification_requirement_results")
    op.drop_table("verification_evidence")
    op.drop_table("verification_findings")
    op.drop_index("ix_verification_runs_created_at", table_name="verification_runs")
    op.drop_index("ix_verification_runs_status", table_name="verification_runs")
    op.drop_index(
        "ix_verification_runs_assignment_status", table_name="verification_runs"
    )
    op.drop_index("ix_verification_runs_workspace_id", table_name="verification_runs")
    op.drop_index("ix_verification_runs_assignment_id", table_name="verification_runs")
    op.drop_table("verification_runs")
