# Phase 7: The Secure Execution Environment — Final Report

## Summary

Phase 6 gave the agent a large, closed, deterministic academic toolkit and made one promise: nothing
it held could leave the run. Phase 7 adds the one capability that *does* leave — running code — and
spends the phase keeping that promise true anyway. The model still cannot choose a command, an image,
a path, an environment variable or a resource limit. It can submit text to a runtime, and that text
runs inside a backend the runtime built, never on the host.

The shape of the phase is therefore not "add code execution". It is "add a *sandbox* and route the one
new capability through it":

- **There is no host execution path, by construction.** The `disabled` backend is the default and it
  `REJECTED`s jobs rather than running them. There is no setting that turns execution on without an
  isolation backend.
- **The boundary is a container, and every flag is a boundary.** `--network none`, `--read-only`,
  `--cap-drop ALL`, `no-new-privileges`, `--user 65534:65534`, memory/CPU/PID caps and a single
  mounted workspace. The Docker socket is never mounted into a container.
- **Resources are ceilings clamped twice** — a per-type profile, then the operator's maxima — and a
  client may only ask for *less*.
- **Failure is classified, not flattened.** A compile error, a non-zero exit, a timeout and a
  resource kill are distinct, because they drive different retry decisions.
- **The environment is tracked apart from the result.** "The process exited" and "the environment is
  gone" are different facts, modelled separately.
- **The queue is the database.** No Celery, no Redis: a claim is a single conditional `UPDATE`, and a
  crashed worker is recovered by a lease sweep.
- **The API is thin and description-first.** Two endpoints describe what a deployment can run; the
  rest submit, read, list and cancel, all scoped to an owned assignment.

## What was built

### The execution engine

`apps/api/app/modules/execution/` is the isolation plane:

| Module | Responsibility |
| --- | --- |
| `policies.py` | Profiles, per-type defaults and ceilings, `ALLOWED_OPTIONS`, `resolve_entrypoint`, and the two-layer `resolve_limits` clamp. |
| `validation.py` | Refuses an execution type, profile, option, oversized source or missing entrypoint before anything runs. |
| `adapters.py` | Turns a validated request into a concrete `SandboxSpec` — the fixed argv, the compile step, the pinned image, the capture bounds. |
| `orchestrator.py` | Drives one attempt through a backend and maps a `SandboxResult` to a job/attempt/event outcome. Backends are sync, offloaded with `asyncio.to_thread`. |
| `backends/` | `base` (the `SandboxSpec`/`SandboxResult` contract), `disabled`, `mock`, `docker`, and the `registry` that selects one from settings. |
| `service.py` | `create_job` / `run_inline` / `load_owned_job` / `list_jobs` / `cancel_job` / `job_detail`, source persistence and round-trip. |
| `queue.py` | `claim_job` (atomic CAS on `QUEUED`) and `recover_stale_jobs`. |
| `worker.py` | `python -m app.modules.execution.worker` — poll, claim, run, recover. |
| `events.py` | The append-only event stream and `metadata_json`. |
| `gateway.py` | `ExecutionGateway` / `ExecutionOutcome` / `ExecutionGatewayProtocol` — the agent's only door into the engine. |

### The three backends

- **`disabled`** — the default. Jobs are `REJECTED` with `POLICY_REJECTED`, cleanup `SKIPPED`. There
  is deliberately no host-exec option.
- **`mock`** — a deterministic, marker-driven in-process fake (`# @mock:stdout=`, `exit=`, `timeout`,
  `oom`, `artifact=<name>`). It never executes anything; it returns the outcome the source describes.
  This is what lets the whole engine be tested — exit/timeout/OOM classification, artifacts, queue
  recovery — on a machine with no Docker daemon.
- **`docker`** — the real path. One `docker run` line per attempt, hardened as above, driven through
  an injectable `CommandRunner` protocol so the exact argv is asserted in a unit test rather than
  assumed. Images are pinned per adapter (`python:3.12-slim`, `eclipse-temurin:21-jdk`, `gcc:14`) and
  an operator may only narrow the set.

