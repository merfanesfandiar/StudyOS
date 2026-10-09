"""Allow more than one decision per iteration by making decisions a sequence.

A decision is the runtime's record of one provider round-trip. Before CALL_TOOL
existed there was exactly one decision per ``_run_step`` iteration, so the
``(run_id, iteration)`` uniqueness held. A step that calls a tool now spends
several round-trips: rebuild the context, call the tool, decide again on the
result. Those are separate decisions and can no longer share one row.

The fix is a ``slot`` column: the ordinal of the decision within its iteration.
Plain decisions use slot 0; each tool call in a step occupies the next slot. A
run's decisions stay uniquely keyed by ``(run_id, iteration, slot)``, which is
what keeps the budget auditable, while no longer conflating "one step" with
"one decision".

Revision ID: 0009_agent_decision_slot
Revises: 0008_run_token_budgets
Create Date: 2026-01-01 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_agent_decision_slot"
down_revision: str | None = "0008_run_token_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_decisions") as batch:
        batch.add_column(
            sa.Column("slot", sa.SmallInteger(), nullable=False, server_default="0")
        )
        # Existing rows were the single decision of their iteration; slot 0 is
        # exactly where they belong.
        batch.drop_constraint("uq_agent_decision_iteration", type_="unique")
        batch.create_unique_constraint(
            "uq_agent_decision_iteration_slot",
            ["run_id", "iteration", "slot"],
        )


def downgrade() -> None:
    # Dropping the slot column while the (run_id, iteration, slot) uniqueness
    # stands would leave the unique key pointing at a column that no longer
    # exists, so the constraint is rebuilt first.
    with op.batch_alter_table("agent_decisions") as batch:
        batch.drop_constraint("uq_agent_decision_iteration_slot", type_="unique")
        batch.create_unique_constraint(
            "uq_agent_decision_iteration",
            ["run_id", "iteration"],
        )
        batch.drop_column("slot")