# The Academic Planning Engine

Phase 4 turns an analyzed assignment into a plan a student can actually
execute: layered tasks, an explicit dependency graph, effort and schedule
estimates, milestones, and a human review step before anything becomes
authoritative.

## The one thing to understand

**A plan is a proposal, never an instruction.**

The system always ends up with a valid plan, but it is honest about which
engine produced it. A model that is unreachable, returns prose, or returns a
plan containing a cycle does not produce a worse plan for the student — it
produces the *deterministic* plan, and the run records that fact:

```json
{
  "used_fallback": true,
  "rejection_reasons": ["the model call failed: LLM_UNAVAILABLE"]
}
```

Those two fields are persisted on the plan, not just returned in the response.
A fallback that is visible only in the API response is invisible in the record
three months later, which is exactly when someone asks why the plan looks like
that.

## Pipeline

```
AssignmentSpecification
        │  (read-only; planning never re-reads it)
        ▼
AssignmentAnalysis ──── normalized_requirements, deliverables, work areas
        │
        ▼
PlanningContractResponse  ← the frozen, structured contract
        │
        ├──▶ score_complexity ──▶ ModelRouter ──▶ tier: advanced | efficient
        │                              │
        │                              ▼
        │                       LLM proposal (PlannerOutput JSON)
        │                              │
        │                        validate_graph ─── fails ──┐
        │                              │ passes            │
        ▼                              ▼                   ▼
   synthesize_plan  ◄─────────── (used as the floor)  rejections recorded
        │
        ▼
   validate_graph ──▶ persist_plan ──▶ AcademicWorkPlan (version N)
                                              │
                                              ▼
                                     human review ──▶ APPROVED
```

Planning reads the analyzer's output and never re-reads the specification, so
the two cannot disagree about what was asked for.

## The deterministic engine is the floor

`synthesize_plan` in `app/modules/planning/planner.py` is a complete planner in
its own right. It is not a stub that fills in when a model is missing. The
layering is domain logic, not a template:

| Layer | What it produces |
|---|---|
| Orient | Understand the material, identify what is being asked |
| Develop | The actual work, one task per requirement or work area |
| Assemble | One task per deliverable, with its format and acceptance criteria |
| Verify | Coverage, consistency, citation and source-quality checks |

Task cap (`planning_max_task_count`) truncates the develop layer and records
what was dropped as an `INFO` risk, rather than silently omitting it.

## Complexity and routing

`score_complexity` produces a weighted 0–100 score from requirement count,
deliverable count, work-area count, ambiguity and contradiction counts, and
longest dependency-chain depth. Each contributes a capped factor and a
human-readable reason, so the score explains itself rather than being a number
that appears from nowhere. The router maps it plus the student's `ai_mode` to a
tier.
Both tiers come from settings, so the routing decision is visible in
configuration rather than hidden in a table.

Routing decides *which* model to ask. It is a separate concern from *whether*
to fall back, and conflating them is how you end up with a "fallback" that was
really just a cheaper model call that nobody told the student about.

## The graph is the authority

Each task maps to `depends_on` (its prerequisites). The invariant is
predecessor-first ordering: a task never appears before something it depends on.

Refused, with the reason returned to the client:

- duplicate task keys
- self-dependency
- dangling references to keys that do not exist
- cycles
- a task, milestone, verification point or risk referencing an unknown key
- a task referencing an unknown requirement or deliverable
- a **required, explicitly-sourced requirement** with no task addressing it
- a required deliverable with no task contributing to it

The last two are the checks that matter most: a plan that validates
structurally but does not cover the brief is not a plan. They are scoped to
`required` and `source_kind == EXPLICIT` deliberately, so an inferred
requirement the analyzer was unsure about cannot make an otherwise sound plan
unplannable.

Validation reads the graph **as stored**, re-queried from the session rather
than trusted from the objects the caller was holding. If persistence and the
proposal ever disagree, the stored truth is what ships.

Every task mutation — add, edit, delete — runs inside a savepoint and
revalidates before release. A cycle created by a `PATCH` returns 409 and leaves
the plan byte-for-byte as it was.

## Versioning

Plans are immutable versions. Regeneration creates version N+1 and never
modifies version N.

What carries across a regeneration:

| Carried | Not carried | Why |
|---|---|---|
| Title, description, effort, acceptance criteria, status, notes | The task key | A generated `T3` in the new version is a different task; keeping the key would retarget the student's traceability. Carried tasks get a distinct `U` prefix. |
| Dependencies between carried tasks | Dependencies onto generated tasks | Both endpoints must exist. A dangling edge is worse than a missing one. |
| Requirement and deliverable links | — | A requirement the student linked by hand is a statement about *their* work, not about the generated plan. |

