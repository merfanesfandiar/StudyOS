# Agent Run State Machine

Every run's status lives in `app/modules/agent/state_machine.py`, and every status change goes
through `assert_transition`. There is no code path that writes `run.status` directly for a
lifecycle change, so the table below is the whole story rather than a summary of it.

## The statuses

| Status | Meaning |
| --- | --- |
| `CREATED` | The run exists and is bound to a plan version. Nothing has been executed. |
| `STARTING` | Claimed by a worker; the first step is being prepared. |
| `RUNNING` | Executing steps. |
| `WAITING_FOR_USER` | Stopped on a checkpoint. The student must answer before anything continues. |
| `PAUSED` | Stopped deliberately, by the student or by the recovery sweep. |
| `BLOCKED` | Stopped on something the agent cannot resolve alone. |
| `COMPLETED` | Every task in the plan is done or skipped. Terminal. |
| `FAILED` | Stopped on an error. Terminal. |
| `CANCELLED` | Withdrawn by the student. Terminal. |

## The transitions

```
                  ┌──────────────► CANCELLED ◄──────────────┐
                  │                                           │
  CREATED ──► STARTING ──► RUNNING ──► COMPLETED             │
                  │  ╲         │ │ ╲                         │
                  │   ╲        │ │  ╲                        │
                  │    ╲       │ │   ╲                       │
                  ▼     ╲      │ │    ╲                      │
            PAUSED      ╲     │ │     ╲                     │
                  ▲       ╲    │ │      ╲                    │
                  │        ╲   │ │       ╲                   │
                  │         ╲  ▼ ▼        ╲                  │
                  └──── PAUSED ◄──┬────────┴─► FAILED ───────┘
                                 │
                    WAITING_FOR_USER
                                 │
                                 └──► BLOCKED
```

As a table, which is what the code actually holds:

| From | To |
| --- | --- |
| `CREATED` | `STARTING`, `CANCELLED` |
| `STARTING` | `RUNNING`, `WAITING_FOR_USER`, `PAUSED`, `BLOCKED`, `FAILED`, `CANCELLED` |
| `RUNNING` | `WAITING_FOR_USER`, `PAUSED`, `BLOCKED`, `COMPLETED`, `FAILED`, `CANCELLED` |
| `WAITING_FOR_USER` | `RUNNING`, `PAUSED`, `BLOCKED`, `FAILED`, `CANCELLED` |
| `PAUSED` | `RUNNING`, `BLOCKED`, `CANCELLED`, `FAILED` |
| `BLOCKED` | `RUNNING`, `PAUSED`, `CANCELLED`, `FAILED` |
| `COMPLETED` | — terminal |
| `FAILED` | — terminal |
| `CANCELLED` | — terminal |

## Why the table is deliberately incomplete

Three absences are the design, not omissions.

**`RUNNING` cannot go to `CREATED`, and nothing goes back to `STARTING`.** A run that has started
cannot un-start. Allowing it would make retries ambiguous.

**`WAITING_FOR_USER` cannot reach `COMPLETED`.** The only way out is through `RUNNING`, which means
executing real work after the answer. There is no path where answering a question silently marks the
plan done.

**Terminal statuses have no outgoing edges.** A cancelled run cannot be resumed. The UI hides the
controls, but the server refuses too — the buttons disappearing is courtesy, not enforcement.

## Re-entering a run that is already going

`RUNNING → RUNNING` is not in the table, and `assert_transition` rejects it. That is intentional:
a self-transition in a state machine usually means a bug.

The one legitimate case is re-entering a run that is already executing — a resumed step, or a
checkpoint answered moments ago whose run was already moved back to `RUNNING`. `execute_run` treats
that as the no-op it is rather than a contradiction, instead of weakening the table for everyone
else's benefit.

## `STARTING → PAUSED`

Added for recovery. A crash can happen between claiming a run and its first heartbeat, so the
recovery sweep has to be able to reclaim a run that never actually started. Without this edge the
only option would be `FAILED`, which claims something went wrong that may simply have been a
process death.

## Reasons are part of the state

`paused_reason` is populated for every stop and is what the UI shows. `CREATED` is the only status
with no reason, because nothing has happened yet.

`_set_status` also clears `error_code`, `error_message`, and `error_category` on entry to `RUNNING`
and `STARTING`. A run that was blocked, addressed the blockage, and resumed should not keep
displaying the error that caused the block — the failure is still in `AgentExecution` and
`AgentEvent`, where it belongs.

## Why this is a table and not a boolean

`is_running` would have been simpler. It would also have made "paused because the student asked" and
"paused because the process died" indistinguishable, and those need different recoveries,
different UI copy, and different audit entries. The table is longer, and it is the reason
[`agent-recovery.md`](./agent-recovery.md) can be precise about what it is reclaiming.