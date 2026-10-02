"""Harden the Phase 5 schema, and the two Phase 1/5 invariants it leaned on.

Nothing here is a new feature. Each change closes a gap where the ORM declared
an intent that the database did not enforce, so the guarantee existed only in a
docstring or in a Python branch that could be raced.

1. ``fk_agent_execution_task`` cascaded. Its own class docstring says losing an
   attempt "would lose the only evidence of how the work failed, which is what
   makes the failure category and backoff policy meaningful over time", and
   three sibling columns already use ``SET NULL``. Deleting a task destroyed the
   dataset the retry logic is tuned from.

2. ``workspaces.owner_id`` cascaded. ``WorkspaceMember`` exists so people can
   share a workspace; deleting one member therefore deleted every course,
   assignment, analysis, plan, run and artifact belonging to *everyone else*.

3. Three ``idempotency_key`` columns had only a non-unique index, so the
   ``SELECT``-then-``INSERT`` used to deduplicate a double-clicked start was
   itself racy, and the ``IntegrityError`` handler that reads as the safety net
   could never fire. Partial unique constraints make the handler reachable.

4. Status columns had no ``CheckConstraint`` at all, on the columns carrying
   every state-machine invariant.

5. ``ix_academic_work_plans_status`` was declared on the model, absent from
   ``0005``, and redundant with ``ix_academic_work_plans_assignment_status``
   anyway. The model is corrected; no index is created.

Revision ID: 0007_schema_invariants
Revises: 0006_phase5_agent_runtime
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_schema_invariants"
down_revision: str | None = "0006_phase5_agent_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AGENT_RUN_STATUSES = (
    "CREATED",
    "STARTING",
    "RUNNING",
    "WAITING_FOR_USER",
    "PAUSED",
    "BLOCKED",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
_CHECKPOINT_STATUSES = ("PENDING", "RESOLVED", "CANCELLED", "EXPIRED")
_ARTIFACT_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED", "ARCHIVED")
#: ``AgentExecutionStatus`` records the *outcome* of one attempt, so a pending
#: attempt is represented by its timestamps rather than by a status value.
_EXECUTION_STATUSES = (
    "SUCCESS",
    "PARTIAL_SUCCESS",
    "FAILED",
    "BLOCKED",
    "NEEDS_USER_INPUT",
    "NEEDS_APPROVAL",
    "SKIPPED",
)
_PLAN_STATUSES = (
    "DRAFT",
    "GENERATING",
    "READY_FOR_REVIEW",
    "APPROVED",
    "IN_PROGRESS",
    "COMPLETED",
    "ARCHIVED",
    "STALE",
)


def _in(column: str, table: str, allowed: tuple[str, ...]) -> tuple[str, str]:
    """``(constraint_name, condition)`` for ``create_check_constraint``.

    Alembic's batch API takes the two parts separately rather than a
    ``CheckConstraint`` object, so this returns a pair to splat.

    The name is the *bare* suffix on purpose. ``Base.metadata`` applies
    ``ck_%(table_name)s_%(constraint_name)s``, so passing an already-prefixed
    name here produces ``ck_agent_runs_ck_agent_runs_status_valid`` in the
    database while the ORM still looks for ``ck_agent_runs_status_valid`` — and
    ``downgrade`` would then fail to find the constraint it is trying to drop.
    """
    values = ", ".join(f"'{value}'" for value in allowed)
    return f"{column}_valid", f"{column} IN ({values})"


def _index_exists(table: str, name: str) -> bool:
    """Whether *name* is currently an index on *table*.

    Needed because ``academic_work_plans.idempotency_key`` had an index declared
    on the ORM model that no migration ever created — so on a database built by
    ``alembic upgrade`` it does not exist, while on one built by
    ``Base.metadata.create_all`` it does. Dropping unconditionally fails on the
    first; skipping unconditionally leaves a redundant index on the second.
    """
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == name for index in inspector.get_indexes(table))


def _drop_index_if_present(table: str, name: str) -> None:
    if _index_exists(table, name):
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    # -- 1. Keep the failure history when a plan task is deleted ---------------
    with op.batch_alter_table("agent_task_executions") as batch:
        batch.drop_constraint("fk_agent_execution_task", type_="foreignkey")
        batch.create_foreign_key(
            "fk_agent_execution_task",
            "plan_tasks",
            ["task_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # -- 2. A shared workspace outlives any one member -------------------------
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_constraint("fk_workspaces_owner_id_users", type_="foreignkey")
        batch.create_foreign_key(
            "fk_workspaces_owner_id_users",
            "users",
            ["owner_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    # -- 3. Make the idempotency guarantee a database guarantee ---------------
    #
    # Partial, because the key is nullable and NULL is how "this caller did not
    # supply one" is represented. A plain UNIQUE would forbid more than one
    # NULL under some engines and collide on every unrelated run otherwise.
    op.create_index(
        "uq_agent_runs_idempotency_key",
        "agent_runs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_academic_work_plans_idempotency_key",
        "academic_work_plans",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_analysis_runs_idempotency_key",
        "analysis_runs",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "uq_planning_runs_idempotency_key",
        "planning_runs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    # ``planning_runs.idempotency_key`` held a *content hash* and was NOT NULL.
    # It is now the client-supplied request key, which a plain regeneration does
    # not have, so the column becomes nullable. The content hash moves to
    # ``input_fingerprint``, which is not constrained: regeneration is a
    # legitimate repeat of identical input, and a unique index there would make
    # the second regeneration of an unchanged plan fail.
    with op.batch_alter_table("planning_runs") as batch:
        batch.alter_column(
            "idempotency_key", existing_type=sa.String(length=64), nullable=True
        )
    op.add_column("planning_runs", sa.Column("input_fingerprint", sa.String(length=64), nullable=True))
    op.add_column(
        "academic_work_plans", sa.Column("input_fingerprint", sa.String(length=64), nullable=True)
    )

    # The now-redundant non-unique indexes go, so a lookup has one candidate.
    _drop_index_if_present("agent_runs", "ix_agent_runs_idempotency_key")
    _drop_index_if_present("academic_work_plans", "ix_academic_work_plans_idempotency_key")
    _drop_index_if_present("analysis_runs", "ix_analysis_runs_idempotency_key")
    _drop_index_if_present("planning_runs", "ix_planning_runs_idempotency_key")

    # -- 4. Constrain the status columns the state machines rely on -----------
    with op.batch_alter_table("agent_runs") as batch:
        batch.create_check_constraint(*_in("status", "agent_runs", _AGENT_RUN_STATUSES))
    with op.batch_alter_table("agent_task_executions") as batch:
        batch.create_check_constraint(*_in("status", "agent_task_executions", _EXECUTION_STATUSES))
    with op.batch_alter_table("agent_checkpoints") as batch:
        batch.create_check_constraint(*_in("status", "agent_checkpoints", _CHECKPOINT_STATUSES))
    with op.batch_alter_table("agent_artifacts") as batch:
        batch.create_check_constraint(*_in("status", "agent_artifacts", _ARTIFACT_STATUSES))
    with op.batch_alter_table("academic_work_plans") as batch:
        batch.create_check_constraint(*_in("status", "academic_work_plans", _PLAN_STATUSES))

    # -- 5. Attribute an artifact to the worker that produced it --------------
    #
    # Without this there is nowhere to record that a Math worker rather than
    # the core runtime drafted an artifact, which is the first thing Phase 6
    # needs and the last thing worth backfilling.
    op.add_column(
        "agent_artifacts",
        sa.Column("worker_name", sa.String(60), nullable=True),
    )
    op.create_index("ix_agent_artifacts_worker_name", "agent_artifacts", ["worker_name"])


def downgrade() -> None:
    op.drop_index("ix_agent_artifacts_worker_name", table_name="agent_artifacts")
    op.drop_column("agent_artifacts", "worker_name")
    op.drop_column("academic_work_plans", "input_fingerprint")
    op.drop_column("planning_runs", "input_fingerprint")
    with op.batch_alter_table("planning_runs") as batch:
        batch.alter_column(
            "idempotency_key", existing_type=sa.String(length=64), nullable=False
        )

    with op.batch_alter_table("academic_work_plans") as batch:
        batch.drop_constraint("status_valid", type_="check")
    with op.batch_alter_table("agent_artifacts") as batch:
        batch.drop_constraint("status_valid", type_="check")
    with op.batch_alter_table("agent_checkpoints") as batch:
        batch.drop_constraint("status_valid", type_="check")
    with op.batch_alter_table("agent_task_executions") as batch:
        batch.drop_constraint("status_valid", type_="check")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("status_valid", type_="check")

    _drop_index_if_present("planning_runs", "uq_planning_runs_idempotency_key")
    _drop_index_if_present("analysis_runs", "uq_analysis_runs_idempotency_key")
    _drop_index_if_present("academic_work_plans", "uq_academic_work_plans_idempotency_key")
    _drop_index_if_present("agent_runs", "uq_agent_runs_idempotency_key")

    op.create_index("ix_agent_runs_idempotency_key", "agent_runs", ["idempotency_key"])
    op.create_index("ix_analysis_runs_idempotency_key", "analysis_runs", ["idempotency_key"])
    op.create_index(
        "ix_academic_work_plans_idempotency_key", "academic_work_plans", ["idempotency_key"]
    )
    op.create_index("ix_planning_runs_idempotency_key", "planning_runs", ["idempotency_key"])

    with op.batch_alter_table("workspaces") as batch:
        batch.drop_constraint("fk_workspaces_owner_id_users", type_="foreignkey")
        batch.create_foreign_key(
            "fk_workspaces_owner_id_users", "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("agent_task_executions") as batch:
        batch.drop_constraint("fk_agent_execution_task", type_="foreignkey")
        batch.create_foreign_key(
            "fk_agent_execution_task", "plan_tasks", ["task_id"], ["id"], ondelete="CASCADE"
        )