### The lifecycle, modelled honestly

`ExecutionJobStatus` keeps the distinctions a boolean would erase: `CREATED → VALIDATING → QUEUED →
STARTING → RUNNING → COLLECTING_RESULTS → SUCCEEDED`, with `REJECTED`, `FAILED`, `TIMED_OUT`,
`CANCELLED`, `RESOURCE_LIMIT_EXCEEDED` as the other terminals and `CANCEL_REQUESTED` and
`CLEANUP_PENDING` as deliberately *non*-terminal states. `ExecutionCleanupStatus`
(`PENDING`/`CLEANED`/`FAILED`/`SKIPPED`) is a separate axis, so a job that produced correct output
but whose sandbox could not be destroyed is not reported as a clean success.

`ExecutionFailureClass` (`INVALID_REQUEST`, `POLICY_REJECTED`, `ENVIRONMENT_UNAVAILABLE`,
`STARTUP_FAILED`, `COMPILE_FAILED`, `USER_CODE_FAILED`, `TIMEOUT`, `RESOURCE_EXHAUSTED`,
`INFRASTRUCTURE`, `CANCELLED`) is what drives retry policy: infrastructure may be retried, user code
may not be (it may repeat side effects), and a timeout or resource kill is a policy outcome rather
than a bug. Exit code 137 becomes `RESOURCE_LIMIT_EXCEEDED`; a failed compile becomes `COMPILE_FAILED`
before anything runs.

### One event stream per job

`execution_events` is append-only and dense: `EXECUTION_REQUESTED`, `…_REJECTED`, `…_QUEUED`,
`SANDBOX_CREATED`, `…_STARTED`, `EXECUTION_COMPLETED`/`…_FAILED`, `SANDBOX_DESTROYED`,
`SANDBOX_CLEANUP_FAILED`, `EXECUTION_TIMED_OUT`, `EXECUTION_RESOURCE_LIMIT_EXCEEDED`,
`EXECUTION_CANCELLED`, and `POLICY_VIOLATION_DETECTED` for the cases that are a violation rather than
a normal failure. Events carry operational facts, never raw source or secrets.

### The web surface

`apps/web/components/assignment/execution-panel.tsx` mounts the execution plane on the assignment
page at `#execution`, alongside the agent workspace. It is built on the same conviction as the rest of
the UI: a student did not ask for a sandbox and should be able to see its edges.

- **The form submits source text and a runtime name, never a command.** There is no field for an
  image, a flag or a path, because the API has none either. The submit test asserts the request body
  carries `execution_type` and `files`, and *not* `command` or `image`.
- **The boundary is rendered, not implied.** `SandboxBoundary` prints the server's
  `absent_capabilities` verbatim, inside a disclosure with no controls — it is not a settings panel
  because there is no value to change.
- **A disabled or unreachable backend is stated, not hidden behind a dead button.** The two cases read
  differently (`disabledHelp` vs `unavailableHelp`), because "nothing is configured" and "nothing is
  reachable right now" are different facts.
- **A failure is not hidden.** Exit code, failure class and the tail of stderr stay on screen.
- **Reads and actions are separate.** `useExecution` re-reads on a 2s timer only while a job is
  non-terminal, and a failed action leaves the last good job on screen rather than blanking it.

The panel is keyed on the runtime list (`key={runtimes.join(",")}`) so its defaults follow what a
deployment actually offers, rather than an effect correcting state after the fact. Read failures,
action failures and a malformed capability payload are all handled without taking the page down.

The surface is four new modules plus three touched files:

- `apps/web/lib/execution-types.ts` — the Phase 7 vocabulary, mirroring `app/schemas/execution.py`,
  plus `isExecutionJobTerminal` (a predicate, so a new terminal status defaults to terminal rather
  than being polled forever).