An approved plan is immutable by design. Changing it in place would make "what
did I agree to" unanswerable, which is the one question an approval exists to
settle.

### Scope

`scope=MILESTONES` copies every task, edge and traceability link verbatim and
re-derives only the checkpoints, with **no model call**. Re-deriving milestones
from the graph the student already has is arithmetic, not generation. Two rules
it respects: a milestone that lost all its tasks is dropped rather than kept as
an unfinishable checkpoint, and the milestone cap folds the tail into the last
milestone rather than dropping work.

`TASKS` (default) and `NONE` both re-plan the whole plan from the analysis.

## Staleness

A plan is stale when it was flagged stale, **or** when a newer analysis replaced
the one it was built on, **or** when the analysis it was built on no longer
matches the assignment as it stands. Staleness is *derived*, not read off a
stored flag — flags only change when something remembers to change them, and a
plan approved in the window between an assignment edit and the next flag rewrite
is exactly the case that matters.

Approving a stale plan is refused. The flag is never cleared by approving: a
plan that is out of date cannot become current by being agreed to. Approved
plans are marked but not retracted — an approved plan is a record of what the
student agreed to, and new information does not rewrite that record.

## Preferences

Planning preferences (style, guidance level, session length, AI mode) are
workspace-wide: they describe how this student works, not one assignment. They
apply to the *next* generated plan. Existing versions are not rewritten — a
plan records the preferences it was built with, so old versions stay
reproducible.

## Run telemetry

Every generation attempt writes a `PlanningRun`: tier, model, routing reason and
confidence, complexity, token usage, estimated cost, duration, output hash, and
whether a fallback occurred. A run that produces nothing — a provider failure or
a rejected proposal, with the floor disabled — is closed as `FAILED` with its
error code, rather than left `RUNNING`. A run stuck open is indistinguishable
from a run in progress, which is precisely when you need to tell them apart.

## Idempotency

Supply `idempotency_key` and a repeated request returns the existing plan
unchanged, with no second model call and no second version. `force` is the
documented escape hatch. An idempotent replay reports **no run id**, because no
run happened.

## Audit trail

Task add/update/delete, task reorder, plan edits, preference changes, generation
requests and completions, and approval all write an `AuditEvent` with the plan
version attached. An audit entry without the version cannot be tied to what the
student was looking at.

## API

All routes live under `/api/v1/assignments/{assignment_id}`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/plans` | Generate. Version 1, then a new version per call. |
| `POST` | `/plans/regenerate` | Re-plan as a new version. Honors `scope`. |
| `GET` | `/plans` | The latest plan, or the approved one if one exists. |
| `GET` | `/plans/summary` | Lightweight list for dashboards. |
| `GET` | `/plans/versions` | Paginated version history, newest first. |
| `GET` | `/plans/preferences` | Workspace planning preferences. |
| `PUT` | `/plans/preferences` | Set them. Applies to the next plan. |
| `GET` | `/plans/{plan_id}` | One specific version. |
| `PATCH` | `/plans/{plan_id}` | Edit title/summary. **Not** status. |
| `POST` | `/plans/{plan_id}/approve` | Human approval. |
| `POST` | `/plans/{plan_id}/tasks` | Add a student-authored task. |
| `PATCH` | `/plans/{plan_id}/tasks/{task_key}` | Edit a task. Marks it the student's. |
| `DELETE` | `/plans/{plan_id}/tasks/{task_key}` | Delete a task and its edges. |
| `POST` | `/plans/{plan_id}/tasks/reorder` | Set display order. No model call. |

`page` is 1-based. `PATCH` on a plan deliberately cannot change `status`:
approval owns the graph and staleness checks, so approval owns the transition.

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `planning_enabled` | `true` | Master switch. |
| `planning_fallback_enabled` | `true` | Whether a failed or invalid model call may fall back to the deterministic engine. When false, the failure surfaces as an error. |
| `planning_max_task_count` | `60` | Cap on generated tasks. |
| `planning_effort_hours_per_point` | `45.0` | Grade-point-to-hours basis for effort. |
| `llm_planner_prompt_version` | `academic_planner_v1` | Prompt version recorded on every run. |

## Related

- [`docs/ai/phase4-contract.md`](../ai/phase4-contract.md) — the contract the model is asked to satisfy
- [`docs/ai/llm_abstraction.md`](../ai/llm_abstraction.md) — provider abstraction and tier routing
- [`docs/ai/stale-analysis.md`](../ai/stale-analysis.md) — how staleness propagates
