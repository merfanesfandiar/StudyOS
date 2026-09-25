"""Phase 2: assignment intelligence and specification engine.

Normalised tables for the structured specification (requirement statuses and
stable identities, dependency edges, structured constraints, deliverables,
workspace-scoped technologies and tags, immutable specification versions) plus
the readiness columns on ``assignments``.

Every added column is created nullable, backfilled, and only then tightened to
NOT NULL. ``op.batch_alter_table`` is used on purpose: SQLite cannot ALTER a
column's nullability in place, and StudyOS supports SQLite for local development.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase2_specification"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REQUIREMENT_DEFAULT_STATUS = "TODO"


def _backfill_requirement_columns() -> None:
    """Give every pre-existing requirement a stable sequence and defaults.

    Sequence numbers are assigned per assignment in creation order, mirroring how
    ``RequirementService`` allocates them at runtime. Numbers are never reused.
    """
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, assignment_id FROM assignment_requirements"
            " ORDER BY assignment_id, created_at, id"
        )
    ).fetchall()
    counters: dict[str, int] = {}
    for requirement_id, assignment_id in rows:
        key = str(assignment_id)
        counters[key] = counters.get(key, 0) + 1
        connection.execute(
            sa.text(
                "UPDATE assignment_requirements SET sequence = :sequence, status = :status,"
                " is_required = 1, position = :position WHERE id = :id"
            ),
            {
                "sequence": counters[key],
                "status": REQUIREMENT_DEFAULT_STATUS,
                "position": counters[key],
                "id": requirement_id,
            },
        )


def _backfill_position_columns() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE assignment_constraints SET type = 'OTHER', severity = 'WARNING',"
            " position = 0 WHERE type IS NULL OR severity IS NULL OR position IS NULL"
        )
    )
    connection.execute(
        sa.text("UPDATE evaluation_criteria SET position = 0 WHERE position IS NULL")
    )
    connection.execute(
        sa.text("UPDATE assignments SET readiness_score = 0 WHERE readiness_score IS NULL")
    )
    # Requirements keep their numbers across the migration, and the high-water
    # mark must start above the highest one so no number is ever handed out
    # twice after the upgrade.
    connection.execute(
        sa.text("UPDATE assignments SET requirement_sequence = 0 WHERE requirement_sequence IS NULL")
    )
    connection.execute(
        sa.text(
            "UPDATE assignments SET requirement_sequence = COALESCE("
            "(SELECT MAX(sequence) FROM assignment_requirements"
            " WHERE assignment_requirements.assignment_id = assignments.id), 0)"
            " WHERE requirement_sequence < COALESCE("
            "(SELECT MAX(sequence) FROM assignment_requirements"
            " WHERE assignment_requirements.assignment_id = assignments.id), 0)"
        )
    )


def upgrade() -> None:
    op.create_table(
        "deliverables",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deliverables_assignment_id", "deliverables", ["assignment_id"])
    op.create_index("ix_deliverables_status", "deliverables", ["status"])
    op.create_index("ix_deliverables_position", "deliverables", ["position"])

    op.create_table(
        "technologies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "normalized_name", "version", name="uq_technology_workspace_identity"
        ),
    )
    op.create_index("ix_technologies_workspace_id", "technologies", ["workspace_id"])

    op.create_table(
        "assignment_technologies",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("technology_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["technology_id"], ["technologies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assignment_id", "technology_id"),
        sa.UniqueConstraint("assignment_id", "technology_id", name="uq_assignment_technology"),
    )
    op.create_index(
        "ix_assignment_technologies_assignment_id", "assignment_technologies", ["assignment_id"]
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("normalized_name", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "normalized_name", name="uq_tag_workspace_name"),
    )
    op.create_index("ix_tags_workspace_id", "tags", ["workspace_id"])

    op.create_table(
        "assignment_tags",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assignment_id", "tag_id"),
        sa.UniqueConstraint("assignment_id", "tag_id", name="uq_assignment_tag"),
    )
    op.create_index("ix_assignment_tags_assignment_id", "assignment_tags", ["assignment_id"])
    op.create_index("ix_assignment_tags_tag_id", "assignment_tags", ["tag_id"])

    op.create_table(
        "assignment_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("change_summary", sa.String(length=500), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "version", name="uq_assignment_version"),
    )
    op.create_index(
        "ix_assignment_versions_assignment_id", "assignment_versions", ["assignment_id"]
    )

    op.create_table(
        "requirement_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["depends_on_id"], ["assignment_requirements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["assignment_requirements.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "requirement_id", "depends_on_id", name="uq_requirement_dependency_pair"
        ),
    )
    op.create_index(
        "ix_requirement_dependencies_requirement_id", "requirement_dependencies", ["requirement_id"]
    )
    op.create_index(
        "ix_requirement_dependencies_depends_on_id", "requirement_dependencies", ["depends_on_id"]
    )

    with op.batch_alter_table("assignments") as batch:
        batch.alter_column("status", existing_type=sa.String(length=20), type_=sa.String(length=30))
        batch.add_column(sa.Column("readiness_score", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("ready_for_analysis_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("requirement_sequence", sa.Integer(), nullable=True))

    with op.batch_alter_table("assignment_requirements") as batch:
        batch.add_column(sa.Column("sequence", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("is_required", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "parent_id",
                sa.Uuid(),
                sa.ForeignKey(
                    "assignment_requirements.id", name="fk_requirement_parent", ondelete="SET NULL"
                ),
                nullable=True,
            )
        )

    with op.batch_alter_table("assignment_constraints") as batch:
        batch.add_column(sa.Column("type", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("severity", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))

    with op.batch_alter_table("evaluation_criteria") as batch:
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))

    _backfill_requirement_columns()
    _backfill_position_columns()

    with op.batch_alter_table("assignment_requirements") as batch:
        batch.alter_column("sequence", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=20), nullable=False)
        batch.alter_column("is_required", existing_type=sa.Boolean(), nullable=False)
        batch.alter_column("position", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint(
            "uq_requirement_assignment_sequence", ["assignment_id", "sequence"]
        )

    with op.batch_alter_table("assignment_constraints") as batch:
        batch.alter_column("type", existing_type=sa.String(length=30), nullable=False)
        batch.alter_column("severity", existing_type=sa.String(length=20), nullable=False)
        batch.alter_column("position", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("evaluation_criteria") as batch:
        batch.alter_column("position", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("assignments") as batch:
        batch.alter_column("readiness_score", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("requirement_sequence", existing_type=sa.Integer(), nullable=False)

    op.create_index("ix_assignment_constraints_position", "assignment_constraints", ["position"])
    op.create_index("ix_evaluation_criteria_position", "evaluation_criteria", ["position"])
    op.create_index("ix_assignment_requirements_status", "assignment_requirements", ["status"])
    op.create_index("ix_assignment_requirements_priority", "assignment_requirements", ["priority"])
    op.create_index("ix_assignments_workspace_status", "assignments", ["workspace_id", "status"])

    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(
            sa.Column(
                "assignment_id",
                sa.Uuid(),
                sa.ForeignKey(
                    "assignments.id", name="fk_audit_logs_assignment_id", ondelete="SET NULL"
                ),
                nullable=True,
            )
        )
    op.create_index("ix_audit_logs_assignment_id", "audit_logs", ["assignment_id"])

    # Phase 1's ACTIVE meant "finalized, deadline set, criteria total 100%", which is exactly what
    # Phase 2 calls READY_FOR_ANALYSIS. Nothing produces ACTIVE any more.
    op.execute(
        sa.text("UPDATE assignments SET status = 'READY_FOR_ANALYSIS' WHERE status = 'ACTIVE'")
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE assignments SET status = 'ACTIVE' WHERE status = 'READY_FOR_ANALYSIS'")
    )
    op.drop_index("ix_audit_logs_assignment_id", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("assignment_id")

    op.drop_index("ix_assignments_workspace_status", table_name="assignments")
    op.drop_index("ix_assignment_requirements_priority", table_name="assignment_requirements")
    op.drop_index("ix_assignment_requirements_status", table_name="assignment_requirements")
    op.drop_index("ix_evaluation_criteria_position", table_name="evaluation_criteria")
    op.drop_index("ix_assignment_constraints_position", table_name="assignment_constraints")

    with op.batch_alter_table("assignments") as batch:
        batch.alter_column("readiness_score", existing_type=sa.Integer(), nullable=True)
        batch.drop_column("readiness_score")
        batch.alter_column("requirement_sequence", existing_type=sa.Integer(), nullable=True)
        batch.drop_column("requirement_sequence")
        batch.drop_column("ready_for_analysis_at")
        batch.alter_column("status", existing_type=sa.String(length=30), type_=sa.String(length=20))

    with op.batch_alter_table("evaluation_criteria") as batch:
        batch.drop_column("position")

    with op.batch_alter_table("assignment_constraints") as batch:
        batch.drop_column("position")
        batch.drop_column("severity")
        batch.drop_column("type")

    with op.batch_alter_table("assignment_requirements") as batch:
        batch.drop_constraint("uq_requirement_assignment_sequence", type_="unique")
        batch.drop_column("parent_id")
        batch.drop_column("position")
        batch.drop_column("is_required")
        batch.drop_column("status")
        batch.drop_column("sequence")

    op.drop_index(
        "ix_requirement_dependencies_depends_on_id", table_name="requirement_dependencies"
    )
    op.drop_index(
        "ix_requirement_dependencies_requirement_id", table_name="requirement_dependencies"
    )
    op.drop_table("requirement_dependencies")

    op.drop_index("ix_assignment_versions_assignment_id", table_name="assignment_versions")
    op.drop_table("assignment_versions")

    op.drop_index("ix_assignment_tags_tag_id", table_name="assignment_tags")
    op.drop_index("ix_assignment_tags_assignment_id", table_name="assignment_tags")
    op.drop_table("assignment_tags")

    op.drop_index("ix_tags_workspace_id", table_name="tags")
    op.drop_table("tags")

    op.drop_index("ix_assignment_technologies_assignment_id", table_name="assignment_technologies")
    op.drop_table("assignment_technologies")

    op.drop_index("ix_technologies_workspace_id", table_name="technologies")
    op.drop_table("technologies")

    op.drop_index("ix_deliverables_position", table_name="deliverables")
    op.drop_index("ix_deliverables_status", table_name="deliverables")
    op.drop_index("ix_deliverables_assignment_id", table_name="deliverables")
    op.drop_table("deliverables")
