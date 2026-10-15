# Agent Security

This document is the threat boundary for the Phase 5 runtime. It states what the system cannot do,
what would happen if the model were fully compromised, and which assumptions the design leans on.

## The short version

The model is not trusted. It does not decide what happens. It proposes a structured action, and
code that did not come from the model decides whether that action is allowed.

If the model output a malicious string on every field of every response, the worst outcome is refused
runs and visible errors.

## What is structurally absent

These are not disabled by default. They are not in the codebase:

- **Shell or subprocess execution on the host.** No `subprocess`, no `os.system`, no shell invocation
  runs a command the model chose on the host. The only process the runtime starts is the sandbox
  backend (Phase 7) and it starts it with a fixed, code-built command line.
- **Outbound network access.** No HTTP client in the agent path, and a sandbox runs with
  `--network none`. The only network egress is the configured LLM provider.
- **Filesystem writes outside the sandbox.** `write_artifact` writes one row in the application's own
  database. An execution writes into an ephemeral, per-job directory that is deleted when the attempt
  ends. Uploads go through the Phase 2 storage abstraction.
- **Host filesystem code execution.** Model-authored code runs only inside the Phase 7 sandbox, never
  on the host. The sandbox runs as an unprivileged user with a read-only root, dropped capabilities
  and `no-new-privileges`, so "a code tool exists" does not become "code runs as the server". See
  [`execution-isolation.md`](./execution-isolation.md) and the `HIGH` risk ceiling below.
- **Credential access.** No runtime path reads a secret other than the provider's own API key, held
  in settings. A sandbox is handed no environment variables and no host mounts beyond its workspace.
- **A browser or web-search tool.** No such tool is registered.
- **Cross-assignment data.** Every read is filtered by the assignment resolved from ownership. There
  is no identifier the client can supply to widen the scope.

The list is published as data by `GET /assignments/{id}/agent/capabilities` and rendered in the UI.
See [`agent-tools.md`](./agent-tools.md).

## The sandbox is the one exception, and it is bounded

Phase 6's claim was "no code execution anywhere". Phase 7 narrows that claim rather than dropping it:
the runtime may *submit* code, and the submission has a fixed shape.

- A code tool names a **runtime** (`python`, `java`, `cpp`) and hands over **text**. It cannot name a
  command, an image, a path, an environment variable or a resource limit — the schema has no such
  field, and the `ExecutionGateway` it is handed fixes the workspace, backend, image and profile.
- The permission is `EXECUTE_SANDBOXED`, deliberately distinct from `EXECUTE_UNTRUSTED` (host
  execution), which remains in `FORBIDDEN_PERMISSIONS` and is held by no tool.
- The risk ceiling is `HIGH` as of Phase 7 — exactly enough to dispatch the sandbox tools. `CRITICAL`
  (host filesystem) is still refused, and raising the ceiling was a reviewed change in the phase that
  shipped the sandbox, not a permission a tool can obtain by declaring it.
- A request may only *shrink* a resource profile. The profile is a ceiling clamped again by the
  operator's configured maxima, so neither an edit to a constant nor a client request can widen it.
- Everything an execution does is recorded: a job, an attempt, its exit code, its failure class, its
  bounded output and a dense event log. A failed program is classified (`USER_CODE_FAILED`,
  `COMPILE_FAILED`, `TIMEOUT`, `RESOURCE_EXHAUSTED`), never silently retried as though it were a
  transient fault.

## The three validation layers

A model's response passes three independent checks before anything is persisted or acted on. They are
in `decisions.py` and they are separate functions on purpose: one layer catching another's failure is
how a validation system ends up with one layer.

**1. Schema.** `parse_decision` parses the raw response into `AgentDecisionOutput`. Malformed JSON,
unknown actions, wrong types, and missing required fields are rejected here. This is the layer that
stops a model from inventing a field the runtime would then trust. A `CALL_TOOL` decision with no
`tool` is rejected here.

**2. Semantics.** `validate_semantics` checks the decision makes sense in context:

