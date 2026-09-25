# API reference

Base URL: `http://localhost:8000/api/v1`. The interactive OpenAPI UI is at `/docs` and the raw schema at
`/openapi.json`. **OpenAPI is the primary reference**; this page is the readable summary and does not
reproduce every field.

All timestamps are ISO 8601 UTC strings. All IDs are UUIDs.

## Authentication

| Method | Path      | Description                                    |
| ------ | --------- | ---------------------------------------------- |
| `POST` | `/auth/register` | Create an account, workspace, and owner membership |
| `POST` | `/auth/login`    | Start a session                                 |
| `GET`  | `/auth/me`       | Return the current user                       |
| `POST` | `/auth/logout`   | Clear the session cookie                         |

Register and login set an HTTP-only cookie named by `COOKIE_NAME`. The frontend never reads the token
directly; it calls `/auth/me` to establish a session.

`POST /auth/register` accepts `name`, `email`, and `password`. Passwords must be at least 8 characters
and contain uppercase, lowercase, and numeric characters.

## Workspaces and tenancy

The account created at registration owns a workspace, and the API resolves the caller's workspace from
their memberships on every request. Multi-workspace switching is not part of this phase. Resources are
always loaded through ownership helpers, so an ID belonging to another workspace returns 404.

## Courses

| Method   | Path            | Description                     |
| -------- | --------------- | ------------------------------- |
| `GET`    | `/courses`      | List courses with assignment counts |
| `POST`   | `/courses`      | Create a course                 |
| `GET`    | `/courses/{id}` | Fetch a course and its assignments |
| `PATCH`  | `/courses/{id}` | Update name, code, or description |
| `DELETE` | `/courses/{id}` | Delete a course with no assignments |

Course codes are unique per workspace. Deleting a course that still has assignments returns 409.

## Assignments

| Method   | Path                          | Description                        |
| -------- | ----------------------------- | ---------------------------------- |
| `GET`    | `/assignments`                | List assignments, filterable and sortable |
| `POST`   | `/assignments`                | Create a draft assignment          |
| `GET`    | `/assignments/{id}`           | Assignment row, criteria total, and documents |
| `PATCH`  | `/assignments/{id}`           | Update details, deadline, course, or client-settable status |
| `DELETE` | `/assignments/{id}`           | Delete an assignment and its stored files |

`criteria_total` is recalculated on every read after a criteria change.

`GET /assignments` accepts `page`, `page_size`, `status`, `readiness` (filter by
`READY_FOR_ANALYSIS` or `INCOMPLETE`), `tag`, `search`, `course_id`, `deadline_after`,
`deadline_before`, `sort_by` (`created_at`, `updated_at`, `deadline`, `title`, `readiness_score`;
default `updated_at`), and `sort_direction` (`asc` or `desc`; default `desc`). `search` matches the
title, description, course name and code, and attached tags. It returns a page envelope with a
`total` count, not a bare list.

### Status and lifecycle

`status` is a closed enum, never a free string: `DRAFT`, `INCOMPLETE`, `READY_FOR_ANALYSIS`,
`ANALYSIS_IN_PROGRESS`, `ANALYZED`, `COMPLETED`, `ARCHIVED`.

| From                          | To                | How                                              |
| ----------------------------- | ----------------- | ------------------------------------------------ |
| `DRAFT`                       | `INCOMPLETE`      | `POST /readiness/mark-incomplete`                |
| `READY_FOR_ANALYSIS`          | `INCOMPLETE`      | `POST /readiness/mark-incomplete`                |
| any state that passes readiness | `READY_FOR_ANALYSIS` | `POST /readiness/mark-ready`                 |
| `DRAFT`, `INCOMPLETE`, `COMPLETED`, `ARCHIVED` | `DRAFT`, `INCOMPLETE`, `COMPLETED`, `ARCHIVED` | `PATCH /assignments/{id}` |

