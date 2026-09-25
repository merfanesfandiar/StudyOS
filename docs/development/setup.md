# Development guide

## Prerequisites

- Python 3.12 or newer (3.13 is used in CI and Docker)
- Node.js 20.9 or newer (24 is used in CI and Docker)
- PostgreSQL 14 or newer, or Docker to run it
- Docker with Compose v2 for the full stack

## Repository layout

```text
apps/api    FastAPI service, Alembic migrations, pytest suite, seed script
apps/web    Next.js app, Vitest tests, Playwright specs
docs/       architecture (overview, ADRs, future AI), api reference, development guides
```

## Backend

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install aiosqlite httpx mypy pytest pytest-asyncio ruff
```

Configuration comes from the repository root `.env` (see `.env.example`). Copy it once:

```bash
cp ../../.env.example ../../.env
```

Run PostgreSQL and apply migrations:

```bash
docker compose up -d db
alembic upgrade head
```

Without a database server, the same migrations can build a local SQLite schema:

```bash
DATABASE_URL="sqlite+aiosqlite:///./studyos.db" alembic upgrade head
```

Migrations are always the schema source of truth; `create_all()` is never used. See
[0005-local-development-database.md](../architecture/decisions/0005-local-development-database.md).

Seed optional demo data:

```bash
python -m app.scripts.seed
```

Start the API with reload:

```bash
uvicorn app.main:app --reload
```

Interactive docs are at <http://localhost:8000/docs>.

### Creating a migration

```bash
alembic revision --autogenerate -m "add something"
```

Review the generated file before committing. Migrations are the contract with existing deployments, so
never edit a migration that has already been applied outside your own machine.

## Frontend

```bash
cd apps/web
npm install
npm run dev
```

The app is served at <http://localhost:3000>. It proxies nothing: the browser calls the API directly at
`NEXT_PUBLIC_API_URL` and sends cookies. Start the API first, and make sure `CORS_ORIGINS` includes the
frontend origin.

## Tests

Backend:

```bash
cd apps/api
pytest                      # behaviour and serialization
ruff check app tests alembic
mypy app
```

The pytest suite runs against in-memory SQLite for speed. `tests/test_migrations.py` separately
applies the real Alembic history to an empty database and compares it with the models, so migration
drift fails the suite. PostgreSQL-specific behavior is covered by the migration check in CI and by
running the stack with Compose.

Frontend:

```bash
cd apps/web
npm test                    # Vitest unit and component tests
npm run lint
npm run typecheck
npm run build
```

### End-to-end tests

The Playwright specs drive two paths:

1. The full student journey: register, create a course, create an assignment, add a requirement, a
   constraint, weighted criteria, upload a PDF, download it, read the review summary, delete the
   document, re-upload it, edit the details, finalize, confirm the assignment in the dashboard's
   upcoming deadlines, then mark it complete and confirm the completion percentage.
2. Tenant isolation: a second student signs up in a separate browser context, is refused the first
   student's assignment, and sees empty course and assignment lists.

```bash
cd apps/web
npx playwright install chromium
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1 npm run test:e2e
```

`test:e2e` starts the web app itself with a production build. The API must already be running and
reachable at `NEXT_PUBLIC_API_URL`. To run against the Compose stack instead:

```bash
SEED_DEMO_DATA=false docker compose up -d --build
cd apps/web && E2E_BASE_URL=http://127.0.0.1:3000 NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1 npm run test:e2e
```

Each run registers a new account, so the spec is safe to repeat against the same database.

## Continuous integration

`.github/workflows/ci.yml` runs three jobs on every push and pull request:

- `api`: ruff, mypy, pytest, and `alembic upgrade head` against PostgreSQL.
- `web`: install, lint, typecheck, unit tests, and a production build.
- `e2e`: builds the Compose stack, waits for API health, and runs the Playwright spec.

## Conventions

- Backend: every route handler lives in `app/modules/<domain>/router.py`, with business rules in
  `service.py` and Pydantic contracts in `app/schemas`. Handlers never query models directly.
- Backend: raise `AppError` for expected failures so responses share one shape.
- Frontend: all API access goes through `lib/api.ts`; components never call `fetch` directly.
- Frontend: use `SubmitButton` for form submission. It stays disabled until hydration completes,
  which prevents an unhydrated click from triggering a native form GET.
- Both: no secrets in code, and no manual comments explaining what the code already says.
- `apps/web/next-env.d.ts` is generated. `next dev` and `next build` rewrite its type references, so
  restore it with `git checkout apps/web/next-env.d.ts` rather than committing a dev-only variant.

## Troubleshooting

**`docker compose up` hangs on the API.** The API waits for `pg_isready`. Check `docker compose logs
db` and confirm the data volume is not owned by a different UID.

**Frontend shows network errors.** The API is not running, or `CORS_ORIGINS` does not include
`http://localhost:3000`.

**Cookie is not stored.** `COOKIE_SECURE=true` over plain HTTP makes the browser drop the cookie. Use
`https` in that case.

**Login works but every request returns 401.** The app and the API are on different hostnames. Cookies
are scoped by host and ignore ports, so `localhost:3000` talking to `127.0.0.1:8000` (or the reverse)
drops the session. Pick one host and use it in both `NEXT_PUBLIC_API_URL` and the address bar.

**E2E fails to reach the API.** The web app bakes `NEXT_PUBLIC_API_URL` in at build time, so changing
it after a build has no effect. Rebuild the app after changing the variable.
