"""Phase 7: the secure execution environment.

Four tables record untrusted work: the job (what was asked and by whom), its
attempts (how each try actually went), the files it produced, and an append-only
event trail. A few deliberate decisions are frozen here.

*No host command is ever stored.* ``execution_type`` selects a versioned,
in-repo runtime adapter and ``options_json`` is validated against an allowlist, so
this schema cannot be coerced into running arbitrary host programs. The database
is the queue: there is no broker to lose a message into, and a job is claimed by a
compare-and-swap on ``lock_version`` exactly as the agent runtime claims runs, so a
redelivered message cannot start two sandboxes.

*Failure is data, not a string.* ``failure_class`` is a small closed vocabulary
(``COMPILATION_ERROR`` and friends). Ordinary compiler output is a normal
``FAILED`` job; only a genuine policy breach is a ``POLICY_VIOLATION_DETECTED``
event, so the two never blur into one another in reporting.

*Cleanup is tracked apart from outcome.* A run that produced the right answer but
whose container could not be reclaimed is a *cleaned failed* job, not a successful
one, because an environment that was not reclaimed is a real finding.

The idempotency key is a partial unique index (mirroring ``agent_runs``): a caller
without a key repeats freely, and a caller with one cannot start two jobs by
retrying. Large stdout/stderr live in storage behind ``stdout_ref``/``stderr_ref``;
only a bounded excerpt is kept in the row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_phase7_execution"
down_revision: str | None = "0011_artifact_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid()),
        sa.Column("agent_run_id", sa.Uuid()),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("requested_by_id", sa.Uuid()),
        sa.Column("execution_type", sa.String(30), nullable=False),
        sa.Column("backend", sa.String(20)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("resource_profile", sa.String(40), nullable=False),
        sa.Column("entrypoint", sa.String(255)),
        sa.Column("options_json", sa.JSON()),
        sa.Column("input_artifact_ids", sa.JSON()),
        sa.Column("output_artifact_ids", sa.JSON()),
        sa.Column("limits_json", sa.JSON()),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(120)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("stdout_ref", sa.String(500)),
        sa.Column("stderr_ref", sa.String(500)),
        sa.Column("result_excerpt", sa.Text()),
        sa.Column("result_json", sa.JSON()),
        sa.Column("failure_class", sa.String(40)),
        sa.Column("error_code", sa.String(60)),
        sa.Column("error_message", sa.Text()),
        sa.Column("idempotency_key", sa.String(64)),
        sa.Column("cleanup_status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_execution_jobs_workspace_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.id"],
            name="fk_execution_jobs_assignment_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], name="fk_execution_jobs_agent_run_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["plan_tasks.id"], name="fk_execution_job_task", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"], name="fk_execution_jobs_requested_by_id", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'VALIDATING', 'REJECTED', 'QUEUED', 'STARTING', "
            "'RUNNING', 'COLLECTING_RESULTS', 'SUCCEEDED', 'FAILED', 'TIMED_OUT', "
            "'CANCEL_REQUESTED', 'CANCELLED', 'RESOURCE_LIMIT_EXCEEDED', "
            "'CLEANUP_PENDING')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "cleanup_status IN ('PENDING', 'CLEANED', 'FAILED', 'SKIPPED')",
            name="cleanup_status_valid",
        ),
    )
    op.create_index("ix_execution_jobs_workspace_id", "execution_jobs", ["workspace_id"])
    op.create_index("ix_execution_jobs_assignment_id", "execution_jobs", ["assignment_id"])
    op.create_index("ix_execution_jobs_agent_run_id", "execution_jobs", ["agent_run_id"])
    op.create_index("ix_execution_jobs_status", "execution_jobs", ["status"])
    op.create_index("ix_execution_jobs_status_queued_at", "execution_jobs", ["status", "queued_at"])
    op.create_index("ix_execution_jobs_requested_by_id", "execution_jobs", ["requested_by_id"])
    op.create_index(
        "ix_execution_jobs_idempotency_key",
        "execution_jobs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "execution_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("backend", sa.String(20)),
        sa.Column("sandbox_id", sa.String(160)),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("stdout_ref", sa.String(500)),
        sa.Column("stderr_ref", sa.String(500)),
        sa.Column("stdout_excerpt", sa.Text()),
        sa.Column("stderr_excerpt", sa.Text()),
        sa.Column("diagnostics", sa.JSON()),
        sa.Column("resource_usage", sa.JSON()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("failure_class", sa.String(40)),
        sa.Column("error_code", sa.String(60)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["job_id"], ["execution_jobs.id"], name="fk_execution_attempts_job_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("job_id", "attempt", name="uq_execution_attempt"),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED', 'TIMED_OUT', 'RESOURCE_LIMIT_EXCEEDED', "
            "'CANCELLED', 'REJECTED')",
            name="status_valid",
        ),
    )
    op.create_index("ix_execution_attempts_job_id", "execution_attempts", ["job_id"])
    op.create_index("ix_execution_attempts_status", "execution_attempts", ["status"])

    op.create_table(
        "execution_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_artifact_id", sa.Uuid()),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(120)),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("ownership", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["execution_jobs.id"], name="fk_execution_artifacts_job_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["execution_attempts.id"],
            name="fk_execution_artifacts_attempt_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_execution_artifacts_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_artifact_id"],
            ["agent_artifacts.id"],
            name="fk_execution_artifacts_agent_artifact_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_execution_artifacts_job_id", "execution_artifacts", ["job_id"])
    op.create_index("ix_execution_artifacts_workspace_id", "execution_artifacts", ["workspace_id"])
    op.create_index("ix_execution_artifacts_attempt_id", "execution_artifacts", ["attempt_id"])

    op.create_table(
        "execution_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["execution_jobs.id"], name="fk_execution_events_job_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("job_id", "sequence", name="uq_execution_events_job_sequence"),
    )
    op.create_index("ix_execution_events_job_id_created_at", "execution_events", ["job_id", "created_at"])
    op.create_index("ix_execution_events_event_type", "execution_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_execution_events_event_type", table_name="execution_events")
    op.drop_index("ix_execution_events_job_id_created_at", table_name="execution_events")
    op.drop_table("execution_events")

    op.drop_index("ix_execution_artifacts_attempt_id", table_name="execution_artifacts")
    op.drop_index("ix_execution_artifacts_workspace_id", table_name="execution_artifacts")
    op.drop_index("ix_execution_artifacts_job_id", table_name="execution_artifacts")
    op.drop_table("execution_artifacts")

    op.drop_index("ix_execution_attempts_status", table_name="execution_attempts")
    op.drop_index("ix_execution_attempts_job_id", table_name="execution_attempts")
    op.drop_table("execution_attempts")

    op.drop_index("ix_execution_jobs_status_queued_at", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_idempotency_key", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_requested_by_id", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_status", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_agent_run_id", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_assignment_id", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_workspace_id", table_name="execution_jobs")
    op.drop_table("execution_jobs")