`ANALYSIS_IN_PROGRESS` and `ANALYZED` are reserved for the later analysis phase and are not
client-settable; attempting to set one returns 422 `STATUS_NOT_CLIENT_SETTABLE`. An invalid jump
returns 422 `INVALID_STATUS_TRANSITION`. Marking an incomplete assignment ready returns 422
`ASSIGNMENT_NOT_READY`.

Readiness is a deterministic function of the specification, not a stored opinion. Breaking a blocking
check automatically demotes a ready assignment to `INCOMPLETE`; repairing it does **not** automatically
promote it, so a student always confirms readiness explicitly.

### Readiness

| Method | Path                                  | Description                       |
| ------ | ------------------------------------- | --------------------------------- |
| `GET`  | `/assignments/{id}/readiness`         | Current score, checks, and blocking problems |
| `POST` | `/assignments/{id}/validate`          | Validate without changing state   |
| `POST` | `/assignments/{id}/readiness/mark-ready` | Promote to `READY_FOR_ANALYSIS` |
| `POST` | `/assignments/{id}/readiness/mark-incomplete` | Reopen for editing        |
| `POST` | `/assignments/{id}/finalize`          | **Deprecated** alias for `mark-ready`, kept for existing clients |

`GET /readiness` and `POST /validate` return the same report: an integer `score` (0-100), a
`completeness_bar` of satisfied checks, `checks`, `failing_checks`, `warning_checks`,
`is_complete`, and `is_ready_for_analysis`. Each check carries a `field`, `label`, `status`
(`PASS`, `WARNING`, `FAIL`), a `message`, a `weight`, and a `blocking` flag. **Blocking** checks are
title, description, course, deadline, at least one requirement, and at least one evaluation criterion;
failing any of them blocks the gate. **Advisory** checks are constraints, deliverables, technologies,
and resources; failing one yields a `WARNING` and lowers the score but does not block. `POST /validate`
wraps the report in `{ is_valid, readiness, validated_at, specification_version }` and never changes
state.

### Specification

`GET /assignments/{id}/specification` is the single read the editor uses: the assignment, description,
`criteria_total`, requirements, constraints, `evaluation_criteria`, deliverables, technologies, tags,
`resources`, `readiness`, `summary`, `specification_version`, and `updated_at`, all in one payload.
`GET /assignments/{id}/summary` returns the smaller `SpecificationSummary` view (per-status requirement
counts, constraint severities, criteria balance, deliverable progress, totals) used for progress
summaries.

### Requirements

| Method   | Path                                                   | Description |
| -------- | ------------------------------------------------------ | ----------- |
| `GET`    | `/assignments/{id}/requirements`                       | List        |
| `POST`   | `/assignments/{id}/requirements`                       | Create      |
| `PATCH`  | `/assignments/{id}/requirements/{requirement_id}`      | Update      |
| `DELETE` | `/assignments/{id}/requirements/{requirement_id}`      | Delete      |

