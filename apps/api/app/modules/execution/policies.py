"""Resource policy: the ceilings every execution runs under.

A resource profile is a *ceiling*, never an entitlement. A request may ask for a
smaller timeout inside its profile, but never a larger one, and even the profile's
own numbers are clamped against the deployment maximum in :class:`Settings`. The
two-layer clamp is the point: editing a profile constant cannot quietly exceed what
the operator configured, and an operator setting cannot be exceeded by a client.

The limits here are what stop a runaway program from becoming an outage — wall
clock, memory, CPU share, process count, and the size of what it may capture and
emit. None of them can be widened by request content.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.core.config import Settings
from app.models.enums import ExecutionResourceProfile, ExecutionType

#: Per-type options a client is allowed to set. Anything outside this set is a
#: validation error, so a request cannot smuggle an arbitrary flag into a fixed
#: command. The adapters consume only these.
ALLOWED_OPTIONS: Final[dict[ExecutionType, frozenset[str]]] = {
    ExecutionType.PYTHON: frozenset({"args", "stdin"}),
    ExecutionType.JAVA: frozenset({"args", "stdin", "main_class"}),
    ExecutionType.CPP: frozenset({"args", "stdin", "standard"}),
    ExecutionType.DATA_ANALYSIS: frozenset({"args", "stdin"}),
    ExecutionType.NUMERICAL_COMPUTATION: frozenset({"args", "stdin"}),
    ExecutionType.TEST_EXECUTION: frozenset({"args", "stdin", "framework"}),
    ExecutionType.BUILD: frozenset({"args", "target"}),
    ExecutionType.STATIC_ANALYSIS: frozenset({"args"}),
    ExecutionType.OTHER: frozenset({"args", "stdin"}),
}

#: Execution types that compile before they run, so a compile failure is a
#: distinct failure class from a runtime failure.
COMPILED_TYPES: Final[frozenset[ExecutionType]] = frozenset(
    {ExecutionType.JAVA, ExecutionType.CPP}
)

#: Conventional entrypoint filename per runtime. Used to default a request that
#: supplies source but names no entrypoint, so a client is not forced to repeat
#: the runtime's convention. The sandbox still only ever runs a file that was
#: uploaded under this name.
DEFAULT_ENTRYPOINT: Final[dict[ExecutionType, str]] = {
    ExecutionType.PYTHON: "main.py",
    ExecutionType.DATA_ANALYSIS: "analysis.py",
    ExecutionType.NUMERICAL_COMPUTATION: "computation.py",
    ExecutionType.TEST_EXECUTION: "test_main.py",
    ExecutionType.JAVA: "Main.java",
    ExecutionType.CPP: "main.cpp",
}


def resolve_entrypoint(
    execution_type: ExecutionType, entrypoint: str | None, files: Mapping[str, object]
) -> str | None:
    """Pick the file to run when a request does not name one.

    Preference order: the caller's explicit entrypoint, then the runtime's
    conventional filename if it was supplied, then the sole file when exactly one
    was uploaded. Anything else is left as ``None`` for validation to refuse with
    a reason a person can read, because guessing among several files would be
    running something the caller did not choose.
    """
    if entrypoint:
        return entrypoint
    default = DEFAULT_ENTRYPOINT.get(execution_type)
    if default is not None and default in files:
        return default
    if len(files) == 1:
        return next(iter(files))
    return default

#: Default resource profile per execution type when the request names none.
DEFAULT_PROFILE: Final[dict[ExecutionType, ExecutionResourceProfile]] = {
    ExecutionType.PYTHON: ExecutionResourceProfile.STANDARD_CODE_EXECUTION,
    ExecutionType.JAVA: ExecutionResourceProfile.STANDARD_CODE_EXECUTION,
    ExecutionType.CPP: ExecutionResourceProfile.STANDARD_CODE_EXECUTION,
    ExecutionType.DATA_ANALYSIS: ExecutionResourceProfile.DATA_ANALYSIS,
    ExecutionType.NUMERICAL_COMPUTATION: ExecutionResourceProfile.DATA_ANALYSIS,
    ExecutionType.TEST_EXECUTION: ExecutionResourceProfile.TEST_EXECUTION,
    ExecutionType.BUILD: ExecutionResourceProfile.BUILD_EXECUTION,
    ExecutionType.STATIC_ANALYSIS: ExecutionResourceProfile.LIGHT_COMPUTATION,
    ExecutionType.OTHER: ExecutionResourceProfile.LIGHT_COMPUTATION,
}


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """The concrete limits a single attempt is bounded by."""

    timeout_seconds: int
    memory_mb: int
    cpus: float
    pids: int
    max_output_bytes: int
    max_artifact_bytes: int
    max_artifacts: int

    def as_dict(self) -> dict[str, int | float]:
        """Snapshot for persistence, so a later config change cannot rewrite it."""
        return {
            "timeout_seconds": self.timeout_seconds,
            "memory_mb": self.memory_mb,
            "cpus": self.cpus,
            "pids": self.pids,
            "max_output_bytes": self.max_output_bytes,
            "max_artifact_bytes": self.max_artifact_bytes,
            "max_artifacts": self.max_artifacts,
        }


#: Profile ceilings, before the operator's maxima are applied. These are chosen
#: so the *shape* of a workload matches its budget: a light note-taking compute is
#: not given a build's two gigabytes, and a build is not starved at half a core.
_PROFILE_BASES: Final[dict[ExecutionResourceProfile, dict[str, int | float]]] = {
    ExecutionResourceProfile.LIGHT_COMPUTATION: {
        "timeout_seconds": 10,
        "memory_mb": 256,
        "cpus": 0.5,
        "pids": 64,
    },
    ExecutionResourceProfile.STANDARD_CODE_EXECUTION: {
        "timeout_seconds": 30,
        "memory_mb": 512,
        "cpus": 1.0,
        "pids": 128,
    },
    ExecutionResourceProfile.DATA_ANALYSIS: {
        "timeout_seconds": 120,
        "memory_mb": 1024,
        "cpus": 1.0,
        "pids": 256,
    },
    ExecutionResourceProfile.TEST_EXECUTION: {
        "timeout_seconds": 60,
        "memory_mb": 512,
        "cpus": 1.0,
        "pids": 128,
    },
    ExecutionResourceProfile.BUILD_EXECUTION: {
        "timeout_seconds": 180,
        "memory_mb": 2048,
        "cpus": 2.0,
        "pids": 512,
    },
}


def profile_ceilings() -> dict[str, dict[str, int | float]]:
    """The profile ceilings before operator maxima, for a read-only capability view."""
    return {profile.value: dict(base) for profile, base in _PROFILE_BASES.items()}


def resolve_limits(
    settings: Settings,
    profile: ExecutionResourceProfile,
    *,
    requested_timeout: int | None = None,
) -> ResourceLimits:
    """Clamp a profile to the operator's maxima, optionally shortening the timeout.

    A requested timeout may only *reduce* the profile's wall clock. A longer one is
    clamped down rather than refused: the caller asked for more time than policy
    grants, and answering with the maximum it may have is friendlier than an error
    while remaining safe.
    """
    base = _PROFILE_BASES[profile]
    timeout = int(base["timeout_seconds"])
    if requested_timeout is not None:
        timeout = min(timeout, max(1, requested_timeout))
    timeout = min(timeout, settings.execution_max_timeout_seconds)

    return ResourceLimits(
        timeout_seconds=timeout,
        memory_mb=min(int(base["memory_mb"]), settings.execution_max_memory_mb),
        cpus=min(float(base["cpus"]), settings.execution_max_cpus),
        pids=min(int(base["pids"]), settings.execution_max_pids),
        max_output_bytes=settings.execution_max_output_bytes,
        max_artifact_bytes=settings.execution_max_artifact_bytes,
        max_artifacts=settings.execution_max_artifacts,
    )
