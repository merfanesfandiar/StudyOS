# StudyOS Audit — Final Report

**Date:** 2026-11-10
**Scope:** API (`apps/api`), web (`apps/web`), agent runtime/observability, i18n, and the UI surfaces exercised by a student.
**Method:** Read the code and the existing phase docs, reproduce defects against a local SQLite instance, fix, add regression tests, then re-run the complete local validation set. Every claim below is backed by a command or a browser request recorded in this report. Nothing was "verified" by reading alone.

This report is additive. It does not replace `PHASE9_REPORT.md`, which describes what Phases 8 and 9 built.

---

## A. Executive summary

- **P0 security and runtime-safety defects are fixed:** proxy-header trust is now opt-in, idempotency keys are scoped to `(user, workspace)`, the signing key no longer silently falls back to a constant, a lost run claim can no longer overwrite a terminal state, and the approval gate for high-risk tool dispatch is enforced end to end.
- **P1 correctness/contract defects are fixed:** checkpoint decisions can actually be submitted from the UI (the previous form produced a guaranteed `422`), status vocabularies match the backend, pagination is bounded with real totals, and the TypeScript contract matches the API.
- **A user-visible data bug was found during browser verification and fixed:** readiness was multiplied by 100 (`4,800%` instead of `48%`). It now renders correctly in both locales, with a regression test.
- **UI/UX and i18n:** agent status labels no longer render blank, the HITL block is localized and surfaces failures, the Persian catalogue corruption is fixed, and several accessibility primitives (live regions, status semantics, skip-link target, landmark nesting) are corrected.
- **All ten findings from the first pass's section I are now closed:** checkpoint decisions are consumed by the runtime, recovery events use the redacted append path, auth is cookie-only with logout revocation, execution artifacts are deleted with their assignment, the dashboard average is a SQL aggregate, UUID ordering is process-tagged and clock-regression safe, `PlanningRun.started_at` is non-nullable, and the agent tablists support roving keyboard focus in both directions.
- **Local validation is green:** API `535 passed, 1 skipped`, ruff and mypy clean; web `tsc`/`eslint` clean, `199` vitest tests passing, production build succeeds.
- **Not verified locally:** the Postgres-backed suite, `docker compose`, Playwright/e2e, and the Docker image build. The Docker daemon is not running in this environment. These must run in CI before a production claim.
- **Readiness:** materially improved and safe for continued development and single-instance local use. Not yet production-ready; the unverified CI gates in section J are the reason.

---

## B. Baseline (before this audit)

Recorded before any change, from the repository as found:

| Check | Baseline |
|---|---|
| API tests | `515 passed, 1 skipped` |
| API ruff | `33` findings |
| API mypy | `4` errors |
| Web `tsc --noEmit` | clean |
| Web eslint | `11` errors |
| Web vitest | `190 passed` |
| Web build | succeeded |
| Postgres/Docker/e2e | not run (daemon unavailable) |

The tree also contained uncommitted work from earlier phases (`AGENTS.md` rule, phase docs, interactions/observability modules, migrations `0012`–`0015`). That work was preserved; this audit changed only what is listed in sections C–F.

---

## C. P0 — security and runtime safety

### C1. Proxy headers are no longer trusted by default

**Defect:** The rate limiter read `X-Forwarded-For` unconditionally. A direct client could set the header and choose its own rate-limit bucket, defeating per-IP throttling on auth and other routes.

**Fix:** `rate_limit_trust_proxy` defaults to `False`. The forwarded header is used only when the operator explicitly opts in. Regression test covers the spoofed-header case.

**Evidence:** `apps/api/tests/test_rate_limit.py` (new header-trust case); full suite passes.

### C2. Idempotency keys are scoped to the caller and workspace

**Defect:** A key submitted by one user could collide with another user's key, returning that user's response or suppressing a legitimate operation.

**Fix:** The lookup is scoped to `(user_id, workspace_id, key)`. Regression test asserts two users can use the same key independently and neither can read the other's result.

### C3. Missing `SECRET_KEY` fails closed / uses an ephemeral key deliberately

**Defect:** An empty `SECRET_KEY` silently produced a predictable signing key, allowing token forgery.

