"""The execution status vocabulary is a closed, enforced state machine.

These tests pin the properties the security model leans on: terminal means
terminal, a cancel is a request until it is honoured, and the one move the queue
makes in SQL is the same edge the table lists.
"""

from __future__ import annotations

from itertools import pairwise
from types import SimpleNamespace

import pytest
from app.core.errors import AppError
from app.models.enums import ExecutionJobStatus
from app.modules.execution import state_machine as sm

ALL_STATUSES = set(ExecutionJobStatus)


def test_every_status_has_a_row() -> None:
    assert set(sm.TRANSITIONS) == ALL_STATUSES


def test_terminal_statuses_match_the_table() -> None:
    for status in ALL_STATUSES:
        if status in sm.TERMINAL_STATUSES:
            assert sm.TRANSITIONS[status] == frozenset(), status
        else:
            assert status not in sm.TERMINAL_STATUSES


def test_only_listed_transitions_are_permitted() -> None:
    assert sm.can_transition(ExecutionJobStatus.QUEUED, ExecutionJobStatus.STARTING)
    assert not sm.can_transition(
        ExecutionJobStatus.SUCCEEDED, ExecutionJobStatus.RUNNING
    )


def test_a_finished_execution_cannot_be_re_entered() -> None:
    with pytest.raises(sm.InvalidTransitionError) as exc_info:
        sm.assert_transition(ExecutionJobStatus.SUCCEEDED, ExecutionJobStatus.RUNNING)
    error = exc_info.value
    assert error.status_code == 409
    assert error.code == "EXECUTION_INVALID_TRANSITION"
    assert error.details["current_status"] == "SUCCEEDED"
    assert error.details["requested_status"] == "RUNNING"
    assert error.details["allowed_statuses"] == []


def test_the_happy_path_is_legal() -> None:
    path = [
        ExecutionJobStatus.CREATED,
        ExecutionJobStatus.QUEUED,
        ExecutionJobStatus.STARTING,
        ExecutionJobStatus.RUNNING,
        ExecutionJobStatus.COLLECTING_RESULTS,
        ExecutionJobStatus.SUCCEEDED,
    ]
    for current, target in pairwise(path):
        sm.assert_transition(current, target)


def test_a_cancel_while_running_is_only_a_request() -> None:
    sm.assert_transition(ExecutionJobStatus.RUNNING, ExecutionJobStatus.CANCEL_REQUESTED)
    sm.assert_transition(ExecutionJobStatus.CANCEL_REQUESTED, ExecutionJobStatus.CANCELLED)
    # A running attempt cannot jump straight to CANCELLED; it must be requested first.
    assert not sm.can_transition(ExecutionJobStatus.RUNNING, ExecutionJobStatus.CANCELLED)


def test_recovery_edges_are_allowed() -> None:
    for stale in sm.ACTIVE_STATUSES:
        assert sm.can_transition(stale, ExecutionJobStatus.QUEUED)
        assert sm.can_transition(stale, ExecutionJobStatus.FAILED)


def test_claim_edge_is_in_the_table() -> None:
    current, target = sm.CLAIM_EDGE
    assert current is ExecutionJobStatus.QUEUED
    assert target is ExecutionJobStatus.STARTING
    assert sm.can_transition(current, target)


def test_transition_helper_sets_and_is_idempotent() -> None:
    job = SimpleNamespace(status=ExecutionJobStatus.CREATED.value)
    sm.transition(job, ExecutionJobStatus.STARTING)
    assert job.status == "STARTING"
    sm.transition(job, ExecutionJobStatus.STARTING)
    assert job.status == "STARTING"


def test_transition_helper_refuses_an_invalid_move() -> None:
    job = SimpleNamespace(status=ExecutionJobStatus.SUCCEEDED.value)
    with pytest.raises(sm.InvalidTransitionError):
        sm.transition(job, ExecutionJobStatus.RUNNING)


def test_parse_status_rejects_an_unknown_value() -> None:
    with pytest.raises(AppError) as exc_info:
        sm.parse_status("NOT_A_STATUS")
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "EXECUTION_STATUS_UNKNOWN"
