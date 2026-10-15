"""The execution job state machine.

Every status change to an :class:`~app.models.entities.ExecutionJob` in this
package goes through :func:`assert_transition` (usually via :func:`transition`).
A job's status is the fact the queue, the recovery sweep, the cancel path and the
read model all lean on, so it is not assigned freely.

The table is data, not control flow, which makes three properties cheap to state
and test:

* **Only listed transitions exist.** ``SUCCEEDED -> RUNNING`` is refused: a
  finished execution is a record, not a shell you can re-enter. Re-running means a
  new job, which is what makes a retry auditable rather than a rewrite of history.
* **Terminal really is terminal.** ``SUCCEEDED``, ``FAILED``, ``TIMED_OUT``,
  ``CANCELLED``, ``RESOURCE_LIMIT_EXCEEDED`` and ``REJECTED`` have no outgoing
  edges. ``CLEANUP_PENDING`` is a reserved value this version never writes —
  cleanup is tracked on its own column (``cleanup_status``) — but it keeps a row
  so the table stays total and an unexpected row cannot raise a ``KeyError``.
* **A cancel is a request until it is honoured.** "Running" jobs move to
  ``CANCEL_REQUESTED``, from which only ``CANCELLED`` (the worker or the recovery
  sweep observed it) or ``FAILED`` (it could not stop) follow. Pretending a
  running attempt stopped the moment it was asked to would be a lie.

The queue's compare-and-swap claim performs the ``QUEUED -> STARTING`` move in
SQL rather than through :func:`assert_transition`, for atomicity; that one edge is
kept in this table so the two representations cannot drift.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from app.core.errors import AppError
from app.models.enums import ExecutionJobStatus

#: States from which no transition is permitted.
TERMINAL_STATUSES: Final[frozenset[ExecutionJobStatus]] = frozenset(
    {
        ExecutionJobStatus.SUCCEEDED,
        ExecutionJobStatus.FAILED,
        ExecutionJobStatus.TIMED_OUT,
        ExecutionJobStatus.CANCELLED,
        ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED,
        ExecutionJobStatus.REJECTED,
    }
)

#: States a worker is allowed to own and advance an execution from.
ACTIVE_STATUSES: Final[frozenset[ExecutionJobStatus]] = frozenset(
    {
        ExecutionJobStatus.STARTING,
        ExecutionJobStatus.RUNNING,
        ExecutionJobStatus.COLLECTING_RESULTS,
    }
)

#: The complete transition table.
TRANSITIONS: Final[Mapping[ExecutionJobStatus, frozenset[ExecutionJobStatus]]] = {
    # A created job is either validated then queued, or run inline (CREATED ->
    # STARTING). It can be rejected or cancelled before either happens.
    ExecutionJobStatus.CREATED: frozenset(
        {
            ExecutionJobStatus.VALIDATING,
            ExecutionJobStatus.QUEUED,
            ExecutionJobStatus.STARTING,
            ExecutionJobStatus.REJECTED,
            ExecutionJobStatus.CANCELLED,
        }
    ),
    ExecutionJobStatus.VALIDATING: frozenset(
        {
            ExecutionJobStatus.QUEUED,
            ExecutionJobStatus.REJECTED,
            ExecutionJobStatus.CANCELLED,
        }
    ),
    ExecutionJobStatus.QUEUED: frozenset(
        {
            ExecutionJobStatus.STARTING,
            ExecutionJobStatus.CANCELLED,
        }
    ),
    # STARTING can fall back to QUEUED and to REJECTED because the orchestrator
    # resolves the plan and checks the backend after the claim; a lost worker is
    # recovered by the sweep, which either re-queues or fails the job.
    ExecutionJobStatus.STARTING: frozenset(
        {
            ExecutionJobStatus.RUNNING,
            ExecutionJobStatus.QUEUED,
            ExecutionJobStatus.REJECTED,
            ExecutionJobStatus.FAILED,
            ExecutionJobStatus.CANCEL_REQUESTED,
        }
    ),
    ExecutionJobStatus.RUNNING: frozenset(
        {
            ExecutionJobStatus.COLLECTING_RESULTS,
            ExecutionJobStatus.QUEUED,
            ExecutionJobStatus.FAILED,
            ExecutionJobStatus.CANCEL_REQUESTED,
        }
    ),
    # The one place every terminal status is reached: the run has finished and its
    # outputs are being gathered, so any outcome except "still running" is allowed
    # (the queued/failed edges are the recovery sweep reclaiming a lost worker).
    ExecutionJobStatus.COLLECTING_RESULTS: frozenset(
        {
            ExecutionJobStatus.SUCCEEDED,
            ExecutionJobStatus.FAILED,
            ExecutionJobStatus.TIMED_OUT,
            ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED,
            ExecutionJobStatus.REJECTED,
            ExecutionJobStatus.CANCELLED,
            ExecutionJobStatus.CANCEL_REQUESTED,
            ExecutionJobStatus.QUEUED,
        }
    ),
    ExecutionJobStatus.CANCEL_REQUESTED: frozenset(
        {ExecutionJobStatus.CANCELLED, ExecutionJobStatus.FAILED}
    ),
    # Reserved: this version tracks cleanup on its own column and never sets this
    # status. If a future version does, it may only resolve to a terminal outcome.
    ExecutionJobStatus.CLEANUP_PENDING: frozenset(
        {
            ExecutionJobStatus.SUCCEEDED,
            ExecutionJobStatus.FAILED,
            ExecutionJobStatus.TIMED_OUT,
            ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED,
            ExecutionJobStatus.CANCELLED,
            ExecutionJobStatus.REJECTED,
        }
    ),
    ExecutionJobStatus.SUCCEEDED: frozenset(),
    ExecutionJobStatus.FAILED: frozenset(),
    ExecutionJobStatus.TIMED_OUT: frozenset(),
    ExecutionJobStatus.CANCELLED: frozenset(),
    ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED: frozenset(),
    ExecutionJobStatus.REJECTED: frozenset(),
}

#: The one move the queue's CAS claim performs in SQL rather than in Python.
CLAIM_EDGE: Final[tuple[ExecutionJobStatus, ExecutionJobStatus]] = (
    ExecutionJobStatus.QUEUED,
    ExecutionJobStatus.STARTING,
)


class InvalidTransitionError(AppError):
    """A requested execution status change is not in the table.

    Surfaced as a 409 rather than a 500: the caller asked for something the
    runtime cannot do, and the correct response is to say so, not to retry.
    """

    def __init__(
        self,
        current: ExecutionJobStatus,
        target: ExecutionJobStatus,
        allowed: frozenset[ExecutionJobStatus],
    ) -> None:
        super().__init__(
            409,
            "EXECUTION_INVALID_TRANSITION",
            f"An execution cannot move from {current.value} to {target.value}.",
            {
                "current_status": current.value,
                "requested_status": target.value,
                "allowed_statuses": sorted(s.value for s in allowed),
            },
        )
        self.current = current
        self.target = target


def parse_status(value: str) -> ExecutionJobStatus:
    """Parse a stored status, treating an unknown value as corrupt rather than defaulting.

    Silently coercing an unrecognised status to ``CREATED`` would let a row written
    by a future version be re-driven by this one. Failing loudly is the correct
    behaviour for a closed vocabulary.
    """
    try:
        return ExecutionJobStatus(value)
    except ValueError as exc:
        raise AppError(
            409,
            "EXECUTION_STATUS_UNKNOWN",
            f"{value!r} is not a known execution job status.",
        ) from exc


def assert_transition(current: ExecutionJobStatus, target: ExecutionJobStatus) -> None:
    """Raise unless ``current -> target`` is permitted."""
    allowed = TRANSITIONS[current]
    if target not in allowed:
        raise InvalidTransitionError(current, target, allowed)


def can_transition(current: ExecutionJobStatus, target: ExecutionJobStatus) -> bool:
    """Non-raising form, for callers that want to branch rather than raise."""
    return target in TRANSITIONS[current]


def is_terminal(status: ExecutionJobStatus) -> bool:
    return status in TERMINAL_STATUSES


def is_terminal_value(value: str) -> bool:
    """Terminal check on a raw stored string, without raising on corruption."""
    try:
        return parse_status(value) in TERMINAL_STATUSES
    except AppError:
        return False


def transition(job: Any, target: ExecutionJobStatus) -> None:
    """Move ``job.status`` to ``target``, refusing any move the table forbids.

    A no-op when the job is already there, so a caller may set the status it
    expects without first checking. ``job`` is any object with a ``status`` string
    attribute; it is typed loosely to keep this module free of model imports.
    """
    current = parse_status(job.status)
    if current is target:
        return
    assert_transition(current, target)
    job.status = target.value


def allowed_targets(status: ExecutionJobStatus) -> frozenset[ExecutionJobStatus]:
    return TRANSITIONS[status]
