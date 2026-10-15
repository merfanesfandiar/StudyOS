"""The isolation boundary: what a sandbox backend is handed and what it returns.

A backend does exactly two things. It runs one :class:`SandboxSpec` — a set of
files, a compile command, a run command and a set of limits — and it reaps a
sandbox by id. It never sees the database, never writes artifacts and never
decides policy; those are the orchestrator's. Keeping the boundary this narrow is
what makes the backends swappable and makes "is this safe?" a question about one
file rather than about the whole pipeline.

Backends are synchronous on purpose. The work is a blocking subprocess or Docker
call; the orchestrator runs it in a worker thread so the event loop keeps serving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.enums import (
    ExecutionAttemptStatus,
    ExecutionBackendKind,
    ExecutionFailureClass,
)


@dataclass(frozen=True, slots=True)
class SandboxFile:
    """One file materialised inside the sandbox, at a path relative to the workdir."""

    path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class SandboxArtifact:
    """A file the run produced, captured before the sandbox is destroyed."""

    filename: str
    content: bytes
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class SandboxSpec:
    """Everything a backend needs to run one attempt, and nothing more."""

    job_id: str
    image: str | None
    files: tuple[SandboxFile, ...]
    compile_argv: list[str] | None
    run_argv: list[str]
    working_dir: str
    timeout_seconds: int
    memory_mb: int
    cpus: float
    pids: int
    max_output_bytes: int
    max_artifact_bytes: int
    max_artifacts: int
    environment: dict[str, str] = field(default_factory=dict)
    stdin: bytes | None = None


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """What a backend observed. Interpretation is the orchestrator's job."""

    status: ExecutionAttemptStatus
    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    duration_ms: int = 0
    sandbox_id: str | None = None
    failure_class: ExecutionFailureClass | None = None
    error_code: str | None = None
    error_message: str | None = None
    resource_usage: dict[str, Any] | None = None
    artifacts: tuple[SandboxArtifact, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()


class SandboxBackend(Protocol):
    """The interface every backend implements.

    ``kind`` is recorded on the job and the attempt so the boundary that served a
    given run is answerable after the fact. ``available`` is consulted before a
    job is dispatched: an unavailable backend produces a clean rejection, not a
    retry storm.
    """

    kind: ExecutionBackendKind

    @property
    def available(self) -> bool:
        """Whether this backend can serve a job right now."""
        ...

    def run(self, spec: SandboxSpec) -> SandboxResult:
        """Run one attempt. Must not raise for a bounded outcome."""
        ...

    def reap(self, sandbox_id: str) -> bool:
        """Force-remove a sandbox. Returns ``True`` if it is now gone."""
        ...
