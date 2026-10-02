from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _engine_kwargs() -> dict[str, object]:
    """Pool and dialect options for the configured database.

    SQLite ignores most of the pool settings, and passes unknown keys through
    to the driver, so they are only applied where they mean something. What is
    applied to *both* is ``foreign_keys``: SQLite defaults it to off, which
    silently turns every ``ON DELETE`` clause in the schema into dead code and
    means a test suite can pass against a database with no referential
    integrity at all. PostgreSQL enforces this already.
    """
    kwargs: dict[str, object] = {"pool_pre_ping": True}

    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {}
    else:
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
        )

    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs())


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
        """Turn on the referential integrity SQLite ships disabled.

        Without this, an ``AgentArtifact`` can reference a run that does not
        exist and every cascade is inert, so the suite validates a schema the
        production database does not have. Enabling it is expected to surface
        pre-existing failures; that is the point.
        """
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionFactory() as session:
        yield session