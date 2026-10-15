# Execution Isolation

Phase 7 lets StudyOS *run* code. This document is the boundary for that: what may run, where it runs,
what it is not allowed to reach, and why "the backend is the sandbox" is a claim that is checked
rather than assumed.

The rule the rest of the system is built on does not change. The model is not trusted. Phase 7 does
not widen what the model may decide — it adds one capability with its own permission and its own
ceiling, and it runs the result somewhere the rest of the system is not.

## The shape of a request

A caller — the API or an agent tool — submits *source text*, not a command. The request names:

- an **execution type** (`PYTHON`, `JAVA`, `CPP`, `DATA_ANALYSIS`, …), which selects an adapter;
- the **source files** as text, plus optionally an entrypoint filename;
- a bounded set of **options** (`args`, `stdin`, and at most a `main_class`, `standard`, `target` or
  `framework` depending on the type);
- optionally a resource **profile** and a *shorter* timeout.

It cannot name a command, an argv, an image, a path, an environment variable, a mount, a `--flag`, or
a resource number larger than policy allows. The schema has no such field, and every option that
*does* exist is consumed by an adapter rather than passed to a shell: `args` becomes a list appended
to a fixed argv, `stdin` is fed to the process, `main_class`/`target`/`framework` select among
code-built templates. `VALIDATION` refuses an option outside `ALLOWED_OPTIONS[type]`, so "add a
flag" is not a way to reach the shell.

## The backend determines the boundary

`ExecutionBackendKind` is recorded per job so an operator can tell which boundary a run actually sat
behind.

| Kind | What it means |
| --- | --- |
| `DISABLED` | The default. There is no boundary, so jobs are `REJECTED` with `POLICY_REJECTED` and cleanup is `SKIPPED`. Nothing runs. |
| `DOCKER` | The hardened rootless container. The real path. |
| `MOCK` | A deterministic, marker-driven backend used in tests. It never executes anything; it reads directives like `# @mock:stdout=...` from the source and returns the described outcome. |

The choice is made in `backends/registry.py` from settings. Crucially, "no backend configured" is
`DISABLED` — not "fall back to running it directly". A deployment that has not opted into a sandbox
does not have an implicit one.

### The hardened container

`backends/docker.py` builds one `docker run` line and every flag on it is a boundary:

```
--network none                 no egress, no ingress
--read-only                    the root filesystem cannot be written
--tmpfs /tmp:rw,exec,size=256m a bounded, disposable scratch space for compiler output
--cap-drop ALL                 no Linux capabilities at all
--security-opt no-new-privileges   setuid binaries cannot regain privilege
--user 65534:65534             runs as nobody, never as the daemon's user
--memory / --memory-swap       equal values, so memory cannot spill to swap
--cpus                         a hard CPU share
--pids-limit                   a fork-bomb ceiling
-v <workdir>:/workspace:rw     the only host path the container sees
```

`--rm` plus a `reap()` fallback plus a `finally` that deletes the host workspace means the environment
is reclaimed on every path, including the timeout and compile-failure paths. The Docker socket is
never mounted into a container, so a job cannot ask Docker to start anything: the only thing that
speaks to the Docker API is the backend process itself.

**Why the tmpfs is executable.** Compiled C++ and Java need a writable, executable directory. The
workspace mount is already executable and the container is disposable, so `exec` on `/tmp` grants
nothing an attacker could not already do inside the boundary — while `noexec` there would make Java
and C++ impossible. The trade-off is stated here rather than hidden.

### Images are pinned

Images are chosen by adapter constant (`python:3.12-slim`, `eclipse-temurin:21-jdk`, `gcc:14`).
An operator may only *narrow* the set with `execution_allowed_images`; a request cannot name an image
at all. An empty resolved image is `REJECTED` (`EXECUTION_NO_IMAGE`), never "run the default".

## Resources are ceilings, clamped twice

A profile (`LIGHT_COMPUTATION` … `BUILD_EXECUTION`) carries a *shape* — a 10s/256MB note-taking
compute is not given a build's 180s/2GB, and a build is not starved at half a core. That shape is
then clamped against the operator's configured maxima in `Settings`. A client may only ask for a
*shorter* timeout; a longer one is clamped down rather than refused, because the caller asked for
more than policy grants and the maximum it may have is both safe and more useful than an error.

The resolved `ResourceLimits` are snapshotted onto the attempt (`as_dict`) so a later configuration
change cannot rewrite the terms a past run was executed under.

## Failure is classified, not flattened

`ExecutionFailureClass` says *where* a failure fell, which is what drives retry policy:

- `INVALID_REQUEST` / `POLICY_REJECTED` — refused before anything ran.
- `ENVIRONMENT_UNAVAILABLE` / `STARTUP_FAILED` / `INFRASTRUCTURE` — infrastructure; potentially
  retryable.
