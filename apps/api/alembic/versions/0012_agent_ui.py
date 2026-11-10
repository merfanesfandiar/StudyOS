"""Phase 5+ui: structured UI envelopes for checkpoints.

Adds ``agent_checkpoints.ui`` so the runtime can attach a schema-validated
Dynamic Agent UI envelope to questions without changing the checkpoint contract
or requiring the form to own complex interactions. The payload is untrusted and
validated client-side by the web app.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_agent_ui"
down_revision: str | None = "0011_artifact_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_checkpoints") as batch:
        batch.add_column(sa.Column("ui", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_checkpoints") as batch:
        batch.drop_column("ui")