**Fix:** Production startup now refuses to mint tokens from a constant fallback; a clearly labeled ephemeral key is used only where the configuration allows it, and the choice is documented. Test covers the configured and unconfigured paths.

### C4. A lost run claim cannot overwrite a terminal state

**Defect:** A worker that lost its claim could still write `RUNNING`/`COMPLETED` over a run another worker had cancelled or completed. The last writer won.

**Fix:**
- `_set_status` re-reads the row under the transaction and raises `RunClaimLost` when the durable status is no longer the one the caller believed it held.
- `_guarded_status` converts that into `409 AGENT_RUN_STATE_CHANGED` at user-facing lifecycle boundaries only; the background loop treats it as "stop, another writer owns this".
- Each step commits, so a crash cannot replay a whole run's side effects.
- `BudgetExceeded` is caught in `_execute_and_finish` and recorded as a failed attempt rather than escaping the loop.
- Interaction resume is permitted only from `WAITING_FOR_USER` or `PAUSED`; the old workspace-wide fallback that could resume the wrong run was removed.
- Checkpoint expiry is swept from `list_interactions`, and an invalid status filter returns `422` instead of being ignored.

**Evidence:** `tests/test_agent_api.py` (claim-loss/state-changed cases); suite passes.

### C5. Approval gate for high-risk tool dispatch

**Defect (pre-fix):** `ApprovalPolicy` existed but was not consulted when `CALL_TOOL` was executed. A `HIGH`-risk sandbox or external-agent tool could be dispatched by the model without a person seeing it.

**Fix:**
- `binding_key(tool, args)` produces a stable hash of the exact operation.
- `ApprovalPolicy.evaluate_tool` requires approval when a `HIGH`-risk tool carries `EXECUTE_SANDBOXED` or `DELEGATE_EXTERNAL_AGENT`.
- `_run_step` creates a `PERMISSION` checkpoint bound to that hash instead of dispatching.
- `_tool_approval_state` honours only a `RESOLVED` checkpoint whose `context` matches the same binding and whose `response` is `approved`. A different argument list is a new binding; a rejection records a `BLOCKED` invocation and dispatches nothing.
- `agent_tool_approval_required` (default `True`) is the single operator switch.

**Evidence:** two regression tests in `tests/test_agent_api.py`: approve → the sandbox job is created and the invocation is `SUCCESS`; reject → the invocation is `BLOCKED` and zero jobs exist. Both pass.

---

## D. P1 — broken workflows, invalid states, contract drift

### D1. Checkpoint decisions were impossible from the UI

**Defect:** `resolve_checkpoint` requires an explicit `approved` for `APPROVAL`, `REVIEW`, and `PERMISSION`. The old panel only sent `response`/`selected_option`, so every such submission was rejected with `422 AGENT_CHECKPOINT_DECISION_REQUIRED`. The seeded run reproduced this: it sat in `WAITING_FOR_USER` forever.

**Fix:**
- `CheckpointPrompt` treats those three types as decisions and renders **Approve**, **Reject**, and **Try that step again** (the latter sends `approved: false, retry: true`).
- Runtime sentinels `approve`/`reject` are filtered out of the radio options; they are now the buttons, not duplicate form values.
- **Stop the run** calls `cancel()` instead of submitting an empty answer (which always produced a `422`).
- Submit is disabled when a text/option answer is required but absent.
- The HITL interaction block is localized, consolidates approve/reject through one `decide()` path, and reports failures with `agent.decisionFailed`.

**Evidence (browser):** a `REVIEW` checkpoint was resolved; the `POST .../checkpoints/{id}/resolve` returned `200` with request body `{"approved":true}`, and the run resumed. Regression tests assert `approved:true`, `approved:false` (with no `response`), and that **Stop** posts to `/cancel` without touching the resolve endpoint.

### D2. Status and artifact vocabularies drifted from the backend

**Defect:** `status.agentExecution.pending/running/succeeded/rejected` and `status.agentArtifact.reviewed/submitted` no longer matched the enums, so labels rendered as raw keys or blank text.

**Fix:** the catalogue now mirrors the backend exactly:
- execution: `success, partial_success, failed, blocked, needs_user_input, needs_approval, skipped`
- artifact: `draft, active, superseded, archived`
- checkpoint: `pending, resolved, cancelled, expired`

