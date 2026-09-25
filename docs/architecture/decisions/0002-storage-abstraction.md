# 2. Storage service abstraction

Status: accepted

## Context

Phase 1 stores uploaded assignment documents on the local filesystem. The product will eventually
need object storage, and the assignment brief is explicit that local filesystem logic must not be
spread through the codebase.

## Decision

File access goes through a `StorageService` protocol in `app/storage/base.py`, with `LocalStorage`
as the only implementation in Phase 1. The service exposes three operations: writing a stream under
a generated key, opening a stored object for reading, and deleting a key.

Two rules make the abstraction meaningful rather than decorative:

- The caller passes an assignment ID and a safe filename; the implementation generates the storage
  key. Client-supplied paths are never accepted.
- The API stores only the generated key in the database. Filesystem layout is an implementation
  detail of the service, so a key remains resolvable after the layout changes.

## Consequences

- Switching to S3 means implementing one class and selecting it in configuration. No router, model,
  or schema changes, because no layer above the service knows where bytes live.
- Download endpoints stream through the service, so authorization is enforced on every read instead
  of relying on the storage backend to be private.
- `Content-Disposition` is always attachment-style, so an uploaded HTML or SVG payload cannot
  execute in the app origin.
- The interface is intentionally small. Features such as multipart uploads, signing, or
  server-side encryption are out of scope and should be added when a consumer exists, not
  speculatively.