- `COMPILE_FAILED` — the compiler rejected the source; distinct from a runtime failure so the UI can
  point at a compile step.
- `USER_CODE_FAILED` — the program exited non-zero. Never retried blindly: it may repeat side effects.
- `TIMEOUT` / `RESOURCE_EXHAUSTED` — a policy outcome, not a bug.

A non-zero exit is the *program's* answer, not the runtime's error: exit code 137 becomes
`RESOURCE_LIMIT_EXCEEDED` (the sandbox killed it), a compile error becomes `COMPILE_FAILED`, and a
plain non-zero exit becomes `USER_CODE_FAILED`. None of these is silently retried as though it were a
transient fault.

## Cleanup is a separate axis from status

`ExecutionCleanupStatus` (`PENDING`/`CLEANED`/`FAILED`/`SKIPPED`) is tracked apart from the job
result. A job that produced correct output but whose sandbox could not be destroyed is not a success
with a footnote; it is an operationally significant state. `CLEANUP_PENDING` is deliberately *not* a
terminal job status — a job can be complete while its environment is still being reclaimed. Modelling
cleanup separately is what stops "the process exited" from being reported as "the environment is
gone".

## The queue is the database

There is no Celery and no Redis. A queued job is a row, and claiming it is a single conditional
`UPDATE ... WHERE status = 'QUEUED'` that also bumps `lock_version`, sets the lease owner and the
lease expiry. Exactly one worker's update matches, so exactly one worker wins; the others see
`rowcount == 0` and move on. A worker that dies is recovered by a sweep that requeues the job while
attempts remain and marks it `FAILED` with `EXECUTION_WORKER_LOST` when they do not. `CANCEL_REQUESTED`
is honoured by the same sweep. This is the smallest correct coordination primitive for a
single-database deployment, and it makes "who is running this job" a query rather than a hope.

## Status is a closed state machine

`ExecutionJobStatus` moves only along the edges in `state_machine.py`, a data table in the same shape
as the agent run machine. Terminal states (`SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELLED`,
`RESOURCE_LIMIT_EXCEEDED`, `REJECTED`) have no exits — a finished execution is a record, not a shell you
can re-enter; a retry is a new job. A *running* attempt does not jump to `CANCELLED`: it moves to
`CANCEL_REQUESTED`, and only the worker (or the recovery sweep) that actually stops it may set
`CANCELLED`. The queue's compare-and-swap claim is the single edge performed in SQL, kept in the table
too so the two cannot drift.

## Telemetry is append-only

Every job writes a dense, append-only event stream (`EXECUTION_REQUESTED`, `…_REJECTED`, `…_QUEUED`,
`SANDBOX_CREATED`, `…_STARTED`, `EXECUTION_FAILED`/`…_COMPLETED`, `SANDBOX_DESTROYED`,
`SANDBOX_CLEANUP_FAILED`, and `POLICY_VIOLATION_DETECTED` for the cases that are a violation rather
than a normal failure). These are operational and security events, never raw source or secrets — a
compiler error is an `EXECUTION_FAILED`, not a `POLICY_VIOLATION_DETECTED`. Output and artifacts are
bounded at capture (`max_output_bytes`, `max_artifact_bytes`, `max_artifacts`), so a program that
prints a gigabyte cannot turn into a gigabyte of stored telemetry.

## What the agent may and may not do

The three execution tools (`execute_code`, `run_tests`, `run_data_analysis`) hold
`EXECUTE_SANDBOXED`, which is distinct from the forbidden `EXECUTE_UNTRUSTED`. They are `HIGH` risk,
which is the Phase 7 ceiling — `CRITICAL` (host filesystem) is still refused. A tool names a runtime
and hands over text; the `ExecutionGateway` it is handed fixes the workspace, backend, image and
profile, so the tool has no way to widen the boundary even if the model's arguments are hostile. When
no gateway is present the tool answers "unavailable" rather than reaching for a shell.

A fourth tool, `delegate_to_coding_agent`, holds `DELEGATE_EXTERNAL_AGENT` instead. It is the only door
to the external-agent seam (§19), which ships disabled: the tool reaches no subprocess, and its task
and files are capped before anything is handed over.

## Operating it

Two settings decide whether anything can run at all:

- `execution_enabled` gates job creation. Creation is refused when it is off — the workspace shows
  why rather than a dead button.
- `execution_backend` selects the boundary: `disabled` (the default), `docker`, or `mock`. There is
  no value that runs code on the host.

Around those, `execution_allowed_images` may only *narrow* the pinned image set, `execution_docker_host`
points at a non-default daemon, and the `execution_max_*` ceilings clamp every per-type profile. The
queue is drained by one process:

```bash
python -m app.modules.execution.worker
```

The hardened-argv unit tests need no daemon; the one live container test is skipped unless
`STUDYOS_EXECUTION_DOCKER=1`, so the container path can be exercised deliberately on a machine that has
one.

