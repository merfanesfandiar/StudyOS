# Phase 5: Agent Runtime — Final Report

## Summary

Phase 5 built the component that actually does the work. Phase 3 read an assignment, Phase 4 proposed
a plan, and this phase walks that plan one task at a time: it routes a model per step, assembles a
bounded context, validates a structured decision against three independent checks, executes it through
a closed registry of three tools, keeps every draft revision, stops for a human when a decision is
genuinely a human's, and can be reclaimed after a crash without ever resuming on its own.

The design premise is that the model is not trusted and does not decide what happens. It proposes an
action; code that did not come from the model decides whether that action is allowed. If the model
returned something malicious on every field of every response, the outcome would be refused runs and
visible errors.

The capability boundary is structural, not configurable. There is no shell, no network access, no
filesystem write, no code execution, and no tool registry that can grow at runtime. `CODE` is an
artifact type — the runtime drafts a function and does not run one. The negative list is published as
data by the API and rendered in the UI, so a student can read what the agent cannot do without opening
documentation.

## What was built

### Runtime service

`apps/api/app/modules/agent/service.py` (~2,360 lines) implements the loop: run creation and
lifecycle, dependency-aware task selection, model routing through the Phase 4 `ModelRouter`, context
assembly, decision parsing and validation, execution, artifact persistence, checkpoints, budget
accounting, and the audit trail. Steps run inline, one transaction each, so a crash between steps
leaves a consistent database and a recoverable run.

`AgentRun` binds to a specific `plan_id` and `plan_version` at creation, so a run continues against the
plan the student approved rather than silently switching to regenerated work they never saw.

Creating a run and starting it are separate calls, deliberately. Opening the workspace reads state and
spends nothing.

### State machine

`state_machine.py` holds an explicit transition table; every lifecycle change goes through
`assert_transition`. Three absences are the design: `WAITING_FOR_USER` cannot reach `COMPLETED`
without executing real work, terminal statuses have no outgoing edges, and `RUNNING → RUNNING` is
rejected — with one narrow exception in `execute_run` for re-entering a run that is legitimately still
going.

### Recovery

`recovery.py` reclaims runs abandoned by a crash: it finds stale `STARTING`/`RUNNING` runs by
heartbeat cutoff, pauses them with a reason chosen by how far they got, and expires unanswered
checkpoints. It never resumes anything — every reclaimed run requires a human to continue it. Both
steps are idempotent, so the sweep is safe on every boot and on a timer.

### Tools, decisions, context

- `tools.py` — three tools (`read_context`, `write_artifact`, `request_checkpoint`), each declaring
  its own permissions. The registry refuses to register a tool declaring `EXECUTE_UNTRUSTED`, which
  exists as a named permission no tool holds, so a future dangerous capability has to be argued for
  in review.
- `decisions.py` — three independent validation layers (schema, semantics, permissions). They are
  separate functions on purpose: one layer catching another's failure is how a validation system ends
  up with one layer. A rejected decision is a recorded `AgentExecution`, not a lost run.
- `context.py` — proportional, bounded context assembly with fixed truncation order and untrusted
  markers around student-authored text. Provenance is recorded for every section including dropped
  ones, so "why couldn't the agent see my document?" has an answer in the data.

### API

Eleven endpoints under `/api/v1/assignments/{id}/agent/`, ownership-resolved from the session. The
capabilities endpoint returns the tool list, the absent-capability list, and the runtime's live limits,
so the UI can explain a stop in terms of the budget that caused it.

### Frontend

`agent-types.ts`, `use-agent.ts`, and `components/agent/agent-panel.tsx` add the Agent Workspace,
rendered inside the plan panel because the dependency is visible in the interface and the approval
state that gates it is already there.

The panel is written for a student who did not ask for an agent: the capability boundary is on screen,
every stop states the server's own reason, and failed attempts stay visible with their errors and
every draft revision is kept. 102 new message keys in both English and Persian; the Persian catalogue
is typed as `Record<MessageKey, string>`, so an omission is a compile error rather than English
leaking onto a Persian page.

### Documentation

Six architecture documents under `docs/architecture/`: the runtime overview, the state machine, the
tool registry, context assembly, the threat boundary, and recovery.

## Defects the verification found

Every one of these was a real defect, found by a test that was written to check a property and not a
specific line of code.

**A student's answer did nothing.** `resolve_checkpoint` marked the checkpoint resolved but never moved
the run out of `WAITING_FOR_USER`, so answering a question left the run permanently stuck — the
question was answered and nothing was left telling the runtime it could proceed. The HTTP test for the
full checkpoint exchange caught this. Fixed by transitioning the run on resolution, which added a
`RUNNING → RUNNING` re-entry that the state machine had no edge for.

**Pause was disabled exactly when it was needed.** The Agent panel disabled the pause control while a
run was active, on the reasoning that active runs should not be disturbed. That removes the only way
to stop work a student did not want. The unit test asserting a pause error is displayed could not
click the button at all.

**A capability-list failure crashed the whole assignment page.** A 200 response with an unexpected
body reached `absent_capabilities.map(...)` and threw, unmounting the entire page — the plan, the
analysis, everything. Found by a pre-existing Persian E2E test that stubbed the API with a catch-all
shape. Fixed with a cheap shape check in the hook, since the capability disclosure is a nice-to-have
that must never take the workspace with it.

**The agent API was mounted at the wrong prefix.** Registered as `/assignments/...` rather than
`/api/v1/assignments/...`, so every route 404'd. Found by the first HTTP test.

