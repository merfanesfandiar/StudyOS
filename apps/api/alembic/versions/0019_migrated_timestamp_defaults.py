"""Restore the ``now()`` server defaults the phase-10/workspace migrations dropped.

``TimestampMixin`` declares ``created_at``/``updated_at`` with
``server_default=func.now()``, so the ORM omits those columns from the INSERT and
lets the database fill them. The verification (0017) and conversations (0018)
migrations declared the columns ``NOT NULL`` *without* a default, so on any
database built from migrations — the only schema the deployment ever runs — the
first write failed with a not-null violation. PostgreSQL reports that as an
``IntegrityError``; the API maps it to a generic 409, which is how the Agent
Workspace's "New conversation" returned no conversation in CI while the
``create_all``-based test suite stayed green.

The missing defaults are applied here rather than by editing history: 0017 is
already released, and an amended 0018 would not repair databases that ran the
original. Fresh installs simply run this right after 0018.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_migrated_timestamp_defaults"
down_revision: str | None = "0018_workspace_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: table -> timestamp columns that the ORM expects the database to fill.
MISSING_DEFAULTS: dict[str, tuple[str, ...]] = {
    "verification_runs": ("created_at", "updated_at"),
    "verification_findings": ("created_at", "updated_at"),
    "verification_evidence": ("created_at", "updated_at"),
    "verification_requirement_results": ("created_at", "updated_at"),
    "verification_rubric_scores": ("created_at", "updated_at"),
    "conversations": ("created_at", "updated_at"),
    "conversation_messages": ("created_at",),
}


def _alter_defaults(default: sa.TextClause | None) -> None:
    for table_name, columns in MISSING_DEFAULTS.items():
        # Batch mode: SQLite cannot ALTER a column at all, so it recreates the
        # table from the reflected definition. Indexes and named checks are
        # carried over (the schema-drift tests assert that they are).
        with op.batch_alter_table(table_name) as batch:
            for column_name in columns:
                batch.alter_column(
                    column_name,
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    server_default=default,
                )


def upgrade() -> None:
    _alter_defaults(sa.func.now())


def downgrade() -> None:
    _alter_defaults(None)
