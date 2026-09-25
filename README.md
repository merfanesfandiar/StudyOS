# StudyOS

StudyOS is a workspace for students who juggle multiple courses and assignment briefs. Phase 1 turns a
scattered pile of PDFs and notes into one structured plan: courses, assignments, requirements,
constraints, grading criteria, and reference documents in a single private workspace.

## Features

- Email and password accounts with Argon2 hashing and HTTP-only session cookies.
- A private workspace per account, with a personal workspace created on registration.
- Courses scoped to a workspace, each with a unique code.
- Assignments linked to a course with a local-timezone deadline that is stored in UTC.
- Structured assignment specifications: requirements, constraints, and weighted evaluation criteria.
- Finalization rules that keep plans honest: a deadline is required and criteria must total exactly 100%.
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

Demo credentials: `student@studyos.local` / `Studyos123`.

To stop the stack and delete all data:

```bash
docker compose down -v
```

## Local development

See [docs/development.md](docs/development.md) for the full walkthrough. The short version:

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
instance.

## Quality gates

| Command                        | What it checks                     |
| ------------------------------ | ---------------------------------- |
| `pytest` (in `apps/api`)       | API behaviour and serialization    |
| `ruff check` / `mypy`          | API lint and strict type checking  |
| `npm test` (in `apps/web`)     | Frontend unit and component tests  |
| `npm run lint` / `typecheck`   | Frontend lint and TypeScript       |
| `npm run build`                | Production frontend build          |
| `npm run test:e2e`             | Playwright critical user flow      |

`npm run test:e2e` expects the API and web app to be reachable, or it starts the web app itself. See
[docs/development.md](docs/development.md#end-to-end-tests).

## Project layout

```text
apps/
  api/            FastAPI application, Alembic migrations, tests, seed script
  web/            Next.js application, Vitest unit tests, Playwright specs
docs/             Architecture, API reference, development guides
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

- [Architecture](docs/architecture.md)
- [API reference](docs/api.md)
- [Development guide](docs/development.md)

## Phase 1 scope

Deliberately excluded for now: real-time collaboration, notifications by email or push, cloud object
storage, background jobs, caching layers, and any AI features. The storage service and module layout
are designed so those can be added without reshaping the domain.
