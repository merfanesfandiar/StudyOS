"""Request validation and normalisation.

Everything a caller can put into an execution is checked here, before a job row
exists, so an invalid request is a bounded ``EXECUTION_REQUEST_REJECTED`` rather
than a sandbox that starts and then misbehaves. Two invariants are enforced that
the rest of the system then relies on:

* **The entrypoint is a path inside the workspace.** Absolute paths, ``..`` and
  backslashes are refused, so no adapter can be pointed at a host file.
  Path traversal is not "handled later" by the sandbox — it never reaches it.
  The backend materialises only the files it is given, so a path that survives
  validation cannot name anything that was not uploaded either.
* **Options are an allowlist.** A request may set only the option keys its
  execution type declares; unknown keys are rejected. There is no generic
  "extra flags" bag to pass to a command.
"""

from __future__ import annotations

from app.models.enums import ExecutionType
from app.modules.execution.errors import ExecutionRejectedError
from app.modules.execution.policies import ALLOWED_OPTIONS

#: A single request may carry at most this many source files. Bounded so a job
#: cannot be an unbounded upload dressed up as an execution.
MAX_SOURCE_FILES = 64
#: Total bytes of source a request may carry, independent of artifact storage.
MAX_SOURCE_BYTES = 2_000_000
#: Largest stdin a request may supply.
MAX_STDIN_BYTES = 65_536
#: Largest number of command arguments, and length of each.
MAX_ARGS = 32
MAX_ARG_CHARS = 200

_ENTRYPOINT_MAX_CHARS = 255

#: File extensions each runtime adapter will accept as an entrypoint. A Java job
#: may not name a ``.py`` file and vice versa — the adapter would run the wrong
#: toolchain, and "it ran something" is not the same as "it ran the right thing".
_ENTRYPOINT_SUFFIXES: dict[str, frozenset[str]] = {
    "PYTHON": frozenset({".py"}),
    "DATA_ANALYSIS": frozenset({".py"}),
    "NUMERICAL_COMPUTATION": frozenset({".py"}),
    "TEST_EXECUTION": frozenset({".py"}),
    "JAVA": frozenset({".java"}),
    "CPP": frozenset({".cpp", ".cc", ".cxx"}),
}


def _is_safe_relative_path(path: str) -> bool:
    if not path or len(path) > _ENTRYPOINT_MAX_CHARS:
        return False
    if path.startswith("/") or path.startswith("\\"):
        return False
    if "\\" in path:
        return False
    if path.startswith("~"):
        return False
    return all(part not in {"", ".", ".."} for part in path.split("/"))


def _reject(reasons: list[str]) -> None:
    raise ExecutionRejectedError(reasons)


def validate_request(
    *,
    execution_type: str,
    entrypoint: str | None,
    options: dict[str, object] | None,
    files: dict[str, bytes] | None,
    stdin: bytes | None,
    requested_timeout: int | None,
) -> None:
    """Validate a raw request, raising :class:`ExecutionRejectedError` on refusal.

    Returns nothing: this only decides whether the request is admissible. Which
    profile and limits apply is :func:`~app.modules.execution.policies.resolve_limits`'s
    job, and building the command is the adapter's.
    """
    reasons: list[str] = []

    try:
        exec_type = ExecutionType(execution_type)
    except ValueError:
        _reject([f"Unknown execution_type {execution_type!r}."])
        return  # pragma: no cover - _reject always raises

    allowed = ALLOWED_OPTIONS[exec_type]

    if entrypoint is not None:
        if not _is_safe_relative_path(entrypoint):
            reasons.append(
                "entrypoint must be a relative path inside the workspace without '..'."
            )
        else:
            suffixes = _ENTRYPOINT_SUFFIXES.get(exec_type.value)
            if suffixes is not None and not any(
                entrypoint.endswith(suffix) for suffix in suffixes
            ):
                reasons.append(
                    f"entrypoint for {exec_type.value} must end with one of "
                    f"{', '.join(sorted(suffixes))}."
                )

    unknown = sorted(set((options or {}).keys()) - allowed)
    if unknown:
        reasons.append(
            f"Options not allowed for {exec_type.value}: {', '.join(unknown)}."
        )

    args = (options or {}).get("args", [])
    if args is not None:
        if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
            reasons.append("options.args must be a list of strings.")
        elif len(args) > MAX_ARGS:
            reasons.append(f"options.args may contain at most {MAX_ARGS} items.")
        elif any(len(item) > MAX_ARG_CHARS for item in args):
            reasons.append(f"Each option args item may be at most {MAX_ARG_CHARS} characters.")

    file_map = files or {}
    if len(file_map) > MAX_SOURCE_FILES:
        reasons.append(f"At most {MAX_SOURCE_FILES} source files are allowed.")
    total = sum(len(body) for body in file_map.values())
    if total > MAX_SOURCE_BYTES:
        reasons.append(f"Source files may total at most {MAX_SOURCE_BYTES} bytes.")
    for path in file_map:
        if not _is_safe_relative_path(path):
            reasons.append(f"Source path {path!r} is not a safe relative path.")

    if entrypoint is not None and file_map and entrypoint not in file_map:
        reasons.append(f"entrypoint {entrypoint!r} is not among the supplied files.")

    if stdin is not None and len(stdin) > MAX_STDIN_BYTES:
        reasons.append(f"stdin may be at most {MAX_STDIN_BYTES} bytes.")

    if requested_timeout is not None and requested_timeout < 1:
        reasons.append("requested timeout must be at least 1 second.")

    if reasons:
        _reject(reasons)
