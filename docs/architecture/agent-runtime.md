# Agent Runtime

The agent runtime is Phase 5: the component that actually *does* the work an approved study plan
describes. Phases 3 and 4 read an assignment and proposed a plan; this phase walks that plan one
task at a time, produces drafts, and stops for a human whenever a decision is genuinely a human's.

It is a runtime, not a chatbot. There is no free-form conversation and no open-ended "what would you
like to do?". Every step is a task from an approved plan, and every step is bounded by a budget, a
tool registry that cannot grow, and a validation step that refuses model output it cannot vouch for.

## Where it sits

```
assignment
  └── AcademicWorkPlan            Phase 4, approved by the student
        └── AgentRun              Phase 5, one attempt at executing that plan
              ├── AgentExecution  one attempt at one task
              ├── AgentArtifact   a draft, kept at every revision
              ├── AgentCheckpoint a question, waiting on the student
              ├── AgentDecision   what the model chose, and what happened
              └── AgentEvent      the ordered audit trail
```

`AgentRun` binds to a specific `plan_id` and `plan_version` at creation. If the plan is regenerated
underneath it, the run continues against the version it was approved against rather than silently
switching to work the student never saw.

## The loop

`service.execute_run` drives a run:

1. **Select** the next runnable task. `selection.py` walks the dependency graph and picks work whose
   prerequisites are done, in priority order, skipping anything blocked.
2. **Route** a model for this step through the Phase 4 `ModelRouter`, so an agent run obeys the
   same routing rules and cost policy as analysis and planning.
3. **Assemble context** from the assignment specification, analysis, plan, prior artifacts, and
   checkpoint answers. `context.py` bounds it and records provenance for everything it used.
4. **Decide** what to do, in the form of one structured `AgentAction`.
5. **Execute** through a closed registry. Nothing outside it can be invoked.
6. **Validate** the output — schema, then semantics, then permission — and keep it as an
   `AgentExecution`, successful or not.
7. **Persist** any draft as an `AgentArtifact`, then record the decision, the event, and the audit
   entry.
8. Repeat until a budget, a question, a failure, or the end of the plan.

Steps run inline, one transaction each. A crash between steps leaves a consistent database and a
recoverable run; that was preferred over a background worker to keep the ordering guarantee
simple — a step's persistence completes before the next begins.

## Creating is not starting

`POST /agent/runs` creates a run. It does not start it. `POST /agent/runs/{id}/start` does that.

This is deliberate and the frontend depends on it: opening the workspace reads state and spends
nothing. A student can look at what the agent would do, and choose to supervise or not, without a
single model call.

## Two modes

- `SUPERVISED` — the run stops whenever a decision is genuinely the student's.
- `AUTONOMOUS` — the run continues to the next real wall: a question, a budget, or a failure.

Neither mode can exceed the configured ceilings, and neither can resolve a checkpoint without the
student.

## Budgets

Every run carries its own `max_iterations` and `max_cost`, seeded from settings and never raisable
above them from the client. Per-step and per-run cost ceilings, artifact counts, and a
`MAX_REVISIONS_PER_TASK` cap all bound a run independently, so no single limit is the only thing
between a bug and an unbounded bill.

Reaching the revision cap does not stop the run quietly. It opens a review checkpoint with real
options — keep revising, move on and leave the draft, or stop — because a runtime that silently
burns its budget is a runtime a student cannot trust.

## Failure is a state, not an exception

Every stop has a status, a reason, and an audit entry. `AgentFailureCategory` separates
`PROVIDER_UNAVAILABLE` from `BUDGET_EXHAUSTED` from `INVALID_OUTPUT`, because "the agent stopped"
is not something a student can act on and "the model is unavailable, try again" is.

When no provider is configured, the run degrades to the deterministic executors rather than failing
at the first step. The UI states when that happened, because a fallback presented as a model result
is the one failure mode the backend goes to real trouble to avoid.

## Related documents

- [`agent-state-machine.md`](./agent-state-machine.md) — every status and the legal transitions.
- [`agent-tools.md`](./agent-tools.md) — the closed capability registry.
- [`agent-context.md`](./agent-context.md) — what the agent may see, and how it is bounded.
- [`agent-security.md`](./agent-security.md) — the threat boundary and what it excludes.
- [`agent-recovery.md`](./agent-recovery.md) — reclaiming runs abandoned by a crash.