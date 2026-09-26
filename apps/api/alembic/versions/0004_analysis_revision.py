"""Phase 3 fix: a monotonic revision so "the latest analysis" is well defined.

``created_at`` alone cannot order analyses. ``TimestampMixin.created_at`` uses
``server_default=func.now()``, which has one-second resolution on SQLite, so two
analyses of the same assignment created within the same second tie and the
"newest" one is chosen arbitrarily. That made ``GET /assignments/{id}/analysis``
return an older analysis after a forced re-analysis.

``revision`` is a per-assignment counter starting at 1. Existing rows are
backfilled with their row order within each assignment, so the column is
immediately consistent and needs no nullable state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_analysis_revision"
down_revision: str | None = "0003_phase3_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "assignment_analyses"


def upgrade() -> None:
    # Added NOT NULL together with a server default, so existing rows are valid
    # immediately and SQLite never needs an ALTER COLUMN (it cannot do one).
    op.add_column(
        TABLE,
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )

    # Backfill per assignment, oldest first, so the ordering matches the order the
    # rows were actually created in. ROW_NUMBER is portable across SQLite and
    # PostgreSQL; among rows sharing an identical `created_at` second the tie order
    # is unspecified, which only affects the cosmetic revision number of historical
    # rows. Every row inserted after this migration gets an exact value.
    op.execute(
        sa.text(
            f"""
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY assignment_id ORDER BY created_at
                ) AS position
                FROM {TABLE}
            )
            UPDATE {TABLE} AS target
            SET revision = (
                SELECT position FROM ranked WHERE ranked.id = target.id
            )
            """
        )
    )

    op.create_index(
        "ix_assignment_analyses_assignment_revision",
        TABLE,
        ["assignment_id", "revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_assignment_analyses_assignment_revision", table_name=TABLE)
    op.drop_column(TABLE, "revision")
