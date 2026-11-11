"""Revoke stateless tokens on logout and make PlanningRun.started_at truthful.

``users.token_version`` is the revocation counter carried by every access token.
Logout bumps it, so a copied token stops authenticating immediately instead of
remaining valid until expiry.

A planning run row is created already RUNNING, and its writer always sets
``started_at`` at that moment. The column was nullable even though no valid state
has a null, so historical nulls are backfilled from ``created_at`` and the
constraint is tightened.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_token_revocation"
down_revision: str | None = "0015_fix_technical_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    # A run created before this migration may have a null started_at only if it
    # was written by an older path that violated the current writer's contract.
    # created_at is the only defensible substitute, and it is never null.
    op.execute("UPDATE planning_runs SET started_at = created_at WHERE started_at IS NULL")
    with op.batch_alter_table("planning_runs") as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("planning_runs") as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("token_version")
