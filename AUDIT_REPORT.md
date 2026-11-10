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
- **Local validation is green:** API `522 passed, 1 skipped`, ruff and mypy clean; web `tsc`/`eslint` clean, `196` vitest tests passing, production build succeeds.
- **Not verified locally:** the Postgres-backed suite, `docker compose`, Playwright/e2e, and the Docker image build. The Docker daemon is not running in this environment. These must run in CI before a production claim.
- **Readiness:** materially improved and safe for continued development and single-instance local use. Not yet production-ready; the remaining items in section I are the reason.

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

The dashboard readiness **aggregate** is still computed in Python over the loaded window; see section I.

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

Deliberately not done: roving arrow-key focus for the agent tablists (documented as a P3 a11y gap).

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

Net new tests: **+7 API** (`515 → 522`) and **+6 web** (`190 → 196`), plus one migration data check.

---

## H. Final validation evidence (run in this environment)

| Command | Result |
|---|---|
| `cd apps/api && .venv/bin/ruff check .` | `All checks passed!` |
| `cd apps/api && .venv/bin/mypy app` | `Success: no issues found in 158 source files` |
| `cd apps/api && .venv/bin/python -m pytest -q` | `522 passed, 1 skipped` in `70.99s` |
| `cd apps/web && npx tsc --noEmit` | clean |
| `cd apps/web && npx eslint .` | clean |
| `cd apps/web && npx vitest run` | `196 passed` (14 files) |
| `cd apps/web && npx next build` | compiled; TypeScript finished; 11 routes generated |
| Browser — dashboard | `48%` / `۴۸%`, `dir=rtl` in Persian |
| Browser — agent panel | REVIEW checkpoint resolved, `POST .../resolve` → `200`, body `{"approved":true}` |
| Browser — network | no `4xx/5xx` on the assignment page after the fix (the only console errors were pre-login `401`s from `/auth/me`) |

Warnings in the pytest output are third-party deprecations (notably `python-jose`'s `datetime.utcnow()`), not failures.

---

## I. Remaining findings (not fixed in this pass)

Severity is my judgement, not an external rating. Each item is a real gap, not a stylistic preference.

1. **Checkpoint decision semantics are stored but not consumed (P2, functional).**
   `resolve_checkpoint` persists `response`, `approved`, and `retry` and then flips the run back to `RUNNING`. The resume path does not branch on `retry` or `selected_option`. A `REVIEW` checkpoint offering "Keep revising / Move on / Stop this run" therefore always takes the same path; only the panel's separate **Stop the run** button actually cancels. The UI is now usable, but the server should either honour these fields or stop offering options it will ignore.

2. **Recovery events bypass redaction and instrumentation (P2, security/observability).**
   `app/modules/agent/recovery.py::_append_event` writes `AgentEvent.metadata_json` directly. It does not call `redact_dict` and does not stamp `assignment_id`, `workspace_id`, correlation/trace ids, severity, or source. If a recovery payload ever contains a credential, it is persisted verbatim. Route it through `observability.service.record_event` or apply `redact_dict` plus the denormalised columns.

3. **The access token is returned in the JSON body as well as the HttpOnly cookie (P2, security).**
   `login`/`register` return `access_token`. The web client relies on the cookie, so the body copy is unnecessary exposure to JavaScript, logs, and XSS. Prefer cookie-only (or a body flag that a non-browser client must opt into) and add `Cache-Control: no-store` on auth responses.

4. **Logout does not revoke a stateless token (P2/P3, security).**
   `POST /auth/logout` only deletes the cookie. A copied token remains valid until `access_token_expire_minutes` (30 minutes). A revocation list or token version would close this; document the window if that is a deliberate trade-off.

5. **Execution artifact storage survives assignment deletion (P3, data hygiene).**
   `delete_assignment` deletes document storage, but `ExecutionArtifact` files are removed only by the cascade of database rows, not their storage keys. Deleting an assignment can leave orphaned bytes. Enumerate and delete execution artifact keys in the same operation, or run a periodic sweeper.

6. **Dashboard readiness aggregate is computed over a 500-row window (P2, correctness at scale).**
   The list is bounded (good), but `average_readiness_score` is computed in Python after the window. Above 500 assignments in a workspace the average silently describes a subset. Move the aggregate to SQL or state the bound in the UI.

7. **`time_ordered_uuid` monotonicity is per process (P3, correctness).**
   The counter in `app/models/identifiers.py` is module-global. Two API workers can mint ids that are not globally ordered within the same millisecond, which weakens the stable tie-break the identifier exists for. Use a per-process prefix/DB sequence if strict cross-worker ordering matters.

8. **`PlanningRun.started_at` nullability is inconsistent with its status (P3).** Noted during the read-through; not reproduced. Confirm the writer sets it when the run leaves `PENDING`, or make the column nullable by contract.

9. **Agent workspace tablists lack roving arrow-key focus (P3, a11y).** Deliberate scope cut in this pass; the tabs are still reachable by Tab.

10. **Server-provided prose remains English in Persian pages (P3, expected).**
    Checkpoint questions/options, failure reasons, and agent-authored UI blocks come from the runtime, not the catalogue. They render as data. Localising them would require translating model output, which is a product decision, not a frontend fix.

---

## J. Not verified here (environment-blocked)

- **Postgres-backed test suite and migrations.** Docker is not running, so `pytest` used SQLite (`aiosqlite`). The migration was exercised only on SQLite. Postgres-specific DDL, concurrent writers, and the `FOR UPDATE` paths remain unverified in this environment.
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

---

## L. Readiness assessment

**What is solid:** the security boundary (proxy trust, idempotency scoping, signing key, approval gate), the run-claim/state machine, the contract between API and web for the agent surface, the i18n vocabulary, and the tested UI paths. The local validation set is fully green and the browser flow from login → assignment → agent decision works against a live API.

**What blocks a production claim:** the Postgres suite and migrations are unverified; the checkpoint decision fields are not consumed; recovery writes bypass redaction; tokens are exposed in the response body and survive logout; execution artifact storage can leak; and the dashboard average is window-bounded. None of these are regressions introduced here, but they are real and should be scheduled before exposing the product to real student data.

**Honest verdict:** this pass moved the codebase from "several P0s and a hard-broken agent decision flow" to "green locally, with a documented short list of production blockers". It is ready for continued development, demos, and CI hardening. It is **not** ready for a production deployment that stores real credentials or runs untrusted code without the items in section I and the CI gates in section J being closed.
