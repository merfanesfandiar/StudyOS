"""Phase 6: artifact ownership.

Adds ``agent_artifacts.ownership`` so the runtime can tell its own drafts apart
from work the student authored or uploaded. The column is the durable half of a
guard whose other half is in ``service._persist_artifact``: the runtime may only
write ``AGENT_OWNED`` rows, and a student's ``USER_OWNED`` artifact is never
mutated in place — a change is written as a new revision beside it.

The default is ``AGENT_OWNED`` because every artifact that existed before this
migration was produced by the runtime. Reporting historic rows as anything else
would credit the student with work the agent did.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_artifact_ownership"
down_revision: str | None = "0010_phase6_tool_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_artifacts") as batch:
        batch.add_column(
            sa.Column(
                "ownership",
                sa.String(20),
                nullable=False,
                server_default="AGENT_OWNED",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_artifacts") as batch:
        batch.drop_column("ownership")