- `apps/web/lib/use-execution.ts` — reads, capabilities, job list/detail, the activation poll, and the
  `submit`/`cancel` actions.
- `apps/web/lib/api.ts` — `executionCapabilities`, `createExecution`, `executionJobs`, `executionJob`,
  `cancelExecution`.
- `apps/web/components/assignment/execution-panel.tsx` — the panel (form, history, detail, boundary).
- `apps/web/components/assignment-detail.tsx` — mounts the panel at `#execution`.
- `apps/web/lib/i18n/messages.ts` — `execution.*`, `status.executionJob.*`, `status.executionAttempt.*`
  and `assignment.sections.execution` in both `en` and `fa`.
- `apps/web/tests/unit/execution-panel.test.tsx` (11) — the boundary rendering, disabled vs
  unreachable, the no-command submit, a failed run's exit code and stderr, terminal jobs hiding stop,
  polling, read/action failure retention, malformed capabilities, and the Persian locale.

### The database-backed queue

`claim_job` is a single `UPDATE execution_jobs SET status='STARTING', lock_version=lock_version+1,
lease_owner=?, lease_expires_at=? WHERE id=? AND status='QUEUED'`. Exactly one worker's update
matches; the rest see `rowcount == 0` and move on. `recover_stale_jobs` requeues a job whose lease
expired while attempts remain and fails it with `EXECUTION_WORKER_LOST` when they do not; a
`CANCEL_REQUESTED` job is moved to `CANCELLED`. This is the smallest correct coordination primitive
for a single-database deployment.

### Idempotency

An `idempotency_key` is unique per owner through a partial unique index (`sqlite_where` /
`postgresql_where` `idempotency_key IS NOT NULL`), mirroring `AgentRun`, so a retried submission
returns the original job rather than starting a second one.

### Quotas (§29)

A job could previously be submitted without bound, so one workspace or one student could occupy the
queue indefinitely. `create_job` now checks two ceilings after the idempotency lookup (so a retried
request is not punished for the retry): `execution_max_active_jobs_per_workspace` (default 8) counts
this workspace's non-terminal jobs, and `execution_max_jobs_per_user_per_day` (default 200) counts the
requester's jobs created in the last 24 hours. Exceeding either raises `ExecutionQuotaExceededError`
(429, `EXECUTION_QUOTA_EXCEEDED`) naming the `scope` and the `limit`. The check is *checked, not
reserved*: two concurrent requests can each see one slot free and both proceed. That is deliberate —
the queue and the sandbox caps are the hard bound, and a lock on the request path is a worse trade
than a blast-radius limit that is occasionally off by one.

### Named metrics (§31)

The event stream answers "what happened to this job"; it is the wrong shape for "how many jobs failed
this hour". `app/modules/execution/metrics.py` is the second shape: a tiny, dependency-free,
process-local registry of counters rendered in Prometheus text format. The orchestrator increments
`execution_jobs_total{status}`, `execution_attempts_total{outcome}`,
`execution_cleanup_total{status}`, `execution_jobs_rejected_total{reason}` and observes
`execution_job_duration_seconds`; the recovery sweep increments `execution_recovery_total{action}`.
Two limitations are documented rather than hidden: the counters are per process (scrape every replica
and worker) and reset on restart (they are for rates and alerting, not audit — the event stream is the
durable record). Call sites pass enum labels, never text, so no source or secret can reach a series.

### The external coding-agent seam (§19)