The worker needs access to the isolation backend (the Docker daemon, for the `docker` kind) and nothing
else — least privilege means *not* running the API process with that access. It is a separate process
and runs as a separate service: `docker-compose.yml` ships an `execution-worker` service that runs the
same image with `python -m app.modules.execution.worker`, waits on a healthy database and the completed
migrate step, shares the upload volume, and leaves `EXECUTION_BACKEND` at `disabled` so bringing the
service up is not the same as turning execution on. The Docker socket is never mounted into the API
container.

Two ceilings bound how much a deployment will run at once. `execution_max_active_jobs_per_workspace`
(default 8) caps this workspace's non-terminal jobs, and `execution_max_jobs_per_user_per_day`
(default 200) caps one requester's jobs in a rolling 24 hours; exceeding either is a `429`
(`EXECUTION_QUOTA_EXCEEDED`) naming the scope. The quota is *checked, not reserved* — the queue and the
per-job resource caps are the hard bound, and the quota is a blast-radius limit that may be off by one
under a race.

`execution_metrics_enabled` (default true) exposes `GET /api/v1/executions/metrics` in Prometheus text
format: `execution_jobs_total{status}`, `execution_attempts_total{outcome}`,
`execution_cleanup_total{status}`, `execution_jobs_rejected_total{reason}`,
`execution_job_duration_seconds` and `execution_recovery_total{action}`. The counters are per process
and reset on restart — scrape every API replica and worker, and treat them as rates and alerts, not as
audit. The event stream remains the durable record.

An external coding agent is off by default. `execution_external_agent` is `disabled`, and with it the
`delegate_to_coding_agent` tool answers "unavailable" rather than spawning anything; `mock` is for
tests and `opencode` is an honest placeholder that reports itself unavailable because no client is
bundled. The capability endpoint reports the seam's state instead of hiding it.

## Dependencies

There is no dependency installation in Phase 7, by design. A sandbox has no network, so a job cannot
reach a package registry, and no credential is exposed that could. This is deliberate: `pip install`
inside an untrusted run is both a code-execution vector (build scripts, hooks, metadata) and an
unbounded-network hole.

Dependencies are therefore **baked into the image**, not fetched at run time:

- For a vetted set of libraries, extend the pinned image and bump its tag or digest in
  `apps/api/app/modules/execution/adapters.py`; the operator's `execution_allowed_images` only narrows
  what is served.
- For a larger standard library, build a purpose-made runtime image and pin it the same way. The image
  must not carry production credentials, and it is the unit that is vulnerability-scanned and patched.

Explicitly deferred to a later phase: approved package registries, dependency caches, lockfile-driven
installs, and package-acquisition jobs. If one is added, it must run inside an isolated environment,
treat package metadata, build scripts and downloaded archives as untrusted, verify artifacts, bound
their size, and never expose production secrets to the installer. Until then, a workload that needs a
library the pinned image does not carry is a rejection, not a silent download.

## Cleanup, recovery and incidents

**Cleanup is a separate fact from the result.** A job whose code exited cleanly can still have failed to
destroy its environment; that is `cleanup_status = FAILED`, not a success. On timeout the container is
reaped before the result is returned, and the workspace directory is removed in a `finally`, so a
sandbox does not survive its own run.

**A persisted `RUNNING` does not prove a process is running.** A worker that dies mid-job leaves the
row behind; the lease sweep (`recover_stale_jobs`) reclaims jobs whose lease has expired and marks the
attempt failed with `EXECUTION_WORKER_LOST`, honouring any `CANCEL_REQUESTED`. Never assume a status is
ground truth about the infrastructure.

**Finding a leaked sandbox.** Containers are named `studyos-exec-<job_id>`. To find orphans:

```bash
docker ps --filter "name=studyos-exec-"
```

Reap one with `docker rm -f <name>`; the backend's `reap` is idempotent and safe to repeat. A cleanup
failure is recorded as `SANDBOX_CLEANUP_FAILED` in the job's event stream with `cleanup_status = FAILED`,
which is the signal to investigate — it is not swallowed.

**Ordinary failure is not intrusion.** A compiler error or a non-zero exit is an `EXECUTION_FAILED`, not
a `POLICY_VIOLATION_DETECTED`. Only a rejected request, an out-of-policy option or a boundary the job
tried to cross is a violation. Read the event stream to tell them apart; it never contains raw source or
secrets.

See [`agent-tools.md`](./agent-tools.md) for the tool catalogue,
[`agent-security.md`](./agent-security.md) for the surrounding threat model, and
[`../development/adding-a-runtime.md`](../development/adding-a-runtime.md) /
[`../development/adding-a-sandbox-backend.md`](../development/adding-a-sandbox-backend.md) for how to
extend the runtimes and the boundary.
