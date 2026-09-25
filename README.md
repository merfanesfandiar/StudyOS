# StudyOS

StudyOS is a workspace for students who juggle multiple courses and assignment briefs. It turns a
scattered pile of PDFs and notes into one structured plan: courses, assignments, requirements,
dependencies, constraints, grading criteria, and reference documents in a single private workspace, and
it tells you when a brief is specific enough to act on.

## Features

- Email and password accounts with Argon2 hashing and HTTP-only session cookies.
- A private workspace per account, with a personal workspace created on registration.
- Courses scoped to a workspace, each with a unique code.
- Assignments linked to a course with a local-timezone deadline that is stored in UTC.
- Structured assignment specifications: requirements with hierarchy, dependencies, and a derived
  execution order, plus constraints, weighted evaluation criteria, deliverables, technologies, and tags.
- A deterministic readiness check: a score out of 100, the specific checks that are failing, and a gate
  that only opens once the deadline, requirements, and weighted criteria are in place.
- Immutable version snapshots and a human-readable activity feed, so every edit to a brief is
  attributable and reversible.
- Document attachments per assignment (PDF, DOCX, MD, TXT, ZIP, and images up to 10 MB) with private
  download URLs.
- A dashboard with upcoming deadlines, progress counts, and in-app notifications.
- Responsive, accessible UI with keyboard-friendly forms, loading states, and inline validation feedback.

## Stack

| Layer     | Technology                                                        |
| --------- | ----------------------------------------------------------------- |
| Frontend  | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4        |
| Backend   | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic                  |
| Database  | PostgreSQL 16                                                      |
| Auth      | Argon2 password hashing, JWT in an HTTP-only cookie                 |
| Storage   | Local filesystem behind a `StorageService` abstraction              |
| Testing   | pytest, Vitest, Testing Library, Playwright                          |
| Runtime   | Docker Compose                                                     |

## Quick start

Requirements: Docker with Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- App: <http://localhost:3000>
- API: <http://localhost:8000>
- OpenAPI docs: <http://localhost:8000/docs>

Migrations run automatically on API start. To load demo content after the stack is up:

```bash
docker compose run --rm api python -m app.scripts.seed
```

Demo credentials: `student@studyos.dev` / `Studyos123`.

To stop the stack and delete all data:

```bash
docker compose down -v
```

## Local development

See [docs/development/setup.md](docs/development/setup.md) for the full walkthrough. The short version:

```bash
# API
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install aiosqlite httpx mypy pytest pytest-asyncio ruff
alembic upgrade head
uvicorn app.main:app --reload

# Web
cd apps/web
npm install
npm run dev
```

PostgreSQL must be reachable. Either run `docker compose up -d db` or point `DATABASE_URL` at your own
instance. To work without a database server, set `DATABASE_URL=sqlite+aiosqlite:///./studyos.db` and run
`alembic upgrade head` as shown; the same migrations build the SQLite schema.

> Local hostnames must match. Serve the web app and call the API through the same host
> (`localhost` or `127.0.0.1`). Cookies are scoped by host and ignore ports, so mixing them produces
> a session that logs in and immediately returns 401.

## Database

PostgreSQL is the database. The schema is owned by Alembic; nothing calls `create_all()`.

```bash
cd apps/api
alembic upgrade head                       # apply migrations
alembic revision --autogenerate -m "..."   # create a migration after changing models
alembic downgrade -1                       # roll back one revision
```

`tests/test_migrations.py` applies the migration history to an empty database and asserts that the
result matches the SQLAlchemy models and can be rolled back, so a model change without a migration
fails CI.

## Quality gates

| Command                        | What it checks                     |
| ------------------------------ | ---------------------------------- |
| `pytest` (in `apps/api`)       | API behaviour, authorization, schema drift |
| `ruff check` / `mypy`          | API lint and strict type checking  |
| `npm test` (in `apps/web`)     | Frontend unit and component tests  |
| `npm run lint` / `typecheck`   | Frontend lint and TypeScript       |
| `npm run build`                | Production frontend build          |
| `npm run test:e2e`             | Playwright critical user flow      |

