from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

#: Stable constraint naming so Alembic can drop and re-create constraints
#: (including the Phase 2 self-referencing foreign keys) instead of guessing.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every ORM model.

    ``eager_defaults`` makes INSERT and UPDATE fetch server-generated columns
    (``created_at``/``updated_at``) in the same statement. Without it those
    attributes stay expired, and reading them from synchronous code - the
    Pydantic mappers that build specification snapshots - would raise
    ``MissingGreenlet`` instead of returning the value the database generated.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    __mapper_args__: dict[str, object] = {"eager_defaults": True}
