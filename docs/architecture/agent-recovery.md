# Agent Recovery

A run can be interrupted in ways that are not errors: the server restarts, the browser closes
mid-step, a laptop sleeps, a deploy lands. `app/modules/agent/recovery.py` reclaims those runs.

## The one rule

**Recovery never resumes anything.** It only pauses runs and expires checkpoints. Every reclaimed run
requires an explicit human action to continue.

Auto-resume was considered and rejected. A run that picks itself up after a crash has no way to know
whether the world it was reasoning about still holds — the assignment may have been edited, the
dependency graph may have changed, the student's intent may have moved on. Resuming silently would
produce work that looks continuous and is not.

## Staleness

`stale_before(timeout_seconds, now)` returns the heartbeat cutoff:

```python
moment - timedelta(seconds=agent_heartbeat_timeout_seconds)
```

A run is stale if its `heartbeat_at` is older than the cutoff. A run with **no heartbeat at all** is
treated as stale once it is older than the window by `created_at` — otherwise a crash between creating
a run and its first heartbeat would leave a run that no sweep could ever reclaim.

`find_stale_runs` considers only `STARTING` and `RUNNING`. Everything else is either waiting for a
human, paused deliberately, or already finished, and touching those would be recovery overreach.

## What a sweep does

`recover_stale_runs` performs three steps:

1. **Find** stale runs, oldest first.
2. **Pause** each one, choosing the reason by status:
   - `STARTING` → *"The worker stopped before this run began. Resume it when you are ready."*
   - `RUNNING` → *"The worker stopped partway through. Nothing after this point was saved."*
3. **Expire** pending checkpoints past their TTL, recording
   *"Nobody answered this question in time, so the run moved on."*

The `STARTING`/`RUNNING` split matters. "Resume it when you are ready" is true and reassuring for a
run that never started; it would be a lie for one that was midway through, so that case says plainly
that the later work was not saved.

## Idempotency

Both steps are safe to repeat:

- `pause_stale_run` re-checks the status under the same conditions it selected on and returns whether
  it acted. A second sweep over the same run does nothing.
- Expiring an already-expired checkpoint does not match it.

This is what makes the sweep safe to call on every boot and on a timer without tracking what a
previous sweep did.

## Audit attribution

Recovery events are written with `user_id = None`.

The actor was the runtime, not a person. Recording the student who happened to click a button — or
the operator who happened to restart a node — would put a false actor in an audit log, and an audit
log that lies about who did what is worse than no audit log.

## Scoping

`find_stale_runs` and `expire_checkpoints` both take an optional `assignment_id`.

- **Omitted** — the whole-database sweep, for a boot hook or a scheduler.
- **Provided** — the sweep is confined to that assignment, which is what the HTTP endpoint does.

This is not an optimisation. Recovery *writes*: it pauses runs and expires questions. The
`POST /assignments/{id}/agent/recover` endpoint originally called the global sweep, which meant a
button on one assignment could pause another student's work. Every user-triggered path must be
scoped, and the behaviour is pinned by two tests — one that proves the scoped sweep still recovers
your own stale run, and one that proves it cannot touch somebody else's.

## Checkpoint expiry

A pending checkpoint with no student behind it is indistinguishable from an unanswered one, and an
unanswered question must not hold a run open forever. `agent_checkpoint_ttl_seconds` bounds it.

Expired checkpoints keep their question and record the expiry as their `response`, so the activity
trail still shows what was asked and how it ended. They are never deleted.

## What recovery does not do

- **It does not retry a failed step.** Failures are the agent's to handle within the run, under the
  attempt and cost budgets. Recovery is for runs with no live worker.
- **It does not roll back.** Everything committed before the crash is kept. `AgentExecution` rows
  exist for that reason — every attempt is retained, including partial ones.
- **It does not notify anyone.** There is no notification integration in Phase 5. A reclaimed run is
  discoverable in the UI by its `PAUSED` status and its reason.
- **It does not run automatically per-request.** The sweep is invoked by a boot hook or an operator;
  `AgentRun.updated_at` is what surfaces a paused run in a list view.

## Running a sweep

```python
report = await recover_stale_runs(session, settings)
# {"runs_paused": 2, "checkpoints_expired": 1, "run_ids": [...]}
```

Safe on every boot, safe on a timer, safe to run concurrently with a live worker — the status
re-check inside `pause_stale_run` is what makes the last claim true.