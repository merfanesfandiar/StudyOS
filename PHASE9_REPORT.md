# Phase 8 & 9: Human Oversight and Agent Observability — Final Report

## Summary

Phase 8 made the agent's risky operations conditional on a durable human decision: an
operation is proposed, a person answers, and only an approval authorises execution.
Phase 9 made the whole agent observable while it does that: structured, correlatable
events from the real execution path, a separate append-only security audit trail,
cost accounting with named pricing, operational signals, and a documented
runbook — with no new infrastructure dependencies.

## What was built

### Phase 8: durable HITL interactions

- `AgentInteraction` / `AgentInteractionResponse` (migration `0013_phase8_interactions`):
  a proposed operation, its risk level, its **operation binding** (what exactly an approval
  authorises), the UI presentation contract, and an immutable decision history.
- Lifecycle state machine: `PENDING → ACCEPTED | REJECTED | EXPIRED | CANCELLED`. A rejection
  or revision never resumes execution; the router executes `execute_run` **only** when
  `interaction.status == ACCEPTED` after the response is committed. Expiry is checked at
  response time and fails closed (`AGENT_INTERACTION_EXPIRED`) — an expired request can never
  double as consent.
- Decision history is immutable: a resolved interaction refuses further responses with 409,
  and every response snapshots the operation binding at decision time.
- The runtime pauses on `WAITING_FOR_USER`; interaction creation/resolution emits run events
  on CREATED runs too, so the lifecycle is visible before execution starts.

### Phase 9: observability from the real execution path

- **Instrumentation is not manual.** `_append_event` now stamps every event with
  `assignment_id`, `workspace_id`, `correlation/causation/trace/span` ids, `severity`,
  `source_component`, `outcome`, `duration_ms`, and `schema_version` (currently 1). The agent
  execute loop emits `LLM_REQUEST_STARTED / COMPLETED / FAILED` around each real
  `provider.complete` call, carrying token usage, model, latency, and estimated cost — so
  model instrumentation reflects what actually ran.
- **Redaction everywhere.** All persisted `metadata_json` and audit payloads pass through
  `redact_dict`, which masks password/token/secret/api_key keys at any depth and truncates
  oversized strings. Chain-of-thought is never persisted; only the structured `AgentAction`
  and provider metadata are.
- **Two ledgers, kept apart.** Operational telemetry lives in `agent_events`; security audit
  rows in `audit_logs` (append-only). New audit types
  `AGENT_INTERACTION_REQUESTED / RESOLVED / EXPIRED / CANCELLED` make every approval
  attributable. `record_audit_event` was rewritten to a single direct INSERT — the previous
  implementation read back the globally-latest audit row and mutated it, which was both racy
  and able to corrupt a concurrent request's record.
- **Authorization.** Every observability endpoint resolves ownership through
  `load_owned_run`, returning 404 — never 403 with details — for foreign ids, matching the
  product-wide convention.
- **Pagination.** `/events` is cursor-paged on `sequence` with limits; the cursor is only
  advertised when a further page actually exists (the router fetches limit+1 rows).
- **Cost accounting.** `/usage` distinguishes estimate from billed usage (`cost_source`),
  names the `pricing_version` (`2026-10`), and reports `usage_available: false` rather than
  silently treating missing usage as zero spend.
- **Signals** (`observability/signals.py`): stalled-running-run detection (no fresh event for
  15 minutes), failure bursts (>= 10 ERROR events/60 min/run), and cost outliers — computed
  from the existing tables at request time, Kafka-free.
- **Operator surface.** `GET .../signals` is scoped to one workspace and restricted to its
  OWNER role (the strongest authority that exists in this product; there is no global admin).

## The API

| Endpoint | Notes |
|---|---|
| `GET /api/v1/assignments/{aid}/agent/runs/{rid}/events` | Cursor-paged structured stream |
| `GET .../timeline` | Ordered full history, bounded |
| `GET .../usage` | Tokens, cost, model, pricing version |
| `GET .../artifacts/{aid}/provenance` | The events that produced a draft |
| `GET .../signals` | Workspace signals, owner-only |
| `POST .../interactions`, `.../respond`, `.../approve`, `.../reject`, `.../cancel`, `GET .../history` | Phase 8 decision endpoints |

## Quality gate verification

All commands were actually run in this session; none are claimed without output:

- `python -m pytest -q` (apps/api): **515 passed, 1 skipped**, no failures
  (was 498 before this work; +7 interaction tests, +10 observability tests, +0 removed).
  - `tests/test_interactions_api.py`: create/read-back, accept vs. reject-no-resume,
    expiry fails closed, cancel blocks later approval, unknown action 422, cross-user 404,
    events recorded — 7/7 passing.
  - `tests/test_observability_api.py`: owner-readable events, cursor paging (no empty
    trailing pages), timeline/usage owner-only 404s, artifact provenance incl. unknown
    artifact 404, redaction unit tests, failure classification, cost estimation, stalled-run
    signal, workspace scoping — 10/10 passing.
