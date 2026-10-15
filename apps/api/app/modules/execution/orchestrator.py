"""The execution orchestrator: one job, one attempt, one bounded outcome.

The orchestrator owns the sequence every execution follows, in order and without
shortcuts:

``STARTING`` → run (in a worker thread) → collect stdout/stderr and artifacts →
``COLLECTING_RESULTS`` → destroy the environment → terminal status.

Two things are true by construction. First, the backend call is the only blocking
step, and it is always off the event loop. Second, an environment is *always* asked
to clean up before the job is marked terminal, so a failure to reap is recorded on
the job as ``cleanup_status=FAILED`` rather than silently dropped. That is why
cleanup is a separate column from status: "the program finished" and "the sandbox
is gone" are different facts.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentArtifact, AgentRun, ExecutionArtifact, ExecutionAttempt, ExecutionJob
from app.models.enums import (
    AgentArtifactOwnership,
    AgentArtifactType,
    ExecutionArtifactKind,
    ExecutionAttemptStatus,
    ExecutionCleanupStatus,
    ExecutionEventType,
    ExecutionFailureClass,
    ExecutionJobStatus,
    ExecutionType,
)
from app.modules.execution import metrics
from app.modules.execution.adapters import AdapterRegistry
from app.modules.execution.backends.base import (
    SandboxArtifact,
    SandboxBackend,
    SandboxFile,
    SandboxResult,
    SandboxSpec,
)
from app.modules.execution.errors import ExecutionRejectedError
from app.modules.execution.events import append_event
from app.modules.execution.policies import ResourceLimits
from app.modules.execution.state_machine import TERMINAL_STATUSES, transition
from app.storage.base import StorageService

#: Map an execution artifact kind onto the agent artifact vocabulary, for the
#: artifacts that also belong to an agent run.
_AGENT_ARTIFACT_TYPE: dict[ExecutionArtifactKind, AgentArtifactType] = {
    ExecutionArtifactKind.SOURCE: AgentArtifactType.CODE,
    ExecutionArtifactKind.RESULT: AgentArtifactType.CALCULATION,
    ExecutionArtifactKind.DATA_OUTPUT: AgentArtifactType.CALCULATION,
    ExecutionArtifactKind.CHART: AgentArtifactType.DOCUMENT,
    ExecutionArtifactKind.TEST_REPORT: AgentArtifactType.REPORT,
    ExecutionArtifactKind.DIAGNOSTICS: AgentArtifactType.TEXT,
    ExecutionArtifactKind.LOG: AgentArtifactType.TEXT,
    ExecutionArtifactKind.SUMMARY: AgentArtifactType.REPORT,
    ExecutionArtifactKind.GENERATED_FILE: AgentArtifactType.DOCUMENT,
    ExecutionArtifactKind.OTHER: AgentArtifactType.TEXT,
}

#: Output extensions classified as a chart rather than generic data.
_CHART_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg", ".gif", ".pdf")


def _now() -> datetime:
    return datetime.now(UTC)


class ExecutionOrchestrator:
    """Runs one attempt of a job through the configured backend."""

    def __init__(
        self,
        *,
        backend: SandboxBackend,
        adapters: AdapterRegistry,
        storage: StorageService,
    ) -> None:
        self.backend = backend
        self.adapters = adapters
        self.storage = storage

    async def execute(
        self,
        db: AsyncSession,
        job: ExecutionJob,
        *,
        source_files: Mapping[str, bytes],
        stdin: bytes | None,
        worker_id: str,
    ) -> ExecutionJob:
        """Run ``job`` and return it in a terminal (or rejected) state.

        Commits at each phase boundary so a crash can be recovered: the job is
        durably ``RUNNING`` with a lease before the blocking call starts, which is
        what lets the recovery sweep reclaim it if this process dies mid-run.
        """
        if job.status in {status.value for status in TERMINAL_STATUSES}:
            return job

        if job.status == ExecutionJobStatus.CANCEL_REQUESTED.value:
            return await self._cancel(db, job)

        try:
            execution_type = ExecutionType(job.execution_type)
            adapter = self.adapters.get(execution_type)
        except (ValueError, ExecutionRejectedError) as exc:
            return await self._reject(db, job, f"{exc}")

        options = job.options_json or {}
        try:
            plan = adapter.build_plan(
                entrypoint=job.entrypoint, options=options, job_id=job.id
            )
        except ExecutionRejectedError as exc:
            reasons = exc.details.get("reasons", []) if isinstance(exc.details, dict) else []
            return await self._reject(db, job, "; ".join(map(str, reasons)) or str(exc))

        if not self.backend.available:
            return await self._reject(
                db, job, "No sandbox backend is available in this deployment."
            )

        limits = self._limits(job)
        attempt_number = (job.attempt_count or 0) + 1
        now = _now()
        transition(job, ExecutionJobStatus.STARTING)
        job.attempt_count = attempt_number
        job.started_at = job.started_at or now
        job.lease_owner = worker_id
        job.lease_expires_at = now
        await append_event(
            db,
            job.id,
            ExecutionEventType.EXECUTION_STARTED,
            f"Execution attempt {attempt_number} started.",
            metadata={"attempt": attempt_number, "backend": self.backend.kind.value},
        )
        await db.commit()

        spec = SandboxSpec(
            job_id=str(job.id),
            image=plan.image,
            files=tuple(
                SandboxFile(path=path, content=body) for path, body in source_files.items()
            ),
            compile_argv=plan.compile_argv,
            run_argv=plan.run_argv,
            working_dir=plan.working_dir,
            timeout_seconds=limits.timeout_seconds,
            memory_mb=limits.memory_mb,
            cpus=limits.cpus,
            pids=limits.pids,
            max_output_bytes=limits.max_output_bytes,
            max_artifact_bytes=limits.max_artifact_bytes,
            max_artifacts=limits.max_artifacts,
            stdin=stdin,
        )

        transition(job, ExecutionJobStatus.RUNNING)
        await append_event(
            db,
            job.id,
            ExecutionEventType.SANDBOX_CREATED,
            "Sandbox created; execution running.",
            metadata={"backend": self.backend.kind.value, "image": plan.image},
        )
        job.lease_expires_at = _now()
        await db.commit()

        try:
            result = await asyncio.to_thread(self.backend.run, spec)
        except Exception as exc:  # pragma: no cover - backend contract violation
            result = SandboxResult(
                status=ExecutionAttemptStatus.FAILED,
                failure_class=ExecutionFailureClass.INFRASTRUCTURE,
                error_code="EXECUTION_BACKEND_ERROR",
                error_message=f"The sandbox backend failed: {type(exc).__name__}.",
            )

        transition(job, ExecutionJobStatus.COLLECTING_RESULTS)
        await self._record_attempt(db, job, attempt_number, result)
        await self._collect_outputs(db, job, result)
        await self._cleanup(db, job, result)
        await self._finalise(db, job, result)
        return job

    # -- phases -------------------------------------------------------------

    async def _record_attempt(
        self,
        db: AsyncSession,
        job: ExecutionJob,
        attempt_number: int,
        result: SandboxResult,
    ) -> None:
        attempt = ExecutionAttempt(
            job_id=job.id,
            attempt=attempt_number,
            status=result.status.value,
            backend=self.backend.kind.value,
            sandbox_id=result.sandbox_id,
            exit_code=result.exit_code,
            failure_class=result.failure_class.value if result.failure_class else None,
            error_code=result.error_code,
            error_message=result.error_message,
            resource_usage=result.resource_usage,
            duration_ms=result.duration_ms,
            completed_at=_now(),
        )
        db.add(attempt)
        await db.flush()
        metrics.incr("execution_attempts_total", outcome=result.status.value)

        if result.stdout:
            key = f"executions/{job.id}/attempt-{attempt_number}.stdout.txt"
            self._write(key, result.stdout)
            attempt.stdout_ref = key
            attempt.stdout_excerpt = _excerpt(result.stdout)
        if result.stderr:
            key = f"executions/{job.id}/attempt-{attempt_number}.stderr.txt"
            self._write(key, result.stderr)
            attempt.stderr_ref = key
            attempt.stderr_excerpt = _excerpt(result.stderr)

    async def _collect_outputs(
        self, db: AsyncSession, job: ExecutionJob, result: SandboxResult
    ) -> None:
        if not result.artifacts:
            return
        run = await self._agent_run(db, job)
        revision = await self._next_revision(db, job)
        for artifact in result.artifacts:
            self._persist_artifact(db, job, artifact, revision)
            if run is not None:
                self._link_agent_artifact(db, job, run, artifact, revision)
                revision += 1
        await db.flush()

    async def _cleanup(
        self, db: AsyncSession, job: ExecutionJob, result: SandboxResult
    ) -> None:
        if result.sandbox_id is None:
            job.cleanup_status = ExecutionCleanupStatus.SKIPPED.value
            metrics.incr("execution_cleanup_total", status=job.cleanup_status)
            return
        reaped = await asyncio.to_thread(self.backend.reap, result.sandbox_id)
        job.cleanup_status = (
            ExecutionCleanupStatus.CLEANED.value
            if reaped
            else ExecutionCleanupStatus.FAILED.value
        )
        metrics.incr("execution_cleanup_total", status=job.cleanup_status)
        await append_event(
            db,
            job.id,
            (
                ExecutionEventType.SANDBOX_DESTROYED
                if reaped
                else ExecutionEventType.SANDBOX_CLEANUP_FAILED
            ),
            "Sandbox destroyed." if reaped else "Sandbox cleanup failed.",
            metadata={"sandbox_id": result.sandbox_id},
        )
        await db.commit()

    async def _finalise(
        self, db: AsyncSession, job: ExecutionJob, result: SandboxResult
    ) -> None:
        finalized = _final_status(result.status)
        transition(job, finalized)
        metrics.incr("execution_jobs_total", status=finalized.value)
        metrics.observe(
            "execution_job_duration_seconds",
            (result.duration_ms or 0) / 1000.0,
            status=finalized.value,
        )
        job.exit_code = result.exit_code
        job.duration_ms = result.duration_ms
        job.failure_class = result.failure_class.value if result.failure_class else None
        job.error_code = result.error_code
        job.error_message = result.error_message
        if result.stdout:
            job.result_excerpt = _excerpt(result.stdout)
        now = _now()
        if finalized is ExecutionJobStatus.SUCCEEDED:
            job.completed_at = now
        elif finalized is ExecutionJobStatus.TIMED_OUT:
            job.failed_at = now
        else:
            job.failed_at = now
        job.lease_owner = None
        job.lease_expires_at = None

        event_type = {
            ExecutionJobStatus.SUCCEEDED: ExecutionEventType.EXECUTION_COMPLETED,
            ExecutionJobStatus.TIMED_OUT: ExecutionEventType.EXECUTION_TIMED_OUT,
            ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED: (
                ExecutionEventType.EXECUTION_RESOURCE_LIMIT_EXCEEDED
            ),
            ExecutionJobStatus.CANCELLED: ExecutionEventType.EXECUTION_CANCELLED,
            ExecutionJobStatus.REJECTED: ExecutionEventType.EXECUTION_REJECTED,
        }.get(finalized, ExecutionEventType.EXECUTION_FAILED)
        await append_event(
            db,
            job.id,
            event_type,
            f"Execution {'succeeded' if finalized is ExecutionJobStatus.SUCCEEDED else 'failed'}"
            f" with status {finalized.value}.",
            metadata={
                "status": finalized.value,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "failure_class": job.failure_class,
            },
        )
        await db.commit()

    async def _reject(self, db: AsyncSession, job: ExecutionJob, reason: str) -> ExecutionJob:
        transition(job, ExecutionJobStatus.REJECTED)
        metrics.incr("execution_jobs_total", status=ExecutionJobStatus.REJECTED.value)
        metrics.incr("execution_jobs_rejected_total", reason="policy")
        job.failure_class = ExecutionFailureClass.POLICY_REJECTED.value
        job.error_message = reason
        job.cleanup_status = ExecutionCleanupStatus.SKIPPED.value
        job.failed_at = _now()
        await append_event(
            db,
            job.id,
            ExecutionEventType.EXECUTION_REJECTED,
            "Execution rejected before running.",
            metadata={"reason": reason[:200]},
        )
        await db.commit()
        return job

    async def _cancel(self, db: AsyncSession, job: ExecutionJob) -> ExecutionJob:
        transition(job, ExecutionJobStatus.CANCELLED)
        metrics.incr("execution_jobs_total", status=ExecutionJobStatus.CANCELLED.value)
        job.failure_class = ExecutionFailureClass.CANCELLED.value
        job.cancelled_at = _now()
        if job.cleanup_status == ExecutionCleanupStatus.PENDING.value:
            job.cleanup_status = ExecutionCleanupStatus.SKIPPED.value
        await append_event(
            db, job.id, ExecutionEventType.EXECUTION_CANCELLED, "Execution cancelled."
        )
        await db.commit()
        return job

    # -- persistence helpers ------------------------------------------------

    def _write(self, key: str, data: bytes) -> int:
        return self.storage.save(key, io.BytesIO(data), len(data) + 1)

    def _persist_artifact(
        self,
        db: AsyncSession,
        job: ExecutionJob,
        artifact: SandboxArtifact,
        revision: int,
    ) -> None:
        kind = _classify_artifact(artifact.filename)
        key = f"executions/{job.id}/artifacts/{revision}-{artifact.filename}"
        size = self._write(key, artifact.content)
        db.add(
            ExecutionArtifact(
                job_id=job.id,
                workspace_id=job.workspace_id,
                filename=artifact.filename[:255],
                storage_key=key,
                size_bytes=size,
                mime_type=artifact.mime_type,
                kind=kind.value,
                ownership=AgentArtifactOwnership.AGENT_OWNED.value,
            )
        )

    def _link_agent_artifact(
        self,
        db: AsyncSession,
        job: ExecutionJob,
        run: AgentRun,
        artifact: SandboxArtifact,
        revision: int,
    ) -> None:
        try:
            text = artifact.content.decode("utf-8")
        except UnicodeDecodeError:
            # A binary artifact (an image, a compiled file) has no honest text
            # body to store as an agent artifact; the execution artifact keeps it.
            return
        kind = _classify_artifact(artifact.filename)
        db.add(
            AgentArtifact(
                run_id=run.id,
                task_id=job.task_id,
                artifact_type=_AGENT_ARTIFACT_TYPE.get(kind, AgentArtifactType.TEXT).value,
                content=text,
                revision=revision,
                created_by_id=job.requested_by_id,
                metadata_json={"execution_job_id": str(job.id), "filename": artifact.filename},
            )
        )

    async def _agent_run(self, db: AsyncSession, job: ExecutionJob) -> AgentRun | None:
        if job.agent_run_id is None:
            return None
        return await db.get(AgentRun, job.agent_run_id)

    async def _next_revision(self, db: AsyncSession, job: ExecutionJob) -> int:
        if job.agent_run_id is None:
            return 1
        from sqlalchemy import func, select

        current = await db.scalar(
            select(func.coalesce(func.max(AgentArtifact.revision), 0)).where(
                AgentArtifact.run_id == job.agent_run_id
            )
        )
        return int(current or 0) + 1

    def _limits(self, job: ExecutionJob) -> ResourceLimits:
        stored = job.limits_json or {}
        return ResourceLimits(
            timeout_seconds=int(stored.get("timeout_seconds", 30)),
            memory_mb=int(stored.get("memory_mb", 512)),
            cpus=float(stored.get("cpus", 1.0)),
            pids=int(stored.get("pids", 128)),
            max_output_bytes=int(stored.get("max_output_bytes", 1_000_000)),
            max_artifact_bytes=int(stored.get("max_artifact_bytes", 25 * 1024 * 1024)),
            max_artifacts=int(stored.get("max_artifacts", 50)),
        )


def _excerpt(data: bytes, limit: int = 4000) -> str:
    text = data.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[-limit:]


def _classify_artifact(filename: str) -> ExecutionArtifactKind:
    lowered = filename.lower()
    if lowered.endswith(_CHART_SUFFIXES):
        return ExecutionArtifactKind.CHART
    if lowered.endswith((".csv", ".json", ".txt", ".tsv")):
        return ExecutionArtifactKind.DATA_OUTPUT
    if lowered.endswith((".py", ".java", ".cpp", ".cc", ".c", ".h", ".hpp")):
        return ExecutionArtifactKind.SOURCE
    return ExecutionArtifactKind.GENERATED_FILE


def _final_status(attempt_status: ExecutionAttemptStatus) -> ExecutionJobStatus:
    return {
        ExecutionAttemptStatus.SUCCEEDED: ExecutionJobStatus.SUCCEEDED,
        ExecutionAttemptStatus.TIMED_OUT: ExecutionJobStatus.TIMED_OUT,
        ExecutionAttemptStatus.RESOURCE_LIMIT_EXCEEDED: ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED,
        ExecutionAttemptStatus.REJECTED: ExecutionJobStatus.REJECTED,
        ExecutionAttemptStatus.CANCELLED: ExecutionJobStatus.CANCELLED,
    }.get(attempt_status, ExecutionJobStatus.FAILED)
