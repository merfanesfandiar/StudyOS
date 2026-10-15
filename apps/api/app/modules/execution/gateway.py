"""The narrow interface the agent runtime is handed.

A tool cannot reach the execution module directly. It is given an
:class:`ExecutionGateway` — an object bound to the run, workspace, assignment and
task it belongs to — and the only method on it runs one bounded execution. The
gateway, not the tool, decides the workspace, the backend, the profile and the
limits. A tool can name a runtime and supply code; it cannot name a workspace, a
host path, an image or a resource limit.

This is the same shape as the rest of the tool contract: the caller passes an
explicit capability object rather than an import, so "what can a tool reach?" is
answerable by reading one signature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ExecutionAttempt
from app.models.enums import ExecutionArtifactKind, ExecutionJobStatus, ExecutionType
from app.modules.execution import service
from app.modules.execution.policies import DEFAULT_ENTRYPOINT
from app.storage.base import StorageService


@runtime_checkable
class ExecutionGatewayProtocol(Protocol):
    """The only execution surface a tool is handed. Deliberately one method."""

    async def run(
        self,
        *,
        execution_type: str,
        code: str,
        entrypoint: str | None = ...,
        stdin: str | None = ...,
        timeout_seconds: int | None = ...,
    ) -> ExecutionOutcome: ...


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """A bounded, user-safe summary of one execution, for a tool to return."""

    job_id: UUID
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    failure_class: str | None
    duration_ms: int
    artifact_names: tuple[str, ...] = ()
    truncated: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == ExecutionJobStatus.SUCCEEDED.value

    def as_payload(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "failure_class": self.failure_class,
            "duration_ms": self.duration_ms,
            "artifacts": list(self.artifact_names),
            "truncated": self.truncated,
        }


class ExecutionGateway:
    """Bind one run's context and expose a single ``run`` method.

    It holds the caller's session, which is the one thing a tool never receives:
    the tool calls ``run`` and the gateway talks to the database. That keeps the
    "a tool reaches nothing but its context" property true even though an
    execution needs to persist a job, an attempt and its events.
    """

    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        storage: StorageService,
        workspace_id: UUID,
        requested_by_id: UUID | None = None,
        assignment_id: UUID | None = None,
        agent_run_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._storage = storage
        self._workspace_id = workspace_id
        self._requested_by_id = requested_by_id
        self._assignment_id = assignment_id
        self._run_id = agent_run_id
        self._task_id = task_id

    async def run(
        self,
        *,
        execution_type: str,
        code: str,
        entrypoint: str | None = None,
        stdin: str | None = None,
        timeout_seconds: int | None = None,
    ) -> ExecutionOutcome:
        """Create and run one execution, returning its bounded outcome."""
        db = self._db
        service.ensure_enabled(self._settings)
        exec_type = ExecutionType(execution_type)
        resolved_entrypoint = entrypoint or DEFAULT_ENTRYPOINT.get(exec_type, "main.py")
        files = {resolved_entrypoint: code.encode("utf-8")}
        stdin_bytes = stdin.encode("utf-8") if stdin is not None else None

        job = await service.create_job(
            db,
            workspace_id=self._workspace_id,
            requested_by_id=self._requested_by_id,
            assignment_id=self._assignment_id,
            agent_run_id=self._run_id,
            task_id=self._task_id,
            execution_type=execution_type,
            entrypoint=resolved_entrypoint,
            options=None,
            files=files,
            stdin=stdin_bytes,
            profile=None,
            requested_timeout=timeout_seconds,
            idempotency_key=None,
            settings=self._settings,
            storage=self._storage,
            queue=False,
        )
        job = await service.run_inline(
            db,
            job,
            settings=self._settings,
            storage=self._storage,
            files=files,
            stdin=stdin_bytes,
        )
        stderr = await self._last_stderr(db, job.id)
        names = await self._artifact_names(db, job.id)
        return ExecutionOutcome(
            job_id=job.id,
            status=job.status,
            exit_code=job.exit_code,
            stdout=job.result_excerpt or "",
            stderr=stderr,
            failure_class=job.failure_class,
            duration_ms=job.duration_ms or 0,
            artifact_names=names,
            truncated=bool(job.result_excerpt and len(job.result_excerpt) >= 4000),
        )

    async def _last_stderr(self, db: AsyncSession, job_id: UUID) -> str:
        from sqlalchemy import select

        attempt = await db.scalar(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.job_id == job_id)
            .order_by(ExecutionAttempt.attempt.desc())
            .limit(1)
        )
        return attempt.stderr_excerpt or "" if attempt else ""

    async def _artifact_names(self, db: AsyncSession, job_id: UUID) -> tuple[str, ...]:
        from sqlalchemy import select

        from app.models import ExecutionArtifact

        rows = (
            await db.execute(
                select(ExecutionArtifact.filename).where(
                    ExecutionArtifact.job_id == job_id,
                    ExecutionArtifact.kind != ExecutionArtifactKind.SOURCE.value,
                )
            )
        ).scalars().all()
        return tuple(rows)