- `python -m alembic upgrade head` from an empty scratch SQLite database: the full chain
  `… → 0012_agent_ui → 0012_phase7_execution → 0013_phase8_interactions →
  0014_phase9_observability` upgrades cleanly; new columns and indexes verified via
  `PRAGMA table_info` afterwards.
- `npx tsc --noEmit` (apps/web): clean.
- `npx vitest run`: **13 files, 190 tests passed**.
- `npx next build`: succeeded (all routes compiled).

## Defects found and fixed during this phase

1. **Racy audit writer.** `record_audit_event` updated "the latest `audit_logs` row" — i.e.
   possibly someone else's just-inserted record under concurrency. Rewritten to a single
   INSERT with every field set in one statement.
2. **`MissingGreenlet` serialization crash.** Validating `AgentInteraction` with lazy-loaded
   `responses` under asyncio raised `MissingGreenlet`. Fixed with an eager-loading fetch
   helper (`get_interaction_with_responses`, `selectinload`) used by every serialising path,
   plus explicit `interaction.responses.append(resp)` so the pending decision is visible in
   the same flush.
3. **Reject-resumed-execution bug.** The respond/approve endpoints ran `execute_run`
   regardless of the decision and swallowed failures with a bare `except Exception`. Both
   removed: execution only follows an ACCEPTED status check on the committed interaction.
4. **Naive/aware datetime crash.** SQLite stores datetimes naive; comparing
   `interaction.expires_at` with UTC `now()` raised `TypeError`. Added `_coerce_aware` on
   every comparison path, including expiry sweep.
5. **Phantom cursor.** Advancing past the last event returned an empty page and a cursor.
   Fixed by fetching one extra row and advertising a cursor only when more rows exist.
6. **Swallowed observability router.** `app/main.py` wrapped the router import in
   `try/except Exception: pass`, which would have silently dropped the entire Phase 9 API if
   the import ever failed. Made unconditional.

## Honest gaps (not hidden)

- **Outbox / exactly-once publishing is not implemented.** Events and audit rows commit in the
  same transaction as the state change, which is atomic, but there is no outbox worker for
  downstream side effects. At present no consumer exists to miss them.
- **Tamper-evidence is application-level only.** Append-only is enforced by the application;
  there is no hash chain, WORM store, or external notarisation. A database-level attacker can
  delete rows. This is documented, not solved.
- **Cost is estimate-only.** No invoice/billing integration; "billed" costs do not exist, and
  `cost_source` never claims otherwise.
- **No global admin role.** The operator signals endpoint uses the workspace-OWNER role. A
  cross-workspace fleet dashboard would require a new authority concept and is out of scope.
- **No push alerting.** Signals are pull-based at request time; a paging system would need
  exactly the infrastructure the phase declined to add.
- **No independent retention/purge job.** Events cascade with their run; long-horizon
  archival to cold storage is future work.
- **`docs/api/reference.md` still covers the Phase 3 analysis API.** Later phases (including
  this one) are documented in `docs/architecture/agent-observability.md` and the phase-specific
  docs instead; the reference file has not been kept current and this is stated explicitly.

## Files changed / added (this phase)

- `apps/api/app/modules/observability/` — `service.py` (redaction, correlation, failure
  classifier, cost calculator, `record_event`, single-INSERT `record_audit_event`),
  `router.py` (events/timeline/usage/provenance/signals), `signals.py` (stalled runs,
  failure bursts, cost outliers).
- `apps/api/app/modules/agent/service.py` — structured `_append_event`, LLM call
  instrumentation in the execute loop.
- `apps/api/app/modules/agent/interactions.py` — lifecycle events, eager loading,
  expiry coercion, no bare-exception resume.
- `apps/api/app/modules/agent/router.py` — approval-gated execution, committed-decision check.
- `apps/api/app/models/enums.py` — `INTERACTION_*`, `LLM_REQUEST_*`, `AGENT_INTERACTION_*`.
- `apps/api/alembic/versions/0013_phase8_interactions.py`, `0014_phase9_observability.py`
  (chain verified end-to-end).
- `apps/api/tests/test_interactions_api.py` (7), `tests/test_observability_api.py` (10).
- `apps/web/lib/api.ts`, `apps/web/lib/agent-types.ts`, `apps/web/components/agent/agent-panel.tsx`
  — the client decision panel (Phase 8 work, verified via tsc/vitest/build).
- `docs/architecture/agent-observability.md` — architecture, taxonomy, privacy, signals,
  retention, runbooks.
