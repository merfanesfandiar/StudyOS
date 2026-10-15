"""Phase 7: the secure execution environment.

This package is the only place in StudyOS where untrusted code runs. It is built
around one refusal: there is no code path that executes a workload on the host.
Every execution is handed to a :class:`~app.modules.execution.backends.base.SandboxBackend`,
and the default backend is ``disabled`` — it rejects jobs rather than run them.
A deployment that wants execution opts into a hardened, network-less container
explicitly; there is no configuration that turns the sandbox off while leaving
execution on.

The pipeline is deliberately explicit and each stage is its own module:

* ``policies`` / ``validation`` — what is allowed, bounded by resource profile.
* ``adapters`` — turn a validated request into a fixed, versioned command. A
  client names a runtime, never a host executable.
* ``backends`` — the isolation boundary (disabled, mock, hardened docker).
* ``orchestrator`` — validate → authorize → queue → run → collect → artifact →
  cleanup → classify.
* ``queue`` / ``worker`` — the database is the queue; a job is claimed by a
  compare-and-swap, so a redelivered claim cannot start two sandboxes.
* ``gateway`` — the narrow interface the agent runtime is handed.
"""
