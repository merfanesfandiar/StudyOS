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

- **Shell or subprocess execution.** No `subprocess`, no `os.system`, no shell invocation anywhere in
  the runtime.
- **Outbound network access.** No HTTP client in the agent path. The only network egress is the
  configured LLM provider.
- **Filesystem writes.** `write_artifact` writes one row in the application's own database. It does
  not touch the filesystem. Uploads go through the Phase 2 storage abstraction.
- **Arbitrary code execution**, including model-authored code. `CODE` is an artifact type; running it
  is not a capability.
- **Credential access.** No runtime path reads a secret other than the provider's own API key, held
  in settings.
- **A browser or web-search tool.** No such tool is registered.
- **Cross-assignment data.** Every read is filtered by the assignment resolved from ownership. There
  is no identifier the client can supply to widen the scope.

The list is published as data by `GET /assignments/{id}/agent/capabilities` and rendered in the UI.
See [`agent-tools.md`](./agent-tools.md).

## The three validation layers

A model's response passes three independent checks before anything is persisted or acted on. They are
in `decisions.py` and they are separate functions on purpose: one layer catching another's failure is
how a validation system ends up with one layer.

**1. Schema.** `parse_decision` parses the raw response into `AgentDecisionOutput`. Malformed JSON,
unknown actions, wrong types, and missing required fields are rejected here. This is the layer that
stops a model from inventing a field the runtime would then trust.

**2. Semantics.** `validate_semantics` checks the decision makes sense in context:

- `COMPLETE_TASK` must name a task that is actually the current one.
- `REQUEST_APPROVAL` requires a checkpoint type that means approval.
- `PAUSE_RUN` is refused in `AUTONOMOUS` mode — the mode exists to run to the next real wall, so a
  model pausing itself on a whim would defeat it.
- Low-confidence decisions are refused for the actions where being wrong is expensive.

**3. Permission.** `validate_permissions` is the layer that exists because the first two can both
pass and still be wrong. It checks the decision against what this run is allowed to do: the tool
registry's permissions, the closed executor set, and the plan's own task list.

All three raise `DecisionRejected`, which becomes a recorded `AgentExecution` with
`failure_category = INVALID_OUTPUT` — not an exception that loses the run. A rejected decision is
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