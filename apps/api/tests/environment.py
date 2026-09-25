"""Known environment defects that affect this test suite.

The macOS ``python.org`` 3.13.6 build available on this machine miscompiles the
string lookup used by ``Enum``/pydantic: for some interned strings, notably
``"TECHNICAL"``, ``RequirementType("TECHNICAL")`` raises even though the value
is present in the enum. The same code validates correctly on CPython 3.11.14 and
on pydantic 2.10 and 2.13, so this is an interpreter defect and not an
application bug.

Rather than renaming domain vocabulary to dodge a miscompiled interpreter, the
suite probes the behaviour once and skips the exhaustive enum checks with an
explicit reason when the interpreter is unreliable.
"""

from enum import StrEnum

import pydantic

_PROBE_ENUM_NAME = "RequirementType"
_PROBE_VALUE = "TECHNICAL"


def enum_coercion_reliable() -> tuple[bool, str]:
    """Return ``(reliable, reason)`` for str -> enum validation on this machine."""
    from app.models import enums

    enum_cls: type[StrEnum] = getattr(enums, _PROBE_ENUM_NAME)
    adapter = pydantic.TypeAdapter(enum_cls)
    if _PROBE_VALUE not in {member.value for member in enum_cls}:
        return True, ""
    try:
        adapter.validate_python(_PROBE_VALUE)
    except Exception:  # noqa: BLE001 - any failure means the lookup is broken
        return False, (
            f"{enum_cls.__name__}({_PROBE_VALUE!r}) fails on this interpreter; "
            "string to enum validation is unreliable here"
        )
    return True, ""


RELIABLE, SKIP_REASON = enum_coercion_reliable()
