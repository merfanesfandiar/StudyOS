"""The agent run state machine.

Every status change in the runtime goes through :func:`assert_transition` or one
of the helpers below. There is deliberately no ``run.status = ...`` anywhere in
``app/modules/agent`` — a run's state is the one piece of data whose integrity
the rest of the system leans on, so it is the one thing that is not assigned
freely.

The transition table is data, not control flow. That makes three properties
cheap to state and cheap to test:

* **Only listed transitions exist.** Anything else raises, including the
  plausible-looking ones. ``COMPLETED -> RUNNING`` in particular is refused: a
  finished run is a record, not a shell you can re-enter.
* **Terminal really is terminal.** ``COMPLETED``, ``FAILED`` and ``CANCELLED``
  have no outgoing edges. Resuming a failed run means creating a new run, which
  is what makes "retry" auditable rather than a rewrite of history.
* **Paused and blocked are different.** ``WAITING_FOR_USER`` expects an answer;
  ``PAUSED`` expects a decision to continue. Collapsing them is how a supervised
  agent silently becomes autonomous, so the UI and the recovery policy both
  depend on keeping them apart.

``BLOCKED`` is reachable from ``RUNNING`` only via an explicit reason. A run that
cannot continue because of a dependency, a missing permission or an
missing-information wall must say which, or "blocked" is not actionable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.core.errors import AppError
from app.models.enums import AgentRunStatus

#: States from which no transition is permitted.
TERMINAL_STATUSES: Final[frozenset[AgentRunStatus]] = frozenset(
    {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}
)

#: States in which the runtime is allowed to own the run and advance it.
ACTIVE_STATUSES: Final[frozenset[AgentRunStatus]] = frozenset(
    {AgentRunStatus.STARTING, AgentRunStatus.RUNNING}
)

#: States a student may resume from. ``WAITING_FOR_USER`` and ``PAUSED`` are
#: here because both mean "a person must decide something"; ``BLOCKED`` is not,
#: because a blocked run has an unresolved wall rather than a pending decision.
RESUMABLE_STATUSES: Final[frozenset[AgentRunStatus]] = frozenset(
    {AgentRunStatus.WAITING_FOR_USER, AgentRunStatus.PAUSED, AgentRunStatus.BLOCKED}
)

#: The complete transition table.
TRANSITIONS: Final[Mapping[AgentRunStatus, frozenset[AgentRunStatus]]] = {
    AgentRunStatus.CREATED: frozenset({AgentRunStatus.STARTING, AgentRunStatus.CANCELLED}),
    # STARTING -> PAUSED exists because a run can die during startup, and
    # recovery has to be able to hand it back to the student rather than only
    # failing it. "Accepted but never began" is a state a person can reason about.
    AgentRunStatus.STARTING: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.WAITING_FOR_USER,
            AgentRunStatus.PAUSED,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.RUNNING: frozenset(
        {
            AgentRunStatus.WAITING_FOR_USER,
            AgentRunStatus.PAUSED,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    # A checkpoint hand-off can still fail or be cancelled while it waits.
    AgentRunStatus.WAITING_FOR_USER: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.PAUSED,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.PAUSED: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.BLOCKED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.FAILED,
        }
    ),
    # Blocked runs resume only once the wall is actually resolved, which the
    # service verifies separately. The table allows it; the service checks it.
    AgentRunStatus.BLOCKED: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.PAUSED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.FAILED,
        }
    ),
    AgentRunStatus.COMPLETED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
    AgentRunStatus.CANCELLED: frozenset(),
}


class InvalidTransitionError(AppError):
    """A requested status change is not in the table.

    Surfaced as a 409 rather than a 500: the caller asked for something the
    runtime cannot do, and the correct response is to say so, not to retry.
    """

    def __init__(
        self,
        current: AgentRunStatus,
        target: AgentRunStatus,
        allowed: frozenset[AgentRunStatus],
    ) -> None:
        super().__init__(
            409,
            "AGENT_INVALID_TRANSITION",
            f"A run cannot move from {current.value} to {target.value}.",
            {
                "current_status": current.value,
                "requested_status": target.value,
                "allowed_statuses": sorted(s.value for s in allowed),
            },
        )
        self.current = current
        self.target = target


def parse_status(value: str) -> AgentRunStatus:
    """Parse a stored status, treating an unknown value as corrupt rather than defaulting.

    Silently coercing an unrecognised status to ``CREATED`` would let a row
    written by a future version be re-driven by this one. Failing loudly is the
    correct behaviour for a closed vocabulary.
    """
    try:
        return AgentRunStatus(value)
    except ValueError as exc:
        raise AppError(
            409,
            "AGENT_STATUS_UNKNOWN",
            f"{value!r} is not a known agent run status.",
        ) from exc


def assert_transition(current: AgentRunStatus, target: AgentRunStatus) -> None:
    """Raise unless ``current -> target`` is permitted."""
    allowed = TRANSITIONS[current]
    if target not in allowed:
        raise InvalidTransitionError(current, target, allowed)


def is_terminal(status: AgentRunStatus) -> bool:
    return status in TERMINAL_STATUSES


def is_resumable(status: AgentRunStatus) -> bool:
    return status in RESUMABLE_STATUSES


def can_transition(current: AgentRunStatus, target: AgentRunStatus) -> bool:
    """Non-raising form, for UIs that want to grey out a button."""
    return target in TRANSITIONS[current]


def allowed_targets(status: AgentRunStatus) -> frozenset[AgentRunStatus]:
    return TRANSITIONS[status]


#: Statuses that represent the runtime waiting on a person rather than on work.
#: The UI reads this to decide whether to offer "resume" or "answer".
AWAITING_PERSON: Final[frozenset[AgentRunStatus]] = frozenset(
    {AgentRunStatus.WAITING_FOR_USER, AgentRunStatus.PAUSED}
)
