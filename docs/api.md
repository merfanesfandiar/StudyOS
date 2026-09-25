# API reference

Base URL: `http://localhost:8000/api/v1`. The interactive OpenAPI UI is at `/docs` and the raw schema at
`/openapi.json`.

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
their memberships on every request. Multi-workspace switching is not part of Phase 1. Resources are
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
| `GET`    | `/assignments`                | List the workspace's assignments, newest first |
| `POST`   | `/assignments`                | Create a draft assignment          |
| `GET`    | `/assignments/{id}`           | Full specification, criteria total, and documents |
| `PATCH`  | `/assignments/{id}`           | Update details, deadline, course, or status |
| `POST`   | `/assignments/{id}/finalize`  | Validate and move a draft to active |

`criteria_total` is returned as a number and is recalculated on every read after a criteria change.
Finalize returns 422 with `DEADLINE_REQUIRED` or `CRITERIA_TOTAL_INVALID` when the assignment is not
ready.

### Requirements

| Method   | Path                                                   | Description |
| -------- | ------------------------------------------------------ | ----------- |
| `GET`    | `/assignments/{id}/requirements`                       | List        |
| `POST`   | `/assignments/{id}/requirements`                       | Create      |
| `PATCH`  | `/assignments/{id}/requirements/{requirement_id}`      | Update      |
| `DELETE` | `/assignments/{id}/requirements/{requirement_id}`      | Delete      |

Requirement types: `FUNCTIONAL`, `TECHNICAL`, `DESIGN`, `DOCUMENTATION`, `CONSTRAINT`, `OTHER`.
Priorities: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

### Constraints

| Method   | Path                                                | Description |
| -------- | --------------------------------------------------- | ----------- |
| `GET`    | `/assignments/{id}/constraints`                     | List        |
| `POST`   | `/assignments/{id}/constraints`                     | Create      |
| `PATCH`  | `/assignments/{id}/constraints/{constraint_id}`     | Update      |
| `DELETE` | `/assignments/{id}/constraints/{constraint_id}`     | Delete      |

### Evaluation criteria

| Method   | Path                                                 | Description |
| -------- | ---------------------------------------------------- | ----------- |
| `GET`    | `/assignments/{id}/criteria`                         | List        |
| `POST`   | `/assignments/{id}/criteria`                         | Create      |
| `PATCH`  | `/assignments/{id}/criteria/{criterion_id}`          | Update      |
| `DELETE` | `/assignments/{id}/criteria/{criterion_id}`          | Delete      |

Weights are decimals between 0 and 100, serialized as JSON numbers, and must total exactly 100 before
finalization.

## Documents

| Method   | Path                              | Description                        |
| -------- | --------------------------------- | ---------------------------------- |
| `GET`    | `/assignments/{id}/documents`     | List metadata for an assignment    |
| `POST`   | `/assignments/{id}/documents`     | Upload a file (multipart)          |
| `GET`    | `/documents/{id}/download`        | Stream a private download          |
| `DELETE` | `/assignments/{id}/documents/{id}`| Delete a document and its file     |

Accepted types: PDF, TXT, DOCX, MD, ZIP, PNG, JPG, and JPEG. Both the extension and the reported
content type must be allowed. Uploads above `MAX_UPLOAD_SIZE` are rejected with 413 `FILE_TOO_LARGE`,
and anything else with 415 `UNSUPPORTED_FILE_TYPE`. Downloads always use
`Content-Disposition: attachment`, so stored documents never execute in the app origin.

## Dashboard and notifications

| Method | Path                    | Description                                     |
| ------ | ----------------------- | ----------------------------------------------- |
| `GET`  | `/dashboard`            | Counts, completion percentage, upcoming and recent assignments |
| `GET`  | `/notifications`        | The 50 most recent notifications for the user    |
| `POST` | `/notifications/{id}/read` | Mark one notification as read                 |

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
| 404    | `*_NOT_FOUND`, `WORKSPACE_NOT_FOUND`                                       |
| 409    | `CONFLICT`, `EMAIL_ALREADY_REGISTERED`, `COURSE_CODE_EXISTS`, `COURSE_HAS_ASSIGNMENTS` |
| 413    | `FILE_TOO_LARGE`                                                           |
| 415    | `UNSUPPORTED_FILE_TYPE`                                                    |
| 422    | `VALIDATION_ERROR`, `INVALID_FILENAME`, `DEADLINE_REQUIRED`, `CRITERIA_TOTAL_INVALID` |
| 503    | `DATABASE_UNAVAILABLE`                                                     |