Phase 7 ships no bundled integration with an external coding agent, and says so rather than pretending
otherwise. `app/modules/execution/external_agent.py` defines the seam — an `ExternalAgent` protocol, an
`ExternalAgentRequest`/`ExternalAgentResult` pair, and three implementations: `DisabledExternalAgent`
(the default; reports `UNAVAILABLE` and runs nothing), `OpenCodeExternalAgent` (an honest placeholder
that reports `unavailable` because no client is bundled), and `MockExternalAgent` (deterministic,
marker-driven, for tests). `build_external_agent(settings)` selects one from
`execution_external_agent`, whose default is `disabled`. The agent reaches it only through
`DelegateToCodingAgentTool`, which holds the new `DELEGATE_EXTERNAL_AGENT` permission; with no agent
configured the tool answers "unavailable" rather than reaching for a subprocess. Outbound task and
file sizes are capped (`MAX_TASK_CHARS`, `MAX_FILE_CHARS`, `MAX_FILES`) before anything leaves.

### The deployed worker (§39)

`docker-compose.yml` gained an `execution-worker` service that runs the same image with
`python -m app.modules.execution.worker`, shares the upload volume, and waits on a healthy database and
the completed migrate step. Its `EXECUTION_BACKEND` defaults to `disabled`, so bringing the service up
is not the same as turning execution on. The compose file carries the standing warning that the Docker
socket is never mounted into a container — the API and worker build sibling containers through the
host daemon they are configured to reach, and that daemon is not exposed to the sandbox.

### The API

- `POST /api/v1/assignments/{id}/executions` — submit (sync inline or queued).
- `GET /api/v1/assignments/{id}/executions` — the assignment's jobs.
- `GET /api/v1/assignments/{id}/executions/{job_id}` — job detail with attempts, artifacts and events.
- `POST /api/v1/assignments/{id}/executions/{job_id}/cancel` — cancel.
- `GET /api/v1/executions/capabilities` — enabled, backend, actual availability, runtimes with
  adapters, the profile ceilings, the deployment maxima (including the per-workspace and per-user
  quota ceilings) and the external coding-agent seam. A disabled or unavailable backend is reported
  as such rather than omitted, so the UI can hide what is not there. The external coding agent is
  reported the same way (`external_coding_agent` in `absent_capabilities`) rather than silently
  dropped.
- `GET /api/v1/executions/metrics` — the named counters in Prometheus text format, gated by
  `execution_metrics_enabled` (`404 EXECUTION_METRICS_DISABLED` when off).

Nothing exposes a sandbox id or a host path.

### The agent's sandboxed tools

`app/modules/agent/execution_tools.py` adds three `HIGH`-risk tools — `execute_code`, `run_tests`,
`run_data_analysis` — each bound to a fixed runtime and holding the new `EXECUTE_SANDBOXED`
permission. `MAX_TOOL_RISK` rises from `MEDIUM` to `HIGH` — exactly enough to dispatch them, and not
a step further (`CRITICAL` host filesystem is still refused). A tool hands over text and the
`ExecutionGateway` it is given fixes everything else, so hostile arguments cannot widen the boundary;
without a gateway the tool answers "unavailable" rather than reaching for a shell. A non-zero exit is
returned as a usable-but-caveated result (`PARTIAL_SUCCESS` with the exit code and stderr), so the
model can react to a compiler error instead of the run treating the step as a dead end.

The CODE and DATA workers gained the sandbox tools and the `sandboxed_execution` capability. The
agent runtime builds a gateway in `_run_step` only when `settings.execution_enabled` is true and
passes it through `ToolContext.execution`.

### Migration

`alembic/versions/0012_phase7_execution.py` adds `execution_jobs`, `execution_attempts`,
`execution_artifacts` and `execution_events` with their indexes (including the partial idempotency
unique index), guarded by the metadata drift check in `tests/test_migrations.py`.

## Defects the completion work found and fixed

**`ABSENT_CAPABILITIES` still claimed `execute_code` was absent.** The capability endpoint would have
told a student the agent cannot run code in the same phase that shipped `execute_code`. The list now
says `host_code_execution` — the claim that is still true — and `filesystem_write_outside_sandbox`,
and the test asserting the old vocabulary now asserts the honest one.

