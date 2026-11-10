# Agent Observability

Phase 9: every run answers "what happened, what did it cost, and who decided what" — from the
real execution path, not from handwritten log lines.

## The two ledgers

Phase 9 keeps two deliberately different records, and the difference is the point:

| | `agent_events` (operational) | `audit_logs` (security) |
|---|---|---|
| Question it answers | What did the run do and why? | Who authorised what? |
| Written by | The runtime, tools, interactions, LLM calls | HITL decisions, privileged operations |
| Mutable? | Within the run's transaction only | Append-only, never updated |
| Visible to | The run's owner, via the API | Operations, via queries |
| Contains | Step summaries, token usage, latency, outcomes | Approvals, rejections, policy codes |

The security ledger never becomes a dumping ground for telemetry, and the event stream never
pretends to be tamper-evident infrastructure. The tables share machinery (`redact_dict`,
correlation ids) but not intent.

## What an event carries

Every `AgentEvent` row written after Phase 9 is a structured, versioned record:

- `event_type` — a member of `AgentEventType` (the taxonomy below).
- `summary` — a user-facing sentence. This is what the timeline shows.
- `metadata_json` — redacted JSON (see privacy).
- `sequence` — dense, strictly increasing, unique per run (backed by a unique constraint).
- `correlation_id` / `causation_id` — which logical operation and which direct cause.
- `trace_id` / `span_id` — a lightweight in-database trace; no OTel export.
- `severity` — `INFO`, `WARNING`, `ERROR`.
- `source_component` — who emitted it (`agent.runtime`, `agent.interactions`, ...).
- `outcome` — `SUCCESS` / `FAILED` / `BLOCKED`, where it applies.
- `duration_ms` — wall-clock duration for measurable events.
- `schema_version` — currently `1`. Consumers can branch on it when the shape evolves.

## Event taxonomy

Lifecycle: `RUN_CREATED`, `RUN_STARTED`, `RUN_PAUSED`, `RUN_RESUMED`, `RUN_CANCELLED`,
`RUN_COMPLETED`, `RUN_FAILED`, `RUN_RETRIED`.

Per-task: `TASK_STARTED`, `TASK_COMPLETED`, `TASK_FAILED`, `TASK_BLOCKED`.

Decisions and tools: `DECISION_RECORDED`, `WORKER_SELECTED`, `TOOL_SELECTED`,
`TOOL_INVOCATION_STARTED/COMPLETED/FAILED`, `TOOL_INVOKED`, `TOOL_BLOCKED`.

Human interaction (Phase 8): `INTERACTION_REQUESTED`, `INTERACTION_RESPONDED`,
`INTERACTION_EXPIRED`, `INTERACTION_CANCELLED`.

Model calls (Phase 9): `LLM_REQUEST_STARTED`, `LLM_REQUEST_COMPLETED`, `LLM_REQUEST_FAILED`.
These are emitted around the real `provider.complete` call in the execute loop, so token usage
and latency reflect the model that actually ran, not an estimate written by hand.

## The security audit trail

`AuditLog` rows are a second append-only stream. Phase 9:

- Added `AGENT_INTERACTION_REQUESTED / RESOLVED / EXPIRED / CANCELLED`.
- Every interaction decision is attributable: actor, action, target, reason, correlation id,
  policy code.
- `record_audit_event` performs a single INSERT. It never reads back or mutates a latest row.

**Tamper-evidence, honestly:** the audit trail is append-only at the *application* level. There is
no cryptographic hash-chain, no WORM store, and no external notarisation. An attacker with direct
database write access can delete rows. What the audit trail gives is completeness and
attributability for every operation that went through the API — nothing more, and this limit is
stated rather than hidden.

## Privacy

`redact_dict` is applied to every persisted `metadata_json` and audit payload:

