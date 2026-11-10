"""Ordering guarantees for the time-ordered UUID used as an audit tie-break.

Audit rows are paged by ``created_at`` and, when several events share a
timestamp, by id. That tie-break is only stable if ids are monotonic, so the
properties worth testing are uniqueness, strict increase, and what happens when
the wall clock is not monotonic.
"""

from __future__ import annotations

from uuid import RFC_4122

import pytest
from app.models import identifiers


def test_time_ordered_uuid_is_a_uuid7() -> None:
    value = identifiers.time_ordered_uuid()
    assert value.version == 7
    assert value.variant == RFC_4122


def test_time_ordered_uuids_increase_within_a_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two thousand ids minted as fast as possible must still sort by creation.

    A same-millisecond counter that rolls back, or a random tie-break, would let
    a page of audit events reshuffle between requests.
    """
    monkeypatch.setattr(identifiers, "_last_ms", 0)
    monkeypatch.setattr(identifiers, "_last_slot", 0)

    ids = [identifiers.time_ordered_uuid() for _ in range(2_000)]

    assert len(set(ids)) == len(ids), "ids must be unique"
    assert ids == sorted(ids), "ids must be strictly increasing"


def test_time_ordered_uuid_survives_a_backwards_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clock that steps back must not mint an id that sorts before the last.

    Incrementing only the sub-millisecond slot was not enough: a regression of a
    whole millisecond still produced a lexicographically earlier id, so the audit
    feed could reorder. The generator has to advance from the last emitted
    position instead of the wall clock.
    """
    monkeypatch.setattr(identifiers, "_last_ms", 0)
    monkeypatch.setattr(identifiers, "_last_slot", 0)
    ticks = iter(
        [
            1_000_000_000_000,
            900_000_000_000,  # one whole second earlier
            900_000_000_001,
            1_000_000_000_000,  # and back to where it started
        ]
    )
    monkeypatch.setattr(identifiers.time, "time_ns", lambda: next(ticks))

    ids = [identifiers.time_ordered_uuid() for _ in range(4)]

    assert ids == sorted(ids)
