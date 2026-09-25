"""Stable, human-facing identifiers for specification entities.

Requirement references such as ``REQ-003`` have to survive reordering, edits and
deletion, because future traceability (tasks, files, tests) points at them. They
are therefore derived from an immutable per-assignment sequence number instead
of the mutable display position.
"""

import os
import time
from uuid import UUID


def requirement_code(sequence: int) -> str:
    """Return the public reference for a requirement sequence number."""
    return f"REQ-{sequence:03d}"


def parse_requirement_code(value: str) -> int | None:
    """Return the sequence number behind a ``REQ-007`` reference, if it is one."""
    normalized = value.strip().upper()
    if not normalized.startswith("REQ-"):
        return None
    digits = normalized[4:]
    return int(digits) if digits.isdigit() else None


#: Guards the same-millisecond counter below. The API is single process, so a
#: module level counter is enough to make ids strictly increasing here.
_last_milliseconds = 0
_counter = 0


def time_ordered_uuid() -> UUID:
    """Return a UUIDv7: random, unguessable, and ordered by creation time.

    Audit rows are paged by ``created_at`` and, when several events share the
    same timestamp, by id. ``uuid4`` ids are random, so that tie-break returns a
    different page on every request; a monotonic, time-ordered id makes the feed
    stable. Ordering matters more here than perfect RFC 9562 conformance, so ids
    minted inside the same millisecond keep counting instead of rolling.
    """
    global _last_milliseconds, _counter

    now = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    if now > _last_milliseconds:
        _last_milliseconds, _counter = now, 0
    elif _counter + 1 >= 1 << 12:  # rand_a exhausted, borrow the next millisecond
        _last_milliseconds = (_last_milliseconds + 1) & 0xFFFFFFFFFFFF
        _counter = 0
    else:
        # Same millisecond, or the clock stepped backwards: keep counting so
        # ids stay strictly increasing.
        _counter += 1

    # rand_a carries the counter, so 4096 ids can share a millisecond and still
    # sort; rand_b keeps the remaining 62 bits random.
    entropy = int.from_bytes(os.urandom(8), "big")
    rand_a = _counter & 0xFFF
    rand_b = entropy & ((1 << 62) - 1)
    value = (_last_milliseconds << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return UUID(int=value)