- `COMPLETE_TASK` must name a task that is actually the current one.
- `REQUEST_APPROVAL` requires a checkpoint type that means approval.
- `PAUSE_RUN` is refused in `AUTONOMOUS` mode — the mode exists to run to the next real wall, so a
  model pausing itself on a whim would defeat it.
- Low-confidence decisions are refused for the actions where being wrong is expensive.
- `CALL_TOOL` must name a tool that is actually registered. A tool the model invents is
  `AGENT_TOOL_UNKNOWN` — nothing is dispatched, so "invent a tool" cannot become "invent an action".

**3. Permission.** `validate_permissions` is the layer that exists because the first two can both
pass and still be wrong. It checks the decision against what this run is allowed to do: the tool
registry's permissions, the closed executor set, and the plan's own task list. A `CALL_TOOL` whose
tool declares any permission outside the run's granted set is `AGENT_TOOL_PERMISSION_DENIED`, and
`invoke_tool` enforces the same granted set again at dispatch.

All three raise `DecisionRejected`, which becomes a recorded `AgentExecution` with
`failure_category = VALIDATION_ERROR` — not an exception that loses the run. A rejected decision is
data.

## Injection

Student-supplied text — the brief, requirements, reference material — is wrapped in untrusted markers
and labelled as data to analyse rather than instructions. Details in
[`agent-context.md`](./agent-context.md).

The honest framing: this raises the cost of injection, it does not eliminate it. A sufficiently
persistent payload in a student's own document might still influence output. The defence that
actually holds is structural — an injected instruction can change *what text gets written into a
draft*, and cannot change *what runs*, *what is called*, or *what is reachable*.

## Output is never trusted either

Draft content is rendered as text in the UI, never as HTML, and never executed. `CODE` artifacts are
stored as text and are the student's to run themselves, in their own environment, on their own
machine — which is the correct place for that.

## Authorization

Every endpoint resolves ownership from the authenticated session. Clients never supply a workspace,
owner, or user identifier.

A run or checkpoint belonging to another student returns `404`, not `403` — the API does not confirm
that an identifier exists.

The recovery endpoint is scoped to the assignment in the path. This was a real defect found during
Phase 5: recovery originally swept every stale run in the database, so a button on one assignment
could have paused another student's work. `find_stale_runs` and `expire_checkpoints` now take an
optional `assignment_id` and the router always passes it. Both behaviours are pinned by tests in
`tests/test_agent_api.py`.

## Budgets as a security property

Every run has iteration and cost ceilings that cannot be raised from the client. Lowering a ceiling
is allowed; raising it above the configured maximum is refused with a validation error.

This matters because an agent that loops is a denial-of-wallet, and the client is the party that
would benefit from an unbounded run.

## What is audited

Every state change, decision, checkpoint, and artifact writes an `AuditEvent` in the
`AGENT_*` family, with the workspace, entity, and actor. Recovery events carry `user_id = None`,
because no user performed them — attributing a system sweep to whoever happened to trigger it would be
a lie in an audit log.

`AgentEvent` is a separate, ordered, per-run trail with a unique `(run_id, sequence)` constraint. The
sequence is enforced in the database, not just in application code, so two concurrent writers cannot
produce duplicate or interleaved-gap trails.

## No chain-of-thought is stored

The runtime never requests internal reasoning and never persists any. `AgentDecisionResponse` has a
`reason` — one sentence, written for the student — and no field for a chain of thought, because
there is no such thing to store.

## Known limitations

Stated plainly rather than left to be found:

- **Delimited untrusted context is a mitigation, not a guarantee.** See above.
- **No defence against a determined student attacking their own account.** A student can always
  start an expensive run; the ceilings bound the damage, they do not prevent intent.
- **The deterministic fallback can produce lower-quality work.** It is preferred to failing, and it
  is always reported as what it is.
- **Single-node correctness.** Steps run inline in the request. `lock_version` guards concurrent
  writers, and PostgreSQL's `SELECT ... FOR UPDATE` gives row-level exclusion, but there is no
  distributed worker queue yet.