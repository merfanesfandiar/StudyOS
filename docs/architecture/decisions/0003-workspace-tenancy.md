# 3. Workspace tenancy and ownership checks

Status: accepted

## Context

The product context starts with one workspace per user but is expected to support collaboration and
multiple workspaces later. The security requirement is stricter: the frontend must never be the
thing that decides whether a caller may read or change a resource.

## Decision

Every course, assignment, and document belongs to a workspace. Registration creates the user, their
workspace, and an owner membership in a single transaction, so an account is usable immediately.

The rules applied everywhere:

- Handlers never accept a workspace or owner identifier from the client. The authenticated user's
  workspace is resolved from their membership by the dependency layer.
- Reads and writes are filtered by `workspace_id`. There is no "fetch by primary key and check
  afterwards" path.
- A resource belonging to another workspace returns `404`, not `403`, so the API does not confirm
  that an identifier exists.
- Nested records inherit tenancy through their assignment, so requirements, constraints, criteria,
  and documents are never looked up independently of ownership.

## Consequences

- Multi-workspace selection becomes a change in the dependency that resolves the caller's workspace,
  not a rewrite of every query. That is the reason the resolution lives in one place.
- Returning `404` for cross-tenant access costs a little debuggability and is the correct trade for
  not leaking existence.
- Deletion is asymmetric on purpose: nested specification records cascade with their assignment, but
  a course that still has assignments is rejected instead of taking the student's work with it.
- Ownership is enforced server side only. Hiding UI controls is presentation, never authorization.
