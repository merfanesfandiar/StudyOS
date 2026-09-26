"""Phase 4: the Academic Planning Engine.

Adds the versioned work-plan tables, the generic task graph, and the per-workspace
planning preferences.

Three schema decisions are worth stating up front, because they are the ones a
reader would otherwise want to "fix":

* ``academic_work_plans.analysis_id`` is ``ON DELETE SET NULL``, not CASCADE. A
  student who deletes a stale analysis must not lose approved work. The plan
  survives and reports itself as unbacked instead.
* Task-to-requirement and task-to-deliverable links are join tables, not arrays in
  the payload. Traceability is the feature that makes a plan trustworthy, and it
  has to be queryable and enforceable rather than buried in a JSON blob.
* ``plan_task_dependencies`` cannot prevent a cycle on its own, because a cycle
  spans rows. The authority on that is the deterministic validator in
  ``app/modules/planning/graph.py``; the service refuses to persist a plan that
  has not passed it. This migration only guarantees the edges are storable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase4_planning"
down_revision: str | None = "0004_analysis_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "academic_work_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("changed_sections", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("estimated_effort", sa.String(length=20), nullable=False),
        sa.Column("min_minutes", sa.Integer(), nullable=True),
        sa.Column("max_minutes", sa.Integer(), nullable=True),
        sa.Column("is_stale", sa.Boolean(), nullable=False),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["assignment_analyses.id"],
            name="fk_academic_work_plans_analysis_id_assignment_analyses",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name="fk_academic_work_plans_approved_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.id"],
            name="fk_academic_work_plans_assignment_id_assignments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_academic_work_plans"),
        sa.UniqueConstraint(
            "assignment_id", "version", name="uq_work_plan_assignment_version"
        ),
    )
    op.create_index(
        "ix_academic_work_plans_analysis_id", "academic_work_plans", ["analysis_id"]
    )
    op.create_index(
        "ix_academic_work_plans_assignment_id", "academic_work_plans", ["assignment_id"]
    )
    op.create_index(
        "ix_academic_work_plans_assignment_status",
        "academic_work_plans",
        ["assignment_id", "status"],
    )
    op.create_index("ix_academic_work_plans_plan_status", "academic_work_plans", ["status"])

    op.create_table(
        "plan_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("estimated_effort", sa.String(length=20), nullable=False),
        sa.Column("min_minutes", sa.Integer(), nullable=True),
        sa.Column("max_minutes", sa.Integer(), nullable=True),
        sa.Column("verification_method", sa.String(length=300), nullable=True),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_user_authored", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["academic_work_plans.id"],
            name="fk_plan_tasks_plan_id_academic_work_plans",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_tasks"),
        sa.UniqueConstraint("plan_id", "key", name="uq_plan_task_plan_key"),
    )
    op.create_index("ix_plan_tasks_plan_id", "plan_tasks", ["plan_id"])
    op.create_index("ix_plan_tasks_plan_status", "plan_tasks", ["plan_id", "status"])
    op.create_index("ix_plan_tasks_type", "plan_tasks", ["type"])

    op.create_table(
        "plan_task_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_key", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["academic_work_plans.id"],
            name="fk_plan_task_requirements_plan_id_academic_work_plans",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["plan_tasks.id"],
            name="fk_plan_task_requirements_task_id_plan_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_task_requirements"),
        sa.UniqueConstraint("task_id", "requirement_key", name="uq_plan_task_requirement"),
    )
    op.create_index(
        "ix_plan_task_requirements_key",
        "plan_task_requirements",
        ["plan_id", "requirement_key"],
    )
    op.create_index("ix_plan_task_requirements_plan_id", "plan_task_requirements", ["plan_id"])
    op.create_index("ix_plan_task_requirements_task_id", "plan_task_requirements", ["task_id"])

    op.create_table(
        "plan_task_deliverables",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("deliverable_key", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["academic_work_plans.id"],
            name="fk_plan_task_deliverables_plan_id_academic_work_plans",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["plan_tasks.id"],
            name="fk_plan_task_deliverables_task_id_plan_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_task_deliverables"),
        sa.UniqueConstraint("task_id", "deliverable_key", name="uq_plan_task_deliverable"),
    )
    op.create_index(
        "ix_plan_task_deliverables_key",
        "plan_task_deliverables",
        ["plan_id", "deliverable_key"],
    )
    op.create_index("ix_plan_task_deliverables_plan_id", "plan_task_deliverables", ["plan_id"])
    op.create_index("ix_plan_task_deliverables_task_id", "plan_task_deliverables", ["task_id"])

    op.create_table(
        "plan_task_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_id", sa.Uuid(), nullable=False),
        sa.Column("successor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["academic_work_plans.id"],
            name="fk_plan_task_dependencies_plan_id_academic_work_plans",
            ondelete="CASCADE",
        ),
        # Both edges are named explicitly: they are self-referencing onto the same
        # table, and Alembic cannot infer which is which without the names.
        sa.ForeignKeyConstraint(
            ["predecessor_id"],
            ["plan_tasks.id"],
            name="fk_plan_dependency_predecessor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["successor_id"],
            ["plan_tasks.id"],
            name="fk_plan_dependency_successor",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_task_dependencies"),
        sa.UniqueConstraint("predecessor_id", "successor_id", name="uq_plan_task_dependency"),
    )
    op.create_index(
        "ix_plan_task_dependencies_plan_id", "plan_task_dependencies", ["plan_id"]
    )
    op.create_index(
        "ix_plan_task_dependencies_predecessor", "plan_task_dependencies", ["predecessor_id"]
    )
    op.create_index(
        "ix_plan_task_dependencies_successor", "plan_task_dependencies", ["successor_id"]
    )

    op.create_table(
        "plan_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["academic_work_plans.id"],
            name="fk_plan_milestones_plan_id_academic_work_plans",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_milestones"),
        sa.UniqueConstraint("plan_id", "key", name="uq_plan_milestone_plan_key"),
    )
    op.create_index("ix_plan_milestones_plan_id", "plan_milestones", ["plan_id"])

    op.create_table(
        "planning_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("model_tier", sa.String(length=20), nullable=False),
        sa.Column("routing_reason", sa.String(length=300), nullable=False),
        sa.Column("routing_confidence", sa.Float(), nullable=False),
        sa.Column("complexity", sa.String(length=20), nullable=False),
        sa.Column("fell_back_from_tier", sa.String(length=20), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("analysis_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["assignments.id"],
            name="fk_planning_runs_assignment_id_assignments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["academic_work_plans.id"],
            name="fk_planning_runs_plan_id_academic_work_plans",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_id"],
            ["users.id"],
            name="fk_planning_runs_triggered_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_planning_runs"),
    )
    op.create_index("ix_planning_runs_assignment_id", "planning_runs", ["assignment_id"])
    op.create_index(
        "ix_planning_runs_assignment_started", "planning_runs", ["assignment_id", "started_at"]
    )
    op.create_index("ix_planning_runs_idempotency_key", "planning_runs", ["idempotency_key"])
    op.create_index("ix_planning_runs_plan_id", "planning_runs", ["plan_id"])
    op.create_index("ix_planning_runs_status", "planning_runs", ["status"])

    op.create_table(
        "planning_preferences",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("planning_style", sa.String(length=20), nullable=False),
        sa.Column("guidance_level", sa.String(length=20), nullable=False),
        sa.Column("session_length", sa.String(length=20), nullable=False),
        sa.Column("ai_mode", sa.String(length=20), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_planning_preferences_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name="pk_planning_preferences"),
    )
    op.create_index(
        "ix_planning_preferences_workspace_id", "planning_preferences", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_planning_preferences_workspace_id", table_name="planning_preferences")
    op.drop_table("planning_preferences")

    op.drop_index("ix_planning_runs_status", table_name="planning_runs")
    op.drop_index("ix_planning_runs_plan_id", table_name="planning_runs")
    op.drop_index("ix_planning_runs_idempotency_key", table_name="planning_runs")
    op.drop_index("ix_planning_runs_assignment_started", table_name="planning_runs")
    op.drop_index("ix_planning_runs_assignment_id", table_name="planning_runs")
    op.drop_table("planning_runs")

    op.drop_index("ix_plan_milestones_plan_id", table_name="plan_milestones")
    op.drop_table("plan_milestones")

    op.drop_index("ix_plan_task_dependencies_successor", table_name="plan_task_dependencies")
    op.drop_index("ix_plan_task_dependencies_predecessor", table_name="plan_task_dependencies")
    op.drop_index("ix_plan_task_dependencies_plan_id", table_name="plan_task_dependencies")
    op.drop_table("plan_task_dependencies")

    op.drop_index("ix_plan_task_deliverables_task_id", table_name="plan_task_deliverables")
    op.drop_index("ix_plan_task_deliverables_plan_id", table_name="plan_task_deliverables")
    op.drop_index("ix_plan_task_deliverables_key", table_name="plan_task_deliverables")
    op.drop_table("plan_task_deliverables")

    op.drop_index("ix_plan_task_requirements_task_id", table_name="plan_task_requirements")
    op.drop_index("ix_plan_task_requirements_plan_id", table_name="plan_task_requirements")
    op.drop_index("ix_plan_task_requirements_key", table_name="plan_task_requirements")
    op.drop_table("plan_task_requirements")

    op.drop_index("ix_plan_tasks_type", table_name="plan_tasks")
    op.drop_index("ix_plan_tasks_plan_status", table_name="plan_tasks")
    op.drop_index("ix_plan_tasks_plan_id", table_name="plan_tasks")
    op.drop_table("plan_tasks")

    op.drop_index("ix_academic_work_plans_plan_status", table_name="academic_work_plans")
    op.drop_index(
        "ix_academic_work_plans_assignment_status", table_name="academic_work_plans"
    )
    op.drop_index("ix_academic_work_plans_assignment_id", table_name="academic_work_plans")
    op.drop_index("ix_academic_work_plans_analysis_id", table_name="academic_work_plans")
    op.drop_table("academic_work_plans")
