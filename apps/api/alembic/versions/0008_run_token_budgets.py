"""Give a run a real token budget, and let a deleted task actually be deleted.

Two changes, both closing a gap between what a column claimed and what it did.

1. ``agent_task_executions.task_id`` was made ``ON DELETE SET NULL`` in ``0007``
   while staying ``NOT NULL``. Those cannot both hold: ``SET NULL`` on a
   non-nullable column makes the delete *fail* rather than preserve the row. The
   intent stated in ``0007`` - keep the failure history, drop the dangling
   reference - is correct and only works with a nullable column. This was not
   caught by the round-trip test because the test deletes no rows: it proves the
   schema migrates, not that the constraint permits the operation it exists for.

   The column becomes nullable. Every execution still gets a ``task_id`` while
   the task exists, because the runtime writes them together; only a deletion
   clears it, and the attempt's ``task_key`` remains on the row so the history
   stays attributable.

2. The run's token ceilings are stored rather than read from settings. The
   iteration budget alone does not bound spend - forty permitted steps of five
   thousand tokens each is not a bounded run - and ``_limits_for`` was already
   rebuilding nine of eleven limits from live settings on every resume, so a
   config reload could move a run's rules mid-flight. That contradicts the
   ``AgentLimits`` docstring, which promises a run keeps the budget it started
   with. ``max_iterations`` and ``max_cost`` were already snapshotted this way;
   the token limits join them because a budget that can change between two steps
   of the same run is not a budget.

Revision ID: 0008_run_token_budgets
Revises: 0007_schema_invariants
Create Date: 2026-01-01 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_run_token_budgets"
down_revision: str | None = "0007_schema_invariants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Defaults matching ``AgentRun``'s mapped defaults, so a new run written without
#: these columns and a run created by this migration agree.
_RUN_TOKEN_DEFAULTS = (
    ("max_tokens", 400_000),
    ("max_output_tokens_per_step", 4_000),
    ("max_input_tokens_per_step", 32_000),
)


def upgrade() -> None:
    for name, default in _RUN_TOKEN_DEFAULTS:
        op.add_column(
            "agent_runs",
            sa.Column(name, sa.Integer(), nullable=False, server_default=str(default)),
        )

    with op.batch_alter_table("agent_task_executions") as batch:
        batch.alter_column(
            "task_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    # Re-tightening task_id needs the FK cleared first: a task that was deleted
    # while the column was nullable leaves executions pointing at nothing, and
    # making the column NOT NULL with those rows still present is a constraint
    # violation. Those rows are dropped, not restored -- an execution whose task
    # no longer exists has no task to reattach to, and keeping it under a NOT NULL
    # task_id would mean inventing one.
    op.execute(
        "DELETE FROM agent_task_executions "
        "WHERE task_id IS NULL"
    )
    with op.batch_alter_table("agent_task_executions") as batch:
        batch.alter_column(
            "task_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )

    for name, _default in _RUN_TOKEN_DEFAULTS:
        op.drop_column("agent_runs", name)