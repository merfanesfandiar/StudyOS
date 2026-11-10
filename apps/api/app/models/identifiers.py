"""Stable, human-facing identifiers for specification entities.

Requirement references such as ``REQ-003`` have to survive reordering, edits and
deletion, because future traceability (tasks, files, tests) points at them. They
are therefore derived from an immutable per-assignment sequence number instead
of the mutable display position.
"""

import os
import socket
import time
import zlib
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


def _instance_prefix() -> int:
    """A stable 8-bit identity for this process.

    Two workers must not mint indistinguishable ids inside the same ordering
    slot. ``STUDYOS_INSTANCE_ID`` lets an orchestrator assign unique values;
    otherwise hostname+pid is a deterministic default that differs across the
    processes of one deployment.
    """
    configured = os.environ.get("STUDYOS_INSTANCE_ID")
    material = configured if configured else f"{socket.gethostname()}:{os.getpid()}"
    return zlib.crc32(material.encode("utf-8")) & 0xFF


_INSTANCE = _instance_prefix()
#: 4096 ordering slots per millisecond. The value stored in the UUID's rand_a
#: field is the sub-millisecond slot, so ids from different workers interleave by
#: wall-clock position at roughly 244µs resolution instead of tying for a whole
#: millisecond.
_SLOTS_PER_MS = 1 << 12
_last_ms = 0
_last_slot = 0


def time_ordered_uuid() -> UUID:
    """Return a UUIDv7-shaped id: random, unguessable, and time-ordered.

    Audit rows are paged by ``created_at`` and, when several events share the
    same timestamp, by id. A monotonic, time-ordered id makes that feed stable
    instead of reshuffling on every request.

    Ordering is per-process monotonic and cross-process ordered by the
    sub-millisecond slot, then by the process prefix. Two ids minted in the same
    244µs slot by different workers are therefore deterministic but not strictly
    chronological; a deployment that needs wall-clock order at finer resolution
    than that must allocate ids from a shared sequence.
    """
    global _last_ms, _last_slot

    ns = time.time_ns()
    now_ms = (ns // 1_000_000) & 0xFFFFFFFFFFFF
    now_slot = ((ns % 1_000_000) * _SLOTS_PER_MS) // 1_000_000

    if (now_ms, now_slot) > (_last_ms, _last_slot):
        milliseconds, slot = now_ms, now_slot
    else:
        # Same slot, or the clock stepped backwards. Advance from the *last
        # emitted* position rather than from the wall clock: if the clock fell
        # back a whole millisecond, incrementing only the sub-millisecond slot
        # would still mint an id that sorts before the previous one.
        milliseconds, slot = _last_ms, _last_slot + 1
        if slot >= _SLOTS_PER_MS:
            milliseconds = (milliseconds + 1) & 0xFFFFFFFFFFFF
            slot = 0
    _last_ms, _last_slot = milliseconds, slot

    # rand_a carries the ordering slot. rand_b starts with the process prefix so
    # same-slot ids from different workers have a deterministic, collision-safe
    # tie-break; the remaining 54 bits stay random.
    entropy = int.from_bytes(os.urandom(7), "big")
    rand_b = ((_INSTANCE & 0xFF) << 54) | (entropy & ((1 << 54) - 1))
    value = (milliseconds << 80) | (0x7 << 76) | (slot << 64) | (0b10 << 62) | rand_b
    return UUID(int=value)
