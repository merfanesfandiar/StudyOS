# 4. Repository and module layout

Status: accepted

## Context

The suggested structure listed `app/api/`, `app/repositories/`, and `app/modules/`, with one module
per domain area.

## Decision

The domain-module layout is adopted, with three deliberate differences.

1. **No `app/api/` layer.** A separate router directory would either duplicate the module structure
   or become a pass-through that adds a hop without adding meaning. Each module keeps its own
   `router.py` and `service.py`, so a feature is read in one directory.
2. **No `app/repositories/`.** Handlers already go through a service, and the services use
   SQLAlchemy sessions with explicit query filters. A repository layer per entity would wrap ORM
   calls one to one with no second implementation behind it, which is the "excessive abstraction"
   case. If a storage-backed implementation ever appears, the service functions become that seam.
3. **`app/services/` holds cross-module helpers** that are not owned by one domain: audit recording
   and file validation.

The `packages/shared/` directory is intentionally left empty. No code is shared between the Python
API and the TypeScript web app, and an empty package would imply a build and publish pipeline that
does not exist yet.

## Consequences

- Each domain module is self-contained, and cross-module imports go through services rather than
  another module's tables.
- Backend and frontend contracts are duplicated as Pydantic schemas and TypeScript types. That is
  accepted for Phase 1: the API is the source of truth, OpenAPI documents it, and generating types
  introduces a build dependency before there is a second consumer.
- Documentation follows the suggested tree: `docs/architecture/`, `docs/api/`, `docs/development/`.