**Recovery paused other students' runs.** `POST /agent/recover` called the global sweep, so a button
on one assignment could pause any run in the database. Both recovery query functions now take an
optional `assignment_id` and the router always passes it. Two tests pin it: one proving the scoped
sweep still recovers your own stale run, one proving it cannot reach somebody else's.

**Event sequences could collide.** Two concurrent writers could produce duplicate or interleaved-gap
trails because the sequence was tracked in application code only. Now backed by a
`(run_id, sequence)` unique constraint in the database and a migration.

**Async ORM lazy loads.** Collections were being read outside the awaited context, raising
`MissingGreenlet` on several endpoints. Replaced with explicit queries and eager loaders.

**The agent wrote the model's justification into the draft.** Artifact bodies were built from the
decision rationale rather than the executor's work product, so a draft contained the model's
explanation instead of its work. One API test asserts `"Proceeding."` never appears in artifact
content.

**Costs were fabricated.** `_charge_run` recorded a made-up figure rather than the provider's reported
cost. Now accumulated from the actual response.

Plus: a malformed `resolve_checkpoint` signature, a stripped docstring, step-budget exhaustion leaving
a run stranded in `RUNNING`, `COMPLETE_TASK` creating a spurious executor call and artifact, a
`PROVIDER_UNAVAILABLE` path that produced no artifact at all, a missing `STARTING → PAUSED` edge that
made crashed-startup runs unreclaimable, and several mypy and lint issues.

## Quality gate verification

| Gate | Command | Result |
| --- | --- | --- |
| API lint | `ruff check app tests alembic` | all checks passed |
| API types | `mypy app` | 2 pre-existing errors in Phase 4 files, none in Phase 5 |
| API tests | `pytest -q` | 305 passed, 871 warnings |
| API migration | `tests/test_migrations.py` | 3 passed |
| Web types | `tsc --noEmit` | clean |
| Web lint | `eslint .` | clean |
| Web unit | `vitest run` | 153 passed, 10 files |
| Web build | `npm run build` | compiled successfully |
| Browser | `playwright test` | 19 passed, 8 skipped (API absent) |

The 2 mypy errors are in `app/modules/planning/router.py:400` and
`app/modules/assignments/requirements.py:291`. Both files are untouched by Phase 5 and both errors
predate it; they are recorded here rather than quietly fixed inside an unrelated phase.

The 38 new backend tests are 22 runtime tests (planning, lifecycle, budgets, recovery, determinism) and
16 HTTP tests running against the real router with a deterministic provider. The 14 new web tests cover
the panel's states, and the 2 new browser tests cover the create/start separation and terminal-state
persistence across a reload.

## What was not verified

- **The full-stack agent flow did not run here.** The eight `critical-flow.spec.ts` tests need the
  API and a real database; neither was available. They skip with a stated reason, so a red suite means
  a real regression. The two new agent tests have therefore never been observed passing against a live
  stack.
- **No real model was ever called.** Every provider in this phase was the deterministic mock. Latency,
  token accounting, rate limiting, and real failure modes are unmeasured. The code paths that read a
  provider's reported usage are exercised by the mock's values, not by a provider's.
- **PostgreSQL was not available.** All 305 backend tests ran on SQLite. The `SELECT ... FOR UPDATE`
  locking path and the new unique constraint are correct in the schema but unexercised against a real
  database engine.
- **Visual layout was not inspected.** No screenshots were available, so the panel is verified
  structurally and through assertions on rendered output.
- **Migration was verified by test, not by an upgrade path.** `tests/test_migrations.py` confirms the
  migration applies to a clean database and produces the expected schema. No upgrade from a populated
  Phase 4 database was performed.

## Known limitations

- **Delimited untrusted context is a mitigation, not a guarantee.** A persistent payload in a
  student's own document might still influence output. The structural defence is what holds: an
  injected instruction can change what text is written into a draft, and cannot change what runs,
  what is called, or what is reachable.
- **No background worker.** Steps run inline in the request. `lock_version` plus PostgreSQL row locks
  give correct single-node behaviour, but there is no distributed queue.
- **No notifications.** A reclaimed run is discoverable by its paused status, but nothing emails or
  messages the student.
- **`reference_material` gets a small context budget** and is likely truncated on a large brief. The
  provenance data says so rather than leaving the agent mysteriously unhelpful.
- **Checkpoint expiry is silent to the student.** The question is closed and the run continues; there
  is no notification that a question timed out unanswered.

## Files changed

### Backend

- `app/modules/agent/` — 13 modules: service, recovery, router, state machine, tools, decisions,
  context, executors, selection, limits, ml, package init
- `app/schemas/agent.py` — request and response DTOs
- `app/ai/prompts/agent.py` — decision and execution prompts with response schemas
- `app/ai/prompts/__init__.py` — agent prompt exports
- `app/ai/providers/mock.py` — deterministic provider behaviour
- `app/models/entities.py`, `app/models/enums.py`, `app/models/__init__.py`
- `app/core/config.py` — agent settings
- `app/main.py` — router registration
- `alembic/versions/0006_phase5_agent_runtime.py`

### Web

- `lib/agent-types.ts`, `lib/use-agent.ts`, `lib/api.ts`
- `components/agent/agent-panel.tsx`
- `components/planning/plan-panel.tsx` — hosts the agent workspace
- `lib/i18n/messages.ts` — 102 keys in English and Persian
- `tests/unit/agent-panel.test.tsx`, `tests/e2e/critical-flow.spec.ts`

### Docs

- `docs/architecture/agent-runtime.md`
- `docs/architecture/agent-state-machine.md`
- `docs/architecture/agent-tools.md`
- `docs/architecture/agent-context.md`
- `docs/architecture/agent-security.md`
- `docs/architecture/agent-recovery.md`