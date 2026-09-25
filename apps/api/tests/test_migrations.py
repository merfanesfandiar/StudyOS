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
from sqlalchemy import create_engine, inspect
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
