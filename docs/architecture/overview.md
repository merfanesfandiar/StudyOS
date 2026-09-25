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
  services/     cross-module helpers (audit, file validation, events)
  scripts/      operational scripts such as the demo seed
```

Deviations from the originally suggested layout, and why, are recorded in
[decisions/0004-repository-layout.md](decisions/0004-repository-layout.md).

## Domain model

```mermaid
erDiagram
    User ||--o{ WorkspaceMember : "joins"
    User ||--o{ Workspace : owns
    Workspace ||--o{ WorkspaceMember : has
    Workspace ||--o{ Course : contains
    Workspace ||--o{ Assignment : contains
    User ||--o{ Notification : receives
    User ||--o{ AuditLog : acts
    Course ||--o{ Assignment : "has (RESTRICT on delete)"
    Assignment ||--o{ AssignmentRequirement : "has (CASCADE)"
    Assignment ||--o{ AssignmentConstraint : "has (CASCADE)"
    Assignment ||--o{ EvaluationCriterion : "has (CASCADE)"
    Assignment ||--o{ Document : "has (CASCADE)"

    User {
        uuid id PK
        string name
        string email UK
        string password_hash
        timestamptz created_at
        timestamptz updated_at
    }
    Workspace {
        uuid id PK
        string name
        uuid owner_id FK
    }
    WorkspaceMember {
        uuid workspace_id PK,FK
        uuid user_id PK,FK
        string role
    }
    Course {
        uuid id PK
        uuid workspace_id FK
        string name
        string code
        text description
    }
    Assignment {
        uuid id PK
        uuid workspace_id FK
        uuid course_id FK
        string title
        text description
        timestamptz deadline
        string status
    }
    AssignmentRequirement {
        uuid id PK
        uuid assignment_id FK
        string title
        string priority
        string type
    }
    AssignmentConstraint {
        uuid id PK
        uuid assignment_id FK
        string title
        text description
        string value
    }
    EvaluationCriterion {
        uuid id PK
        uuid assignment_id FK
        string title
        numeric weight
    }
    Document {
        uuid id PK
        uuid assignment_id FK
        string filename
        string storage_key UK
        string mime_type
        integer size
    }
    Notification {
        uuid id PK
        uuid user_id FK
        string type
        string title
        text message
        timestamptz read_at
        timestamptz created_at
    }
    AuditLog {
        uuid id PK
        uuid user_id FK
        uuid workspace_id FK
        string event_type
        string entity_type
        uuid entity_id
        json metadata_json
        timestamptz created_at
    }
```

Every course, assignment, and document belongs to a workspace. Nested records (requirements,
constraints, criteria, documents) inherit tenancy from their assignment.

Deletion behaviour is deliberate and asymmetric: nested specification records cascade with their
assignment, but a course with assignments is rejected (`RESTRICT`) rather than silently taking the
student's work with it. Audit rows are detached, not deleted, when their user or workspace is
removed.

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
  returns a structured 422 (`DEADLINE_REQUIRED`, `CRITERIA_TOTAL_INVALID`). The rule guards the
  `ACTIVE` state specifically, so drafts stay freely editable and unfinished work can still be
  archived.
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

## Future phases

Phase 1 deliberately contains no AI code. The seams that later phases plug into are already in place:
domain modules own their write paths, `services/audit.py` records state changes, `StorageService`
isolates file IO, and `Notification` plus `AuditEventType` define the vocabulary a future engine can
publish. How that engine is expected to attach is described in [future-ai.md](future-ai.md).

## Decisions

Architecture decision records live next to this file:

- [0001 Cookie-based session authentication](decisions/0001-cookie-session-auth.md)
- [0002 Storage service abstraction](decisions/0002-storage-abstraction.md)
- [0003 Workspace tenancy and ownership checks](decisions/0003-workspace-tenancy.md)
- [0004 Repository layout](decisions/0004-repository-layout.md)
- [0005 Local development database](decisions/0005-local-development-database.md)