**Test:** `tests/unit/i18n.test.ts` pins every backend status value for run/execution/artifact/tool/checkpoint and every interaction risk value in both locales. A new backend value now fails a test instead of reaching a student as `status.agentExecution.*`.

### D3. API/TypeScript contract drift

- `AgentExecutionResponse.task_id` is `UUID | None` in the schema and `string | null` in `agent-types.ts`.
- Agent enums in `agent-types.ts` were aligned with the backend.
- `agentInteractionHistory` is typed as `AgentInteractionResponseHistoryItem[]` and the endpoint has a `response_model`.
- Four test fixtures using the retired artifact type `"DRAFT"` were corrected.

### D4. Unbounded queries

| Surface | Change |
|---|---|
| `list_jobs`, `list_runs` | return `(items, total)` and accept `offset`; routers report real totals |
| tool invocations | default limit `500`, `le=1000` |
| dashboard assignments | capped at `500` |
| taxonomy technologies/tags | capped at `500` |
| artifact-event provenance scan | capped at `2000` |

The dashboard **list** is capped at `500`, but the readiness **aggregate** is computed in SQL over the whole workspace, so it does not describe only the visible window.

### D5. `TECHICAL` typo in a persisted enum

**Fix:** `RequirementType.TECHNICAL` replaces `TECHICAL`. Migration `0015_fix_technical_requirement_type` rewrites existing rows and adds `ix_audit_logs_agent_run_id` in the same migration.

**Evidence:** upgrade → downgrade → upgrade on SQLite; the `TECHICAL` row rewrite was verified with a seeded row. Postgres is untested locally (section J).

---

## E. P2/P3 — UI, UX, i18n, accessibility

- **Readiness percentage bug:** `readiness_score` is `0–100`, but the dashboard and card passed it to `Intl.NumberFormat` with `style: "percent"`, multiplying by 100 (`4,800%`). Fixed to `formatNumber(score) + "%"` in `assignment-card.tsx` and the dashboard's four call sites. Regression test `tests/unit/assignment-card.test.tsx`.
- **Persian catalogue corruption:** `analysis.rubricInferred` began with a stray Latin fragment (`" rubricای …"`); corrected to `"بارم‌نامه‌ای …"`.
- **Untranslated UI moved onto the catalogue:** requirements/constraints/criteria/deliverables/taxonomy empty states, brief status note, delete confirmation, rubric-provided note, settings mark-read failure, decision/risk labels, and the pending-decisions heading.
- **Settings:** a failed "mark read" no longer says "could not load settings"; it uses `settings.markReadFailed`.
- **`Alert`:** now `role="alert"` for errors and `role="status"` otherwise, so failed saves are announced.
- **`CheckDot`:** now `role="img"`, which is what makes its `aria-label` reach assistive tech instead of leaving the check colour-only.
- **Skip link / landmarks:** loading and error states on the assignment page carry `id="main-content"`; the segment error boundary no longer nests a second `<main>` inside the app shell's landmark.
- **Verified in the browser:** `dir="rtl"`, `lang="fa-IR"`, Persian labels for run/decision/risk/actions, no leaked `status.*`/`agent.risk.*` keys, dashboard shows `۴۸%`.

- **Agent tablists:** roving `tabindex` with `ArrowLeft`/`ArrowRight`/`Home`/`End`, including RTL-aware arrow direction and wrap-around; the selected tab is the only tab stop.

---

## F. Files changed by this audit

**API**
- `app/core/config.py`, `app/core/rate_limit.py`, `app/core/security.py`
- `app/models/enums.py`, `app/schemas/agent.py`
- `app/modules/agent/service.py`, `policy.py`, `router.py`, `tools.py`, `domain_tools.py`
- `app/modules/analysis/{router,service}.py`, `app/modules/assignments/taxonomy_router.py`
- `app/modules/dashboard/router.py`, `app/modules/execution/{router,service}.py`
- `alembic/versions/0015_fix_technical_requirement_type.py`
- `tests/{conftest,test_agent_api,test_auth,test_execution_api}.py`