**Four configuration knobs did nothing.** `execution_default_timeout_seconds`,
`execution_default_memory_mb`, `execution_default_cpus` and `execution_default_pids` were declared but
read by nothing; per-type defaults live in the resource profiles and every bound is applied there and
clamped against the `execution_max_*` ceilings. Removed rather than left as an untrue entitlement.

**A non-zero exit was modelled as a refusal.** The execution tools initially returned `BLOCKED` for a
non-zero exit, which reads as "the runtime refused" when it is really "the program answered". Changed
to `PARTIAL_SUCCESS` with a warning, so a failing test or a compiler error is information the model
can act on rather than a wall.

**Job status was assigned freely.** Every transition was a plain `job.status = ...`, so the vocabulary
was enforced only by the statements around it. Added `state_machine.py`, a data-driven table in the
shape of the agent run machine: terminal states have no exits, a running job moves to
`CANCEL_REQUESTED` before `CANCELLED`, and the queue's SQL compare-and-swap claim is the one edge kept
in both the SQL and the table so they cannot drift. Every status assignment in the orchestrator, the
service and the recovery sweep now goes through `assert_transition`.

## Quality gate verification

| Gate | Command | Result |
| --- | --- | --- |
| API lint | `ruff check app/ tests/ alembic/` | all checks passed |
| API types | `mypy app/` | clean, 150 source files |
| API tests | `pytest -q` | 498 passed, 1 skipped |
| API migration | `tests/test_migrations.py` | 10 passed |
| Web build | `npm run build` | production build clean |
| Web lint | `npm run lint` | clean, no warnings |
| Web types | `npm run typecheck` | clean |
| Web tests | `npm test` (vitest) | 170 passed (12 files) |

The suite grew by the Phase 7 tests:

- `tests/test_execution_engine.py` (26) — end-to-end mock runs, exit/timeout/OOM classification,
  artifact capture, disabled/rejected, traversal and unknown-option validation, policy clamps,
  idempotency, source round-trip, the queue CAS and recovery, cancel, backend selection, the two
  quota ceilings (and that a finished job frees its slot), and the named counters.
- `tests/test_execution_api.py` (11) — the endpoints, ownership scoping, capabilities (including the
  quota limits and the honest external-agent report), the metrics endpoint and its 404 when disabled.
- `tests/test_execution_sandbox.py` (11) — the Docker argv hardening, compile-fail classification,
  timeout and reap, empty-image rejection, adapter registry images and entrypoint refusal, and the
  execution tools with a fake gateway.
- `tests/test_execution_state_machine.py` (11) — the transition table is total, terminal states have no
  exits, a running cancellation must be requested first, the recovery and claim edges are legal, and an
  unknown stored status is corrupt rather than defaulted.
- `tests/test_external_agent.py` (10) — the seam runs nothing by default, the OpenCode placeholder is
  honestly unavailable, the mock scripts its outcome, the delegation tool is granted only its own
  permission, and delegation refuses without an agent, refuses an empty or oversized task, and returns
  the mock's success or partial result.
- `tests/test_execution_docker_live.py` — one real-container test, skipped unless
  `STUDYOS_EXECUTION_DOCKER=1`.

## What was not verified

- **No real container was run.** The Docker daemon was not available, so the hardened argv is
  asserted and the live test is gated behind `STUDYOS_EXECUTION_DOCKER=1`; the container path itself
  is unexercised here.
- **PostgreSQL was not available.** The whole suite ran on SQLite, so the partial-unique index and the
  row-locking claim path are correct in the schema but unexercised against a real engine.
- **No real model was ever called**, so the execution tools were exercised through a fake gateway, not
  through a provider deciding to call them.
- **The execution panel is verified against a mocked API, not a live one.** Its 11 unit tests assert
  the contract and behaviour (submit body, boundary rendering, disabled/unreachable states, polling,
  failure retention); no browser or end-to-end run against a real backend and sandbox was performed.

## Known limitations