`npm run test:e2e` expects the API and web app to be reachable, or it starts the web app itself. See
[docs/development/setup.md](docs/development/setup.md#end-to-end-tests).

## Project layout

```text
apps/
  api/            FastAPI application, Alembic migrations, tests, seed script
  web/            Next.js application, Vitest unit tests, Playwright specs
docs/
  architecture/   Overview, data model, ADRs, future AI design
  api/            Endpoint reference
  development/    Local setup, testing, conventions
infrastructure/   Dockerfiles and container entrypoints
docker-compose.yml
```

## Configuration

Copy `.env.example` to `.env`. Every value has a working default for local development.

| Variable                        | Default                                            | Purpose                              |
| ------------------------------- | -------------------------------------------------- | ------------------------------------ |
| `ENVIRONMENT`                   | `development`                                      | Runtime environment label            |
| `DATABASE_URL`                  | `postgresql+asyncpg://studyos:studyos@db:5432/studyos` | Async SQLAlchemy URL           |
| `DATABASE_ADMIN_URL`            | `postgresql+asyncpg://studyos:studyos@db:5432/postgres` | Maintenance URL                 |
| `SECRET_KEY`                    | development placeholder                            | JWT signing key, change in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES`   | `30`                                               | Session lifetime                     |
| `CORS_ORIGINS`                  | `http://localhost:3000`                            | Comma-separated allowed origins      |
| `COOKIE_SECURE`                 | `false`                                            | Set to `true` behind HTTPS           |
| `COOKIE_NAME`                   | `studyos_session`                                  | Session cookie name                  |
| `MAX_UPLOAD_SIZE`               | `10485760`                                         | Upload ceiling in bytes              |
| `LOG_LEVEL`                     | `INFO`                                             | Log level                            |
| `SEED_DEMO_DATA`                | `false`                                            | Seed demo data on API start          |
| `NEXT_PUBLIC_API_URL`           | `http://localhost:8000/api/v1`                     | API base URL baked into the frontend |

## Documentation

- [Architecture overview and data model](docs/architecture/overview.md)
- [Architecture decisions](docs/architecture/decisions/)
- [Future AI layer design](docs/architecture/future-ai.md)
- [API reference](docs/api/reference.md)
- [Development guide](docs/development/setup.md)

## Current phase

The foundation and the structured specification are implemented. A student can register, sign in,
create a course, create an assignment, build a specification out of requirements, dependencies,
constraints, weighted criteria, deliverables, and documents, watch the readiness score respond to every
edit, mark the assignment ready for analysis, and page through the version history and activity feed,
with ownership enforced on the server for every resource.

Deliberately not implemented yet: LLM calls, agents, planning, code generation or execution, RAG
and vector storage, mastery mode, presentation generation, payment, social features, and
collaboration between students. See
[docs/architecture/future-ai.md](docs/architecture/future-ai.md) for how that layer is meant to attach
to the current domain.

## Future roadmap

- **Analysis and planning.** An analyzer agent reads a `READY_FOR_ANALYSIS` specification and produces
  a plan that stops for human approval. Introduces `ai_runs`, an orchestrator state machine, and
  approval notifications. The two analysis statuses are already reserved in the enum and are not
  client-settable, so only a run can own that transition.
- **Execution with checkpoints.** Executors run approved steps, pausing at checkpoints, with every
  step recorded as an audit event and every artifact written through `StorageService`.
- **Verification and learning.** Artifacts are evaluated against the existing
  `EvaluationCriterion` weights, then surfaced for study and presentation preparation.

Collaboration, multiple workspaces per user, and object storage remain out of scope; the seams for
each are recorded in the architecture decisions.