**Web**
- `lib/i18n/messages.ts`, `lib/agent-types.ts`, `lib/api.ts`
- `components/agent/agent-panel.tsx`, `components/ui.tsx`, `components/assignment-card.tsx`
- `components/assignment-detail.tsx`, `components/assignment/{analysis-panel,assignment-brief,content-sections,requirements-section,taxonomy-section}.tsx`
- `app/(app)/dashboard/page.tsx`, `app/(app)/settings/page.tsx`, `app/(app)/error.tsx`
- `tests/unit/{agent-panel,i18n,plan-panel,assignment-card}.test.tsx`

**Docs**
- `docs/architecture/agent-observability.md` (redaction rule made exact)
- `docs/architecture/agent-security.md` (approval gate / `agent_tool_approval_required`)

**Follow-up pass (section I closures)**
- `app/core/{security,dependencies}.py`, `app/schemas/auth.py`, `app/modules/auth/router.py`
- `app/models/{entities,identifiers}.py`, `app/modules/agent/{service,context,router,recovery}.py`
- `app/modules/assignments/router.py`, `app/modules/dashboard/router.py`
- `alembic/versions/0016_token_revocation_and_planning_started_at.py`
- `tests/{test_identifiers,test_agent_runtime,test_agent_api,test_auth,test_execution_api,test_migrations,test_planning_service,test_specification}.py`
- `apps/web/components/agent/agent-panel.tsx`, `apps/web/lib/{types,i18n/messages}.ts`
- `apps/web/tests/unit/agent-panel.test.tsx`
- `docs/architecture/decisions/0001-cookie-session-auth.md`, `docs/architecture/agent-runtime.md`, `docs/architecture/agent-recovery.md`

Uncommitted user work in `globals.css`, `layout.tsx`, `app-shell.tsx`, `auth-page.tsx`, and `next-env.d.ts` was left untouched.

---

## G. Regression tests added

| Area | Test |
|---|---|
| Proxy header trust | spoofed `X-Forwarded-For` does not get its own bucket |
| Idempotency | same key, two users, independent results |
| Run claim loss | terminal state is not overwritten; `409` at the boundary |
| Approval gate | approve dispatches; reject records `BLOCKED` and creates no job |
| Checkpoint decisions | approve sends `approved:true`; reject sends `approved:false` without a text answer; Stop calls `/cancel` and never resolves |
| i18n vocabulary | every backend status and interaction risk has a key in every locale |
| Readiness formatting | card renders `48%`, not `4,800%` |
| Redaction | `token_usage` survives while `token`/`*_token` do not |
| Checkpoint semantics | Stop cancels, Move on completes, Keep revising extends the allowance, answers reach the next context, permission retry stays pending |
| Logout revocation | a token copied before logout is rejected afterwards |
| Auth response | no token in the JSON body; `Cache-Control: no-store` |
| Dashboard average | covers more than the 500-row list window |
| Assignment deletion | removes execution artifact bytes and keeps the job row |
| UUIDv7 | version/variant, 2,000 strictly increasing ids, backwards-clock monotonicity |
| `started_at` | set when a run starts; `NOT NULL` after migrations |
| Recovery redaction | recovery metadata is redacted and instrumented like runtime events |
| Tab keyboard nav | roving tab stop, wrap-around, RTL arrow direction |
| Runtime prose i18n | the revision-limit REVIEW prompt/options/context render in Persian |

Net new tests across both passes: **+20 API** (`515 → 535`) and **+9 web** (`190 → 199`), plus migration data/nullability checks.

---

## H. Final validation evidence (run in this environment)

| Command | Result |
|---|---|
| `cd apps/api && .venv/bin/ruff check .` | `All checks passed!` |
| `cd apps/api && .venv/bin/mypy app` | `Success: no issues found in 158 source files` |
| `cd apps/api && .venv/bin/python -m pytest -q` | `535 passed, 1 skipped` in `72.71s` |
| `cd apps/web && npx tsc --noEmit` | clean |
| `cd apps/web && npx eslint .` | clean |
| `cd apps/web && npx vitest run` | `199 passed` (14 files) |
| `cd apps/web && npx next build` | compiled; TypeScript finished; 11 routes generated |
| Browser — dashboard | `48%` / `۴۸%`, `dir=rtl` in Persian |
| Browser — agent panel | REVIEW checkpoint resolved, `POST .../resolve` → `200`, body `{"approved":true}` |
| Browser — network | no `4xx/5xx` on the assignment page after the fix (the only console errors were pre-login `401`s from `/auth/me`) |

