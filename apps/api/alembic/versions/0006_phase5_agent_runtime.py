"""Phase 5: the Professional Agent Runtime.

Adds the durable execution tables behind an agent run: the run lifecycle, a
per-attempt execution ledger, artifacts, human checkpoints, a user-safe event
stream, and structured decisions.

The schema decisions worth stating up front are the ones a reader would
otherwise want to "fix":

* **A retried task gets a new ``agent_task_executions`` row, never an update.**
  ``(run_id, task_id, attempt)`` is unique, so every failed attempt survives.
  Overwriting the last attempt would destroy the only evidence of *how* work
  failed, which is what the retry and backoff policy is reasoned from.

* **``agent_decisions`` is unique on ``(run_id, iteration)``.** One validated
  decision per loop iteration is what makes the iteration budget auditable
  rather than approximate.

* **Events carry a per-run ``sequence``, not just a timestamp.** Several events
  are written inside one step and share a timestamp; without the counter the
  activity panel cannot be ordered deterministically.

* **Nothing here stores chain-of-thought.** ``agent_decisions.reason`` and
  ``agent_events.summary`` are concise, user-safe text written for a person.
  ``agent_task_executions.output`` holds the executor's *result*, not its
  internal reasoning.

* **The runtime has no capability columns.** There is no sandbox, no tool grant,
  no network route and no filesystem path anywhere in these tables, because the
  runtime has no such capability to grant. ``agent_artifacts.artifact_type``
  can be ``CODE``; the body is stored as text and never executed. That single
  distinction is the entire security boundary described in
  ``docs/architecture/agent-security.md``.

* **Foreign keys use ``SET NULL`` for the record-keeping ones.** Deleting a plan
  must not delete the record of work a student already did against it, so a run
  survives as an orphan and reports itself as unbacked.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase5_agent_runtime"
down_revision: str | None = "0005_phase4_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid()),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("paused_reason", sa.String(300)),
        sa.Column("error_code", sa.String(60)),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_category", sa.String(40)),
        sa.Column("model", sa.String(160)),
        sa.Column("model_tier", sa.String(20)),
        sa.Column("routing_reason", sa.String(300)),
        sa.Column("iteration_count", sa.Integer(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("max_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("token_usage", sa.JSON()),
        sa.Column("idempotency_key", sa.String(64)),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("triggered_by_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["academic_work_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["triggered_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "agent_task_executions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_key", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("executor", sa.String(30), nullable=False),
        sa.Column("model", sa.String(160)),
        sa.Column("model_tier", sa.String(20)),
        sa.Column("output", sa.JSON()),
        sa.Column("reason", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("token_usage", sa.JSON()),
        sa.Column("estimated_cost", sa.Numeric(12, 6)),
        sa.Column("failure_category", sa.String(40)),
        sa.Column("error_code", sa.String(60)),
        sa.Column("error_message", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("validation_errors", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "task_id", "attempt", name="uq_agent_execution_attempt"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["plan_tasks.id"], name="fk_agent_execution_task", ondelete="CASCADE"
        ),
    )
    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("artifact_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deliverable_key", sa.String(80)),
        sa.Column("created_by_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.UniqueConstraint("run_id", "task_id", "revision", name="uq_agent_artifact_revision"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["plan_tasks.id"], name="fk_agent_artifact_task", ondelete="SET NULL"
        ),
    )
    op.create_table(
        "agent_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("checkpoint_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text()),
        sa.Column("options", sa.JSON()),
        sa.Column("response", sa.Text()),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by_id", sa.Uuid()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["plan_tasks.id"], name="fk_agent_checkpoint_task", ondelete="SET NULL"
        ),
    )
    op.create_table(
        "agent_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("execution_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["agent_task_executions.id"],
            name="fk_agent_event_execution",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["plan_tasks.id"], name="fk_agent_event_task", ondelete="SET NULL"
        ),
        # Replay reads the log in sequence order, so two events sharing a number
        # would make the history ambiguous. Constrain it rather than trust it.
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_events_run_sequence"),
    )
    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model", sa.String(160)),
        sa.Column("model_tier", sa.String(20)),
        sa.Column("payload", sa.JSON()),
        sa.Column("outcome", sa.String(40)),
        sa.Column(
            "executed_at", sa.DateTime(timezone=True), nullable=False, server_default="now()"
        ),
        sa.UniqueConstraint("run_id", "iteration", name="uq_agent_decision_iteration"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_agent_runs_assignment_id", "agent_runs", ["assignment_id"])
    op.create_index("ix_agent_runs_assignment_status", "agent_runs", ["assignment_id", "status"])
    op.create_index("ix_agent_runs_idempotency_key", "agent_runs", ["idempotency_key"])
    op.create_index("ix_agent_runs_plan_id", "agent_runs", ["plan_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_task_executions_run_id", "agent_task_executions", ["run_id"])
    op.create_index("ix_agent_task_executions_status", "agent_task_executions", ["status"])
    op.create_index("ix_agent_task_executions_task_id", "agent_task_executions", ["task_id"])
    op.create_index("ix_agent_artifacts_run_id", "agent_artifacts", ["run_id"])
    op.create_index("ix_agent_artifacts_run_type", "agent_artifacts", ["run_id", "artifact_type"])
    op.create_index("ix_agent_checkpoints_run_id", "agent_checkpoints", ["run_id"])
    op.create_index("ix_agent_checkpoints_run_status", "agent_checkpoints", ["run_id", "status"])
    op.create_index("ix_agent_checkpoints_task_id", "agent_checkpoints", ["task_id"])
    op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])
    op.create_index("ix_agent_events_run_id_created_at", "agent_events", ["run_id", "created_at"])
    op.create_index("ix_agent_events_run_id_sequence", "agent_events", ["run_id", "sequence"])
    op.create_index("ix_agent_decisions_action", "agent_decisions", ["action"])
    op.create_index("ix_agent_decisions_run_id", "agent_decisions", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_decisions_run_id", table_name="agent_decisions")
    op.drop_index("ix_agent_decisions_action", table_name="agent_decisions")
    op.drop_table("agent_decisions")

    op.drop_index("ix_agent_events_run_id_sequence", table_name="agent_events")
    op.drop_index("ix_agent_events_run_id_created_at", table_name="agent_events")
    op.drop_index("ix_agent_events_event_type", table_name="agent_events")
    op.drop_table("agent_events")

    op.drop_index("ix_agent_checkpoints_task_id", table_name="agent_checkpoints")
    op.drop_index("ix_agent_checkpoints_run_status", table_name="agent_checkpoints")
    op.drop_index("ix_agent_checkpoints_run_id", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")

    op.drop_index("ix_agent_artifacts_run_type", table_name="agent_artifacts")
    op.drop_index("ix_agent_artifacts_run_id", table_name="agent_artifacts")
    op.drop_table("agent_artifacts")

    op.drop_index("ix_agent_task_executions_status", table_name="agent_task_executions")
    op.drop_index("ix_agent_task_executions_task_id", table_name="agent_task_executions")
    op.drop_index("ix_agent_task_executions_run_id", table_name="agent_task_executions")
    op.drop_table("agent_task_executions")

    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_plan_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_idempotency_key", table_name="agent_runs")
    op.drop_index("ix_agent_runs_assignment_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_assignment_id", table_name="agent_runs")
    op.drop_table("agent_runs")