- **Concurrency is one worker process by default.** `execution_worker_concurrency` exists but the
  safety argument for raising it is resource isolation rather than throughput, so the default is and
  stays 1.
- **CPU and memory caps on macOS.** Docker Desktop honours `--cpus` and `--memory` on Linux VMs; exact
  enforcement of fractional CPU on a host without cgroup quotas is weaker, which is why the pids and
  memory-swap caps are also present.
- **The `mock` backend is a test double, not a security boundary.** It is selected only by explicit
  configuration and never executes anything.

## Deferred, recorded honestly

These are the requirements the phase prompt raises that this implementation does **not** meet, kept
explicit so none is mistaken for done:

- **A live external coding agent is not bundled.** The seam (§19) is real — a protocol, an honest
  disabled default, a placeholder that reports itself unavailable, and a deterministic mock — but no
  request has ever reached a real OpenCode (or other) agent, because none was available to reach.
- **Java, C++ and Python have not run in a real container.** The adapters, their argv and their plans
  are unit-tested, but "execution works in an isolated environment" is unproven until the live test
  (`STUDYOS_EXECUTION_DOCKER=1`) has actually run.
- **No real model drove the sandboxed or delegation tools.** They were exercised through a fake
  gateway and the deterministic mock, not through a provider deciding to call them.

The per-workspace and per-user quotas (§29), the named metrics (§31) and the deployed
`execution-worker` service (§39) were completion-work gaps; they are now implemented and tested.

## Files changed

### Backend (new)

`apps/api/app/modules/execution/{policies,validation,adapters,events,state_machine,metrics,external_agent,orchestrator,service,queue,worker,gateway,router}.py`,
`apps/api/app/modules/execution/backends/{base,disabled,mock,docker,registry}.py`,
`apps/api/app/schemas/execution.py`,
`apps/api/app/modules/agent/{execution_tools,external_agent_tools}.py`,
`apps/api/alembic/versions/0012_phase7_execution.py`,
`apps/api/tests/{test_execution_engine,test_execution_api,test_execution_sandbox,test_execution_docker_live,test_execution_state_machine,test_external_agent}.py`.

### Backend (modified)

`apps/api/app/main.py` (wire the routers),
`apps/api/app/core/config.py` (execution settings; dropped the unused defaults),
`apps/api/app/models/{enums,entities,__init__}.py` (the execution tables and vocabulary),
`apps/api/app/modules/agent/{tools,workers,service}.py` (the sandboxed permission, the tool bindings
and the gateway construction),
`apps/api/app/modules/agent/router.py` (the honest `ABSENT_CAPABILITIES`),
`apps/api/tests/{test_agent_api,test_agent_domain_tools}.py`.

### Docs (new)

`docs/architecture/execution-isolation.md`,
`docs/development/adding-a-runtime.md` (how to add a runtime adapter),
`docs/development/adding-a-sandbox-backend.md` (how to add a sandbox backend).

### Docs (modified)

`docs/architecture/agent-tools.md` and `docs/architecture/agent-security.md` now describe the sandbox
as the one bounded exception rather than claiming code execution is absent.
`docs/architecture/execution-isolation.md` gains the state-machine, operating (including quotas,
metrics and the external-agent seam), dependency, and cleanup/recovery sections;
`docs/development/adding-agent-tools.md` names the sandboxed tools as the sole exception;
`README.md` stops claiming code execution is unimplemented.

### Web (new)

`apps/web/lib/execution-types.ts`,
`apps/web/lib/use-execution.ts`,
`apps/web/components/assignment/execution-panel.tsx`,
`apps/web/tests/unit/execution-panel.test.tsx`.

### Web (modified)

`apps/web/lib/api.ts` (the five execution methods),
`apps/web/lib/i18n/messages.ts` (`execution.*`, `status.executionJob.*`, `status.executionAttempt.*`
and `assignment.sections.execution`, in `en` and `fa`),
`apps/web/components/assignment-detail.tsx` (mount the panel at `#execution`).