- A key is redacted when it contains `password`, `secret`, `api_key`, `private_key`, or
  `authorization`, is exactly `token`, or ends in `_token` (at any nesting depth). The bare
  `token` case is deliberate: matching the substring everywhere would also swallow `token_usage`,
  the cost field this module exists to expose.
- The key is kept and its value replaced with `[REDACTED]`, so the shape of a payload stays
  auditable without the credential.
- Strings are truncated so a runaway payload cannot bloat the table.
- Chain-of-thought is never stored: only the resulting structured `AgentAction` and the model
  provider name are persisted. Nothing in any observability table contains the model's reasoning
  text.

## Cost accounting

Costs are **estimates** and are labelled as such. `estimated_cost` is computed at pricing time and
stored on the run; the `/usage` endpoint returns it alongside `cost_source: "provider_estimate"`
and a `pricing_version` stamp (`2026-10`) so a future pricing change cannot retroactively
reinterpret old numbers. Provider responses whose usage is missing never silently bill zero: the
usage endpoint marks `usage_available: false`.

## The API

The observability router is entirely workspace-scoped. Every path
serves through `load_owned_run`, adopting the same 404-instead-of-403 convention as the rest of the
agent module: another student's identifiers are indistinguishable from nonexistent ones.

| Endpoint | Purpose | Pagination |
|---|---|---|
| `GET /api/v1/assignments/{aid}/agent/runs/{rid}/events` | Structured, ordered event stream | Cursor on `sequence`, only offered when another page exists |
| `GET .../timeline` | Everything that happened, in order | Hard limit, max 1000 |
| `GET .../usage` | Token usage, estimated cost, model, pricing version | Single object |
| `GET .../artifacts/{aid}/provenance` | The events responsible for a draft's creation | Nested list |
| `GET .../signals` | Workspace-scoped stalled runs / bursts / outliers | Owner-only (403 otherwise) |

## Signals

Because there is no streaming infrastructure, anomalies are computed from the same tables, at
request time:

- **Stalled run**: a run in `RUNNING` whose newest event is older than 15 minutes (or which has
  no events and was created more than 15 minutes ago).
- **Failure burst**: more than 10 ERROR-severity events in one run inside a 60-minute window.
- **Cost outlier**: a run whose estimated cost is above the workspace review threshold.

Thresholds are module constants in `observability/signals.py`; there is no background worker and
no alerting channel — the operator dashboard is the endpoint. This is documented as a
deliberate lightweight choice: at current scale it answers "is anything stuck right now", and a
push-based alerting system would require exactly the infrastructure the phase declines to add.

## Retention

Event and audit rows inherit the lifetime of their parent run (deleted runs cascade). There is no
independent purge job, no configurable retention window, and no archive to cold storage. For a
deployment where events must outlive runs, that becomes a new requirement — a scheduled purge
writing to an external store — and is explicitly *not* part of this phase.

## Runbooks

**A run looks hung (nothing in the timeline is moving):**

1. `GET .../events?limit=200` — find the last event and its timestamp.
2. Confirm the run is `RUNNING` and its last event is older than the stall threshold.
3. `GET .../signals` — the stalled-run list names the run and how long it has been quiet.
4. The safe intervention is `POST .../cancel` (idempotent, audited). Do not edit run rows directly.

**Costs look inflated:**

1. `GET .../usage` — token totals, estimated cost, model.
2. `GET .../events` filtered mentally by `LLM_REQUEST_COMPLETED` — per-call `token_usage` and
   `duration_ms` show whether the spend tracks many small calls or fewer large ones.
3. A `COST_OUTLIER` signal names the worst runs in the workspace.

**A user disputes a decision the agent made:**

1. The `agent_decisions` rows for the run record what the model chose and what happened.
2. The audit ledger (`audit_logs`) records every human approval that authorised the step,
   with actor and operation binding.
3. `correlation_id` joins a disputed outcome back to the exact request that produced it.

**Reproducing locally:**

```bash
cd apps/api
python -m pytest tests/test_observability_api.py tests/test_interactions_api.py -q
```
