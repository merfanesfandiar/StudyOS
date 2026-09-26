# Stale analysis detection

An analysis that no longer matches the assignment specification it was computed
against is marked stale rather than silently reused.

## How it works

1. **Specification hash**: `build_analyzer_input(assignment).specification_hash`
   computes a SHA-256 of the canonical specification (requirements, constraints,
   criteria, deliverables, technologies, tags, description).
2. **On analysis request**: `mark_stale_analyses()` runs a query comparing the
   current hash against all non-stale analyses for the assignment. Any that differ
   are marked `is_stale = True`, `stale_at = now`.
3. **`is_analysis_stale()`**: Returns `True` when `analysis.is_stale` is already
   `True` or when `analysis.specification_hash != current_hash`.
4. **Client warning**: The response includes `is_stale: true` and `stale_at` so
   the UI can display a warning.
5. **Planning contract**: `PlanningContract.is_stale` is a hard signal — a stale
   contract must not be planned against silently.

## Idempotency and staleness interaction

- When an analysis is requested, stale analyses are marked stale first.
- The idempotency key includes the specification hash and prompt version, so a
  specification change naturally produces a new idempotency key.
- `force: true` forces a fresh run regardless of idempotency, deriving a distinct
  key (`sha256(base:uuid4)`) to satisfy the `UNIQUE(assignment_id, idempotency_key)`
  constraint.

## UI guidance

- Show a warning badge when `is_stale` is `true`.
- The analysis is still viewable — the student can review and accept/reject it
  before the specification changes invalidate it further.
- A stale analysis is not automatically deleted; it remains auditable.
- Only the analysis layer can mark an analysis stale; the client cannot.

## Example

```
Specification hash (old):  a1b2c3d4...
Analysis stored hash:     a1b2c3d4...  →  is_stale = false

Specification hash (new):  e5f6g7h8...  (student edited a requirement)
Analysis stored hash:     a1b2c3d4...  →  is_stale = true, stale_at = now

New analysis request:      spec_hash = e5f6g7h8...
mark_stale_analyses() marks the old analysis stale
New analysis runs with     spec_hash = e5f6g7h8...  →  is_stale = false
```