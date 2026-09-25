"""Stable, human-facing identifiers for specification entities.

Requirement references such as ``REQ-003`` have to survive reordering, edits and
deletion, because future traceability (tasks, files, tests) points at them. They
are therefore derived from an immutable per-assignment sequence number instead
of the mutable display position.
"""


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
