# How to add a sandbox backend (Phase 7)

A sandbox backend is the isolation boundary. It does exactly two things: it runs one `SandboxSpec`
(files, an optional compile command, a run command, and the limits) and it reaps a sandbox by id. It
never sees the database, never writes artifacts and never decides policy — those are the
orchestrator's. Keeping the interface this narrow is what lets the backend be replaced without touching
the agent runtime, and makes "is this safe?" a question about one file.

The current backends are `disabled` (the default — refuses rather than runs), `mock` (a deterministic
test double) and `docker` (the hardened rootless container).

## The contract

`apps/api/app/modules/execution/backends/base.py`:

- `SandboxSpec` — the job id, the resolved image, the files to materialise, the optional compile argv,
  the run argv, the working dir, and every limit (`timeout_seconds`, `memory_mb`, `cpus`, `pids`,
  `max_output_bytes`, `max_artifact_bytes`, `max_artifacts`), plus optional environment and stdin.
- `SandboxResult` — what the run observed: a status, exit code, bounded stdout/stderr, duration, a
  sandbox id, a failure class, resource usage, captured artifacts and diagnostics.
- `SandboxBackend` — `kind`, an `available` probe, `run(spec)`, `reap(sandbox_id)`.

Two invariants a backend must honour:

- **`run` must not raise for a bounded outcome.** A timeout, a compile error and a resource kill are
  normal results to be classified, not exceptions. An unexpected raise is an infrastructure bug.
- **`reap` is idempotent and truthful.** It returns `True` only when the sandbox is actually gone, so a
  cleanup failure surfaces instead of being assumed away.

## Choosing a technology

Do not pick one because it is popular. Evaluate it against the load it will carry:

| Criterion | Question |
| --- | --- |
| Threat model | What is it defending against — a curious student, or an actively malicious workload? |
| Isolation guarantee | What is the actual boundary: namespaces, a user-space kernel, a hardware VM? |
| Operational complexity | What must be installed, daemonised and privileged on every worker host? |
| Compatibility | Does the academic runtime (Python/Java/C++) work unmodified? |
| Startup latency | How long from spec to first instruction, and does it fit the poll budget? |
| Resource overhead | Memory and CPU cost per idle sandbox. |
| Cost | Infrastructure and engineering cost to run and to keep patched. |
| Observability | Can you see the sandbox, its exit and its logs from the worker? |
| Orchestration | What API manages its lifecycle, and how is that interface protected? |

A hardened rootless container is a reasonable first boundary for low-risk workloads **provided its
limitations are documented**. Against actively malicious workloads, evaluate a user-space kernel
(gVisor) or a microVM (Firecracker); do not claim that a container is equivalent to either.

Document the residual risk and the conditions under which a stronger boundary is required, in
[`../architecture/execution-isolation.md`](../architecture/execution-isolation.md).

## 1. Add the kind

Add the value to `ExecutionBackendKind` in `apps/api/app/models/enums.py`. The kind is recorded on the
job and the attempt so "which boundary served this run" stays answerable after the fact.

## 2. Implement the protocol

Add a module under `apps/api/app/modules/execution/backends/`. Keep the capability probe honest: if the
daemon or runtime is missing, `available` must report `False` so the job is rejected cleanly rather
than retried in a storm.

```python
class MySandboxBackend:
    kind = ExecutionBackendKind.MY_BACKEND

    @property
    def available(self) -> bool:
        ...

    def run(self, spec: SandboxSpec) -> SandboxResult:
        ...

    def reap(self, sandbox_id: str) -> bool:
        ...
```

Give the backend an injectable seam for its process or API calls (the way `DockerSandboxBackend`
takes a `CommandRunner`) so the exact command or request can be asserted in a unit test without the
real infrastructure. Never let the backend read the database, write artifacts or read policy — those
belong to the orchestrator.

## 3. Register it

- Add the branch to `build_backend()` in `backends/registry.py`. The mapping must stay total and
  closed: a configuration value selects a code path that exists in that file, and nothing else. The
  default stays `DisabledSandboxBackend`.
- Widen the `execution_backend` `Literal` in `apps/api/app/core/config.py`.

## 4. Test it

- **By construction (always):** a unit test that asserts the boundary flags or equivalent hardening the
  backend emits. See
  `tests/test_execution_sandbox.py::test_the_docker_run_is_hardened_by_construction`.
- **Live (opt-in):** one representative run behind an environment gate, so the boundary can be checked
  on a host that has the infrastructure. A backend that has never run a real spec is not supported;
  say so in the phase report until it has.

## Checklist

- [ ] `ExecutionBackendKind` value added.
- [ ] Protocol implemented; `available`, `run`, `reap` truthful and non-raising for bounded outcomes.
- [ ] Injectability seam added for testability.
- [ ] Registered in `registry.py`; `execution_backend` `Literal` widened; default still `disabled`.
- [ ] Hardening asserted by construction in a unit test; live test added or deferred.
- [ ] Residual risk and the conditions needing a stronger boundary documented.
- [ ] Backend does not touch the database, artifacts or policy.
