"""Phase 6: the Professional Agent Tool System and Specialized Workers.

Adds the durable record of every tool call a run dispatches, and the column that
names which specialized academic worker served each task attempt.

Two schema decisions worth stating:

* **Every tool call is recorded, including blocked ones.** ``agent_tool_invocations``
  keeps ``SUCCESS``, ``FAILED`` and ``BLOCKED`` rows alike. A blocked call is not a
  silent no-op to be forgotten; it is evidence of exactly what a review wants to
  count — how often the model reached for something the worker was not allowed to do.

* **``agent_task_executions.worker`` is a name, not a row.** The worker vocabulary
  lives in ``app/models/enums.py`` (``AgentWorkerKind``) and the machinery in
  ``app/modules/agent/workers.py``. The column is a plain string so a future worker
  kind cannot lock the schema; history rows written before Phase 6 stay ``NULL``
  and report themselves as "the core runtime served this", which is the truth.

The invocation row's ``task_id`` uses ``SET NULL`` like its sibling agent tables:
deleting a task must not delete the record of a call made against it, and
``task_key`` keeps the row attributable after the task is gone.

Also note what this migration does *not* add: no table holds a prohibition any
tool could argue its way around. The tool catalogue is code, not rows — there is
no way to store a new tool into the database, which is exactly the property that
keeps the tool set a reviewable code review away from a shell.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_phase6_tool_system"
down_revision: str | None = "0009_agent_decision_slot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_invocations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("task_key", sa.String(20), nullable=False),
        sa.Column("worker_kind", sa.String(30)),
        sa.Column("tool_name", sa.String(60), nullable=False),
        sa.Column("iteration", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_id"], ["plan_tasks.id"], name="fk_agent_tool_invocation_task", ondelete="SET NULL"
        ),
        sa.CheckConstraint("status IN ('SUCCESS', 'FAILED', 'BLOCKED')", name="status_valid"),
    )
    op.create_index("ix_agent_tool_invocations_run_id", "agent_tool_invocations", ["run_id"])
    op.create_index(
        "ix_agent_tool_invocations_run_status", "agent_tool_invocations", ["run_id", "status"]
    )
    op.create_index(
        "ix_agent_tool_invocations_run_tool", "agent_tool_invocations", ["run_id", "tool_name"]
    )
    op.create_index("ix_agent_tool_invocations_tool", "agent_tool_invocations", ["tool_name"])

    with op.batch_alter_table("agent_task_executions") as batch:
        batch.add_column(sa.Column("worker", sa.String(30), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_task_executions") as batch:
        batch.drop_column("worker")
    op.drop_index("ix_agent_tool_invocations_tool", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_run_tool", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_run_status", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_run_id", table_name="agent_tool_invocations")
    op.drop_table("agent_tool_invocations")