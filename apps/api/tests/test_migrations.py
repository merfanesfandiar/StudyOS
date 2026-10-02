"""Schema drift guard.

The production schema is owned by Alembic, never by ``create_all``. This module applies the real
migration history to an empty database and compares the result with the SQLAlchemy metadata, so a
model change that no migration accompanies fails the test suite instead of surfacing in production.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.db.base import Base
from app.models import entities  # noqa: F401  imported so the metadata is populated
from sqlalchemy import CheckConstraint, create_engine, inspect
from sqlalchemy.engine import Engine

API_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def _migrate_to_head(database_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_file}")
    get_settings.cache_clear()
    command.upgrade(_alembic_config(), "head")
    get_settings.cache_clear()


def _sync_engine(database_file: Path) -> Engine:
    return create_engine(f"sqlite:///{database_file}")


def _migrated_tables(engine: Engine) -> set[str]:
    return {table for table in inspect(engine).get_table_names() if table != "alembic_version"}


def test_migrations_create_the_full_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_file = tmp_path / "migrated.db"
    _migrate_to_head(database_file, monkeypatch)

    engine = _sync_engine(database_file)
    assert _migrated_tables(engine) == set(Base.metadata.tables)


def test_migrations_match_model_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_file = tmp_path / "drift.db"
    _migrate_to_head(database_file, monkeypatch)

    engine = _sync_engine(database_file)
    for table_name, table in Base.metadata.tables.items():
        migrated = {column["name"] for column in inspect(engine).get_columns(table_name)}
        assert migrated == {column.name for column in table.columns}, table_name


def test_migrations_are_reversible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_file = tmp_path / "reversible.db"
    _migrate_to_head(database_file, monkeypatch)

    command.downgrade(_alembic_config(), "base")

    engine = _sync_engine(database_file)
    assert _migrated_tables(engine) == set()


def test_migrations_match_model_indexes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every index the ORM declares must exist in the migrated schema.

    The pre-Phase-5 audit found ``ix_academic_work_plans_status`` declared on the
    model but created by no migration, alongside a hand-written duplicate. The
    model therefore described two indexes on ``status`` while every real database
    had neither, and plan-level idempotency had no index at all.

    Column and type checks passed while this was true, which is why the check
    lives here rather than being folded into the existing assertions.
    """
    database_file = tmp_path / "indexes.db"
    _migrate_to_head(database_file, monkeypatch)

    inspector = inspect(_sync_engine(database_file))
    for table_name, table in Base.metadata.tables.items():
        # SQLite auto-generates indexes for UNIQUE constraints; the inspector
        # reports those under their constraint name, so compare on that basis.
        migrated = {index["name"] for index in inspector.get_indexes(table_name)}
        declared = {index.name for index in table.indexes}
        assert declared <= migrated, f"{table_name}: {sorted(declared - migrated)}"


def test_migrations_match_model_foreign_key_policies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ondelete`` is the part of a foreign key that a column comparison ignores.

    A ``CASCADE`` where the model documents ``SET NULL`` still migrates cleanly
    and still passes a column check; it only destroys history at runtime.
    """
    database_file = tmp_path / "fk.db"
    _migrate_to_head(database_file, monkeypatch)

    inspector = inspect(_sync_engine(database_file))
    for table_name, table in Base.metadata.tables.items():
        expected = {
            fk.parent.name: (fk.ondelete or "").upper()
            for fk in table.foreign_keys
            if fk.parent.name is not None
        }
        actual = {
            fk["constrained_columns"][0]: (fk.get("options", {}) or {}).get("ondelete", "").upper()
            for fk in inspector.get_foreign_keys(table_name)
        }
        for column, ondelete in expected.items():
            if column in actual:
                assert actual[column] == ondelete, f"{table_name}.{column}"


def test_timestamp_server_defaults_are_functions_not_literals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``server_default`` may be the string ``'now()'``.

    Written as a literal it becomes the *text* ``now()`` in PostgreSQL, so the
    column holds ``'now()'`` instead of a timestamp and every ordering,
    comparison and ``MAX(created_at)`` on that table is wrong. SQLite tolerates
    it, which is why the suite stayed green.
    """
    database_file = tmp_path / "defaults.db"
    _migrate_to_head(database_file, monkeypatch)

    inspector = inspect(_sync_engine(database_file))
    offenders: list[str] = []
    for table_name in inspector.get_table_names():
        if table_name == "alembic_version":
            continue
        for column in inspector.get_columns(table_name):
            default = column.get("default")
            if isinstance(default, str) and default.strip("'\"").lower() == "now()":
                offenders.append(f"{table_name}.{column['name']}")
    assert offenders == [], f"literal 'now()' server defaults: {offenders}"


def test_migrated_checks_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``CheckConstraint`` in the metadata must exist in the migrated schema.

    The naming convention is ``ck_%(table_name)s_%(constraint_name)s``, so a
    migration that passes an already-prefixed name lands in the database as
    ``ck_agent_runs_ck_agent_runs_status_valid`` while the ORM still expects
    ``ck_agent_runs_status_valid`` — invisible until a later ``downgrade`` fails
    to find the constraint it is trying to drop.
    """
    database_file = tmp_path / "checks.db"
    _migrate_to_head(database_file, monkeypatch)

    inspector = inspect(_sync_engine(database_file))
    for table_name, table in Base.metadata.tables.items():
        expected = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint) and constraint.name
        }
        if not expected:
            continue
        migrated = {item["name"] for item in inspector.get_check_constraints(table_name)}
        assert expected <= migrated, f"{table_name}: missing {sorted(expected - migrated)}"


def test_idempotency_keys_are_uniquely_constrained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every ``idempotency_key`` index must be UNIQUE.

    A non-unique index makes the ``SELECT``-then-``INSERT`` deduplication racy
    and leaves the ``IntegrityError`` handler that reads as the safety net
    unreachable, which is the worst combination: the code looks correct and the
    guarantee is absent.
    """
    database_file = tmp_path / "idempotency.db"
    _migrate_to_head(database_file, monkeypatch)

    inspector = inspect(_sync_engine(database_file))
    for table_name in ("agent_runs", "academic_work_plans", "analysis_runs", "planning_runs"):
        indexes = {index["name"]: index for index in inspector.get_indexes(table_name)}
        candidates = [
            index for name, index in indexes.items() if "idempotency" in name
        ]
        assert candidates, f"{table_name} has no idempotency index"
        assert all(index["unique"] for index in candidates), table_name