Requirement types: `FUNCTIONAL`, `TECHNICAL`, `DESIGN`, `DOCUMENTATION`, `CONSTRAINT`, `OTHER`.
Priorities: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`. Progress `status`: `TODO`, `IN_PROGRESS`, `BLOCKED`,
`COMPLETED`, `VERIFIED`.

Each requirement has a per-assignment code (`REQ-001`), an optional `parent_id` for hierarchy, and a
`code`/`title` pair. Numbers come from a high-water mark and are never reused, so deleting `REQ-002`
does not hand `REQ-002` to the next requirement. Deleting a requirement that still has children returns
409 `REQUIREMENT_HAS_CHILDREN`; a parent from another assignment returns 422 `INVALID_PARENT`;
concurrent creation returns 409 `REQUIREMENT_SEQUENCE_CONFLICT`.

### Requirement dependencies

| Method   | Path                                                                | Description |
| -------- | ------------------------------------------------------------------- | ----------- |
| `GET`    | `/assignments/{id}/requirements/dependency-graph`                    | Whole graph with execution order and cycle detection |
| `GET`    | `/assignments/{id}/requirements/{requirement_id}/dependencies`      | List        |
| `POST`   | `/assignments/{id}/requirements/{requirement_id}/dependencies`      | Link        |
| `DELETE` | `/assignments/{id}/requirements/{requirement_id}/dependencies/{dependency_id}` | Unlink |

A cycle is rejected with 422 `DEPENDENCY_CYCLE`, self-dependency with 422 `SELF_DEPENDENCY`, a repeat
link with 409 `DUPLICATE_DEPENDENCY`, and a link to another assignment's requirement with 404
`DEPENDENCY_NOT_FOUND`. The graph returns `nodes`, `edges`, `execution_order`, and `has_cycles`; an
existing cycle is reported through `has_cycles` rather than failing the whole read.

### Constraints, criteria, and deliverables

| Method   | Path                                                 | Description |
| -------- | ---------------------------------------------------- | ----------- |
| `GET`/`POST` | `/assignments/{id}/constraints`                  | List, create |
| `PATCH`/`DELETE` | `/assignments/{id}/constraints/{constraint_id}` | Update, delete |
| `GET`/`POST` | `/assignments/{id}/criteria`                     | List, create |
| `PATCH`/`DELETE` | `/assignments/{id}/criteria/{criterion_id}`     | Update, delete |
| `GET`/`POST` | `/assignments/{id}/deliverables`                 | List, create |
| `PATCH`/`DELETE` | `/assignments/{id}/deliverables/{deliverable_id}` | Update, delete |

Criterion weights are decimal strings (for example `"25.50"`) and must total exactly 100 before the
assignment can be marked ready. Weights that are out of range return 422 `INVALID_WEIGHT`, and weights
with more than two decimal places return 422 `INVALID_WEIGHT_PRECISION`. Titles are unique per
assignment, so duplicates return 409 `DUPLICATE_CONSTRAINT_TITLE`, `DUPLICATE_CRITERION_TITLE`, or
`DUPLICATE_DELIVERABLE_TITLE`.

Constraint types: `TECHNOLOGY`, `TIME`, `RESOURCE`, `FORMAT`, `LANGUAGE`, `LIBRARY`, `PLATFORM`,
`ACADEMIC`, `SECURITY`, `PERFORMANCE`, `OTHER`. Severities: `INFO`, `WARNING`, `IMPORTANT`, `CRITICAL`.
Deliverable types: `SOURCE_CODE`, `DOCUMENT`, `DATASET`, `PRESENTATION`, `TEST_SUITE`, `VIDEO`, `OTHER`;
statuses: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `VERIFIED`.

### Technologies and tags

Technologies and tags are workspace-scoped catalogues; linking one to an assignment creates the
catalogue entry if it does not exist.

| Method   | Path                                             | Description |
| -------- | ------------------------------------------------ | ----------- |
| `GET`    | `/workspaces/{workspace_id}/technologies`        | List catalogue |
| `GET`/`POST` | `/assignments/{id}/technologies`             | List, link (create or reuse) |
| `DELETE` | `/assignments/{id}/technologies/{technology_id}` | Unlink |
| `GET`    | `/workspaces/{workspace_id}/tags`                | List catalogue |
| `GET`/`POST` | `/assignments/{id}/tags`                     | List, link |
| `DELETE` | `/assignments/{id}/tags/{tag_id}`               | Unlink |

Names are compared case-insensitively, and a catalogue entry is keyed by normalized name *and* version.
Re-linking an existing assignment technology returns 409 `TECHNOLOGY_ALREADY_LINKED` (409
`TAG_ALREADY_LINKED` for tags). If two requests race to create the same catalogue entry, the loser gets
409 `TECHNOLOGY_CONFLICT` or `TAG_CONFLICT` and can retry.

### Documents

| Method   | Path                              | Description                        |
| -------- | --------------------------------- | ---------------------------------- |
| `GET`    | `/assignments/{id}/documents`     | List metadata for an assignment    |
| `POST`   | `/assignments/{id}/documents`     | Upload a file (multipart)          |
| `GET`    | `/documents/{id}`                 | Fetch metadata                     |
| `GET`    | `/documents/{id}/download`        | Stream a private download          |
| `DELETE` | `/documents/{id}`                 | Delete a document and its file     |

Accepted types: PDF, TXT, DOCX, MD, ZIP, PNG, JPG, and JPEG. Both the extension and the reported
content type must be allowed. Uploads above `MAX_UPLOAD_SIZE` are rejected with 413 `FILE_TOO_LARGE`,
and anything else with 415 `UNSUPPORTED_FILE_TYPE`. Downloads always use
`Content-Disposition: attachment`, so stored documents never execute in the app origin.

Documents take part in the readiness checklist, so uploading or deleting one is recorded as a
specification change: it moves the readiness score, appears in the activity feed, and takes a new
version snapshot.

### Versions and activity

| Method | Path                                | Description                        |
| ------ | ----------------------------------- | ---------------------------------- |
| `GET`  | `/assignments/{id}/versions`        | Paginated snapshot list            |
| `GET`  | `/assignments/{id}/versions/{n}`    | One immutable snapshot             |
| `GET`  | `/assignments/{id}/activity`        | Paginated change feed              |

A snapshot is taken on every specification change and is never modified. Versions are ordered newest
first with a stable tiebreaker, so paging cannot repeat or skip an entry. Each activity event carries a
human-readable `change_summary` (for example `Added requirement REQ-001` or
`Deleted assignment-brief.pdf`) plus its `event_type` and entity, so the UI never has to infer what
changed from timestamps. Both endpoints accept `page`, `page_size`, and `event_type` on activity.

## Dashboard and notifications

| Method | Path                    | Description                                     |
| ------ | ----------------------- | ----------------------------------------------- |
| `GET`  | `/dashboard`            | Counts, readiness breakdown, average readiness, upcoming and recent assignments |
| `GET`  | `/notifications`        | The 50 most recent notifications for the user    |
| `POST` | `/notifications/{id}/read` | Mark one notification as read                 |

The dashboard reports `in_progress_assignments_count`, `ready_assignments_count`,
`incomplete_assignments_count`, and `average_readiness_score` alongside the assignment rows, which
themselves carry `readiness_score` and readiness-derived progress.

## Operational endpoints

| Method | Path     | Description                                |
| ------ | -------- | ------------------------------------------ |
| `GET`  | `/health` | Liveness                                  |
| `GET`  | `/ready`  | Readiness, verifies database connectivity |

## Errors

Every error uses the same shape:

```json
{ "error": { "code": "COURSE_NOT_FOUND", "message": "Course not found." } }
```

| Status | Codes                                                                    |
| ------ | ------------------------------------------------------------------------ |
| 401    | `AUTHENTICATION_REQUIRED`, `INVALID_CREDENTIALS`, `INVALID_TOKEN`           |
| 404    | `*_NOT_FOUND`, `WORKSPACE_NOT_FOUND`, `DEPENDENCY_NOT_FOUND`               |
| 409    | `CONFLICT`, `EMAIL_ALREADY_REGISTERED`, `COURSE_CODE_EXISTS`, `COURSE_HAS_ASSIGNMENTS`, `DUPLICATE_*`, `REQUIREMENT_HAS_CHILDREN`, `REQUIREMENT_SEQUENCE_CONFLICT`, `*_ALREADY_LINKED`, `*_CONFLICT` |
| 413    | `FILE_TOO_LARGE`                                                           |
| 415    | `UNSUPPORTED_FILE_TYPE`                                                    |
| 422    | `VALIDATION_ERROR`, `INVALID_FILENAME`, `INVALID_WEIGHT`, `INVALID_WEIGHT_PRECISION`, `CRITERIA_TOTAL_INVALID`, `ASSIGNMENT_NOT_READY`, `INVALID_STATUS_TRANSITION`, `STATUS_NOT_CLIENT_SETTABLE`, `DEPENDENCY_CYCLE`, `SELF_DEPENDENCY`, `INVALID_PARENT`, `TIMEZONE_REQUIRED` |
| 503    | `DATABASE_UNAVAILABLE`                                                     |
