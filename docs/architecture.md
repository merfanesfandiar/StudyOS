# Architecture

## Shape

StudyOS Phase 1 is a modular monolith: one FastAPI service and one Next.js application, plus
PostgreSQL and a filesystem volume. The backend is organized by domain module, not by technical
layer, so a feature can be read end to end in one directory.

```text
apps/api/app
  core/         settings, security, errors, logging, dependencies
  db/           engine, session, declarative base
  models/       SQLAlchemy entities and enums
  schemas/      Pydantic request and response contracts
  modules/      auth, courses, assignments, documents, dashboard, notifications
  storage/      StorageService abstraction and local implementation
  scripts/      operational scripts such as the demo seed
```

## Domain model

```text
User ──< WorkspaceMember >── Workspace ──< Course
  │                                 │            │
  │                                 └──< Assignment ──< AssignmentRequirement
  │                                                  ├──< AssignmentConstraint
  │                                                  ├──< EvaluationCriterion
  │                                                  └──< Document
  ├──< Notification
  └──< AuditLog
```

Every course, assignment, and document belongs to a workspace. Nested records (requirements,
constraints, criteria, documents) inherit tenancy from their assignment.

## Tenancy enforcement

A session cookie carries a signed JWT with the user ID. The dependency layer resolves the caller's
workspace from their memberships, and every handler filters queries by `workspace_id`. Resources are
loaded through ownership helpers, so an ID from another workspace returns 404 rather than leaking
existence. Multi-workspace selection is deliberately out of scope for Phase 1, but the dependency is
the single seam where it would be introduced.

Registration creates the user, a workspace, and an owner membership in one transaction, so a new
account is immediately usable.

## Data integrity rules

- Course codes are unique per workspace (`uq_courses_workspace_code`).
- Criterion weights are stored as `NUMERIC(5,2)` and summed server side. The API serializes
  `criteria_total` as a JSON number.
- Finalizing an assignment requires a deadline and criteria totalling exactly 100. Anything else
  returns a structured 422 (`DEADLINE_REQUIRED`, `CRITERIA_TOTAL_INVALID`).
- Deleting a course that still has assignments is rejected rather than cascading.
- Timestamps are stored as timezone-aware UTC. The frontend converts to and from `datetime-local`
  strings so students always see their own local time.

## Documents

Uploads go through `StorageService`, which today resolves to `LocalStorage`. The service interface
takes an assignment ID and a safe filename and returns a generated key; the API stores only the key,
never a user-supplied path. Downloads are streamed through an authenticated endpoint, and
`Content-Disposition` is always attachment-style so assignment documents cannot execute in the app
origin. Swapping in S3 or another backend means implementing the same interface.

## Frontend

The web app uses the Next.js App Router. The server shells render layout and static content; data
fetching happens in client components through a single typed API client that always sends
credentials. Authentication state is held in one provider that revalidates the session on load and on
route changes.

Two details worth knowing:

- `NEXT_PUBLIC_API_URL` is inlined at build time, so the Docker build receives it as a build argument.
- Submit buttons stay disabled until hydration completes. Without that, a click on a not-yet-hydrated
  button triggers a native form GET, which would put typed values, including passwords, into the URL.

## Observability and errors

Every request receives a request ID, which is returned in the `X-Request-ID` header and included in
structured JSON logs alongside method, path, status, and duration. Domain errors are raised as
`AppError` and rendered as a consistent envelope:

```json
{
  "error": {
    "code": "CRITERIA_TOTAL_INVALID",
    "message": "Evaluation criteria must total exactly 100% before finalizing an assignment.",
    "details": { "total": "80.00" }
  }
}
```

Validation failures use `VALIDATION_ERROR`, uniqueness violations surface as 409 `CONFLICT`, and
unexpected database problems return 503 `DATABASE_UNAVAILABLE` instead of leaking internals.

`/health` is a liveness check, `/ready` verifies database connectivity.

## Deployment topology

```text
browser ──> web (Next.js, port 3000) ──> api (FastAPI, port 8000) ──> postgres (5432)
                                              │
                                              └──> upload volume
```

Compose orders startup with health checks: the API waits for PostgreSQL, the web app waits for the
API, and the API runs `alembic upgrade head` before serving. Data lives in two named volumes, so
`docker compose down` preserves state and `docker compose down -v` resets it.