Warnings in the pytest output are third-party deprecations (notably `python-jose`'s `datetime.utcnow()`), not failures.

---

## I. First-pass findings — all closed in the follow-up pass

Severity is my judgement, not an external rating. Each entry keeps the original defect and records the correction and its evidence.

1. **Checkpoint decision semantics are consumed (was P2, functional).**
   `resolve_checkpoint` now acts on the fields it stores. `retry` is written as `"retry"` and leaves a pending gate instead of pretending the permission was refused. A `REVIEW` option is read as a decision: **Stop this run** cancels, **Move on and leave the draft** completes the task and resumes, and **Keep revising** extends the draft allowance. Student answers are injected into the next step through a bounded `student_answers` context section. Regression tests cover all four paths plus the permission-retry case in `tests/test_agent_runtime.py`.

2. **Recovery events use the redacted append path (was P2, security/observability).**
   `_append_event` delegates to `observability.service.record_event`, so recovery metadata is redacted and rows carry `assignment_id`, `workspace_id`, correlation/trace ids, `WARNING` severity, and `agent.recovery` as the source. `tests/test_agent_api.py` asserts a credential is persisted as `[REDACTED]` and that the operational columns are populated.

3. **Auth is cookie-only (was P2, security).**
   `login` and `register` no longer return `access_token`; the web client already relied on the HttpOnly cookie, and `AuthResponse` now matches. Auth responses carry `Cache-Control: no-store`. `tests/test_auth.py` covers the response shape and header.

4. **Logout revokes tokens (was P2/P3, security).**
   `users.token_version` is embedded as the `ver` JWT claim and checked in `get_current_user`; logout bumps it, revoking every session for that user rather than only deleting the current cookie. Tokens without a `ver` claim are treated as version `0` for migration compatibility. `test_logout_revokes_a_token_that_was_already_copied` copies a token, logs out, and asserts the copy is rejected.

5. **Execution artifact storage is deleted with the assignment (was P3, data hygiene).**
   `delete_assignment` enumerates the assignment's execution artifacts, deletes their storage objects, and nulls `storage_key` while preserving the `ExecutionJob` row (`assignment_id` is still `SET NULL`). `test_deleting_an_assignment_removes_execution_artifact_bytes` checks both the missing bytes and the surviving audit row.

6. **The dashboard average is a SQL aggregate (was P2, correctness at scale).**
   `average_readiness_score` is computed with a database aggregate over the whole workspace, independent of the 500-row list cap. `test_dashboard_average_covers_more_than_the_visible_window` seeds more rows than the window and asserts the returned average includes them.

7. **`time_ordered_uuid` is process-tagged and clock-regression safe (was P3, correctness).**
   Ids now combine a per-process 8-bit prefix, a 12-bit sub-millisecond slot (~244µs), a millisecond timestamp, and randomness. When the wall clock moves backwards the generator advances from the last emitted `(ms, slot)` rather than the regressed clock, so ids stay monotonic. `tests/test_identifiers.py` asserts UUIDv7 version/variant, 2,000 strictly increasing ids, and monotonicity across a backwards clock jump. Strict cross-process wall-clock ordering would still need a shared sequence; the process prefix makes collisions impossible, which is the property the identifier actually needs.

8. **`PlanningRun.started_at` is non-nullable (was P3).**
   The model declares it non-nullable and the service sets it when the run starts. Migration `0016_token_revocation_and_planning_started_at` backfills existing rows and applies `NOT NULL`; `tests/test_migrations.py` checks nullability after upgrading to head, and `test_planning_service.py` checks the writer.

9. **Agent tablists have roving keyboard focus (was P3, a11y).**
   Tabs use roving `tabindex` with `ArrowLeft`/`ArrowRight`/`Home`/`End`, wrap-around, and RTL-aware arrow direction. `apps/web/tests/unit/agent-panel.test.tsx` verifies the single tab stop, selection movement, `End`, wrap-around, and Persian direction.

10. **Deterministic runtime prose is localized (was P3).**
    The runtime's revision-limit question, its three options, its context note, and the permission question now come from the i18n catalogue, so Persian pages no longer show those fixed English sentences. Model-authored prose and stored failure reasons remain data by design. The Persian REVIEW rendering is covered by a unit test.

### Follow-up validation evidence

| Command | Result |
|---|---|
| `cd apps/api && .venv/bin/ruff check .` | `All checks passed!` |
| `cd apps/api && .venv/bin/mypy app` | `Success: no issues found in 158 source files` |
| `cd apps/api && .venv/bin/python -m pytest -q` | `535 passed, 1 skipped` in `72.71s` |
| `cd apps/web && npx tsc --noEmit` | clean |
| `cd apps/web && npx eslint .` | clean |
| `cd apps/web && npx vitest run` | `199 passed` (14 files) |
| `cd apps/web && npx next build` | compiled; TypeScript finished; routes generated |

The Postgres suite, Docker stack/image, and Playwright/e2e remain unverified here for the environment reasons in section J.

---

## J. Not verified here (environment-blocked)

- **Postgres-backed test suite and migrations.** Docker is not running, so `pytest` used SQLite (`aiosqlite`). Migrations `0015` and `0016` (including the `started_at` backfill and `NOT NULL` change) were exercised only on SQLite. Postgres-specific DDL, concurrent writers, and the `FOR UPDATE` paths remain unverified in this environment.
- **`docker compose` stack and the container image build.** No daemon.
- **Playwright / end-to-end tests.** Not run; browser checks above are manual, single-session evidence.
- **Load/performance and memory profiling.** Not measured; no claim is made.
- **Backup/restore and multi-worker recovery.** The recovery code was read and its unit tests pass, but multi-process recovery was not exercised.

These are the first things CI should run.

---

## K. Behaviour changes worth knowing

- High-risk tool dispatch now pauses on a `PERMISSION` checkpoint by default. Operators who relied on unattended execution must set `agent_tool_approval_required=False` knowingly.
- User-facing run mutations now return `409 AGENT_RUN_STATE_CHANGED` when another writer has already moved the run; clients should refresh rather than retry blindly.
- The permission-checkpoint binding is `(tool, arguments)`, not the tool alone. The same tool with different arguments asks again; that is intentional.
- Interaction/checkpoint expiry is swept on list calls, so a stale `PENDING` interaction can become `EXPIRED` without a background job.
- Pagination responses now carry real `total` values; clients that assumed `total == len(items)` should re-check.
- The dashboard/card readiness figure changed from a 100× value to the real percentage. Any snapshot test keyed to `4,800%` was wrong.
- Auth responses no longer include `access_token`; a non-browser client must rely on the cookie. Logout increments `users.token_version`, so it now ends **every** session for that user, not just the current browser.
- `POST /agent/runs/{id}/resume` only executes a run that is still `RUNNING` after a decision; an option that cancels or completes the task never re-enters the executor.
- Checkpoint answers now appear in the next step's context under `student_answers` (bounded by the usual truncation order), so a runtime that ignored them is no longer an option.

---

## L. Readiness assessment

**What is solid:** the security boundary (proxy trust, idempotency scoping, signing key, approval gate), the run-claim/state machine, the contract between API and web for the agent surface, the i18n vocabulary, and the tested UI paths. The local validation set is fully green and the browser flow from login → assignment → agent decision works against a live API.

**What blocks a production claim:** the environment-blocked gates in section J. The Postgres suite and migrations are unverified, `docker compose` and the image build have not run, and Playwright/e2e has not run. The ten functional/security findings from the first pass are closed. Multi-process UUID ordering remains a per-process guarantee by design; it prevents collisions but does not provide a global wall-clock order.

**Honest verdict:** this work moved the codebase from "several P0s and a hard-broken agent decision flow" to "green locally, with all first-pass findings closed and a short list of CI gates left". It is ready for continued development, demos, and CI hardening. It is **not** ready for a production deployment that stores real credentials or runs untrusted code until the gates in section J are run and pass.
