# 5. Local development database

Status: accepted

## Context

PostgreSQL is the database for the application, and the shipped migrations target it. Requiring a
running PostgreSQL server before a contributor can run a single test would make the feedback loop
slow, and the repository had no local database available on the development machine.

## Decision

PostgreSQL remains the only supported application database. Alembic is the only schema management
mechanism: the application, the seed script, and the documentation never call `create_all()`.

For local development without a database server, the same Alembic migrations are run against SQLite
by pointing `DATABASE_URL` at a file. The migration is written to render on both dialects, so the
local schema is produced by migrations rather than by a separate code path. This is a developer
convenience, not a deployment target.

The pytest suite is the one exception, and it is deliberate: API tests build an isolated in-memory
database with `create_all` because each test needs a fresh schema in milliseconds. That is test
scaffolding, not schema management, and it is not trusted: `tests/test_migrations.py` applies the
real migration history to an empty database and asserts that the result matches the SQLAlchemy
metadata and can be downgraded, so drift between models and migrations fails the suite.

## Consequences

- A local SQLite database and the Docker PostgreSQL database are the same schema, so a migration
  that passes locally is meaningful. Writing a second, divergent schema definition would defeat the
  purpose.
- The dialect-specific column types in the schema are limited to what both engines render
  equivalently; anything genuinely PostgreSQL-specific belongs in a later migration guarded by
  dialect, not in the initial one.
- Local SQLite testing does not prove PostgreSQL behaviour. Connection pooling, `JSONB` operators, and
  concurrent writes are verified by the Compose stack and CI, not by the local file database.
- `docker compose up` remains the supported way to run against PostgreSQL, and the CI database
  service always uses PostgreSQL.
