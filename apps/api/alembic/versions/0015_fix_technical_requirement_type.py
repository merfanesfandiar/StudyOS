"""Fix the misspelled TECHICAL requirement type and index audit agent runs."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_fix_technical_requirement_type"
down_revision: str | None = "0014_phase9_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The RequirementType enum shipped with a persisted value "TECHICAL" (the
    # `TECHNICAL` member's value was a typo). The Python value has been fixed;
    # any row written before this migration still carries the old spelling and
    # would fail enum parsing on read, so rewrite it in place.
    op.execute(
        "UPDATE assignment_requirements "
        "SET type = 'TECHNICAL' "
        "WHERE type = 'TECHICAL'"
    )

    # agent_run_id is the join key for every per-run audit query
    # ("what did this run cause?") but was unindexed: each such read was a
    # full table scan over the append-only audit log.
    op.create_index(
        "ix_audit_logs_agent_run_id",
        "audit_logs",
        ["agent_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_agent_run_id", table_name="audit_logs")
    # The typo repair is deliberately not reversed: the Python vocabulary now
    # only contains the correct value, so downgrading the data would break the
    # application against an older codebase that also contains the fix.
