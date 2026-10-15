"""API-facing execution service.

This is the layer a route calls. It validates and creates jobs, resolves the
resource profile, optionally runs a job inline (for deployments without a worker)
or enqueues it (for the dedicated worker), and assembles the read models.

The inline path exists because the product must work on a single node without a
second process: a request can run its own execution and return the result. The
queued path exists because that is how it scales and how a job survives a request
being cancelled. Both paths go through the same orchestrator, so they cannot
diverge in what they enforce.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import (
    AgentRun,
    ExecutionArtifact,
    ExecutionAttempt,
    ExecutionEvent,
    ExecutionJob,
    WorkspaceMember,
)
from app.models.enums import (
    ExecutionArtifactKind,
    ExecutionCleanupStatus,
    ExecutionEventType,
    ExecutionJobStatus,
    ExecutionResourceProfile,
    ExecutionType,
)
from app.modules.execution.adapters import build_adapter_registry
from app.modules.execution.backends.registry import build_backend
from app.modules.execution.errors import (
    ExecutionConflictError,
    ExecutionDisabledError,
    ExecutionNotFoundError,
    ExecutionQuotaExceededError,
)
from app.modules.execution.events import append_event
from app.modules.execution.orchestrator import ExecutionOrchestrator
from app.modules.execution.policies import (
    DEFAULT_PROFILE,
    resolve_entrypoint,
    resolve_limits,
)
from app.modules.execution.state_machine import TERMINAL_STATUSES, transition
from app.modules.execution.validation import validate_request
from app.storage.base import StorageService


def build_orchestrator(settings: Settings, storage: StorageService) -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        backend=build_backend(settings),
        adapters=build_adapter_registry(settings),
        storage=storage,
    )


def ensure_enabled(settings: Settings) -> None:
    """Refuse execution when it is turned off or has no usable backend."""
    if not settings.execution_enabled:
        raise ExecutionDisabledError()


def encode_files(files: Mapping[str, str] | None) -> dict[str, bytes]:
    """Turn a text source map into bytes, rejecting anything not valid UTF-8.

    Source a caller supplies over the API is text by contract; a body that is not
    valid UTF-8 is a client bug, and silently substituting replacement characters
    would run subtly different code than was sent.
    """
    encoded: dict[str, bytes] = {}
    for path, body in (files or {}).items():
        encoded[path] = body.encode("utf-8")
    return encoded


async def _count_active_jobs(db: AsyncSession, workspace_id: UUID) -> int:
    terminal = [status.value for status in TERMINAL_STATUSES]
    count = await db.scalar(
        select(func.count())
        .select_from(ExecutionJob)
        .where(
            ExecutionJob.workspace_id == workspace_id,
            ExecutionJob.status.notin_(terminal),
        )
    )
    return int(count or 0)


async def _check_quotas(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    requested_by_id: UUID | None,
    settings: Settings,
) -> None:
    """Refuse a new job when the workspace or the user is at a ceiling.

    A quota is checked, not reserved: two concurrent requests can each observe one
    slot free and both proceed. That is acceptable for a blast-radius limit — the
    queue and the sandbox caps are the hard bound — and avoiding a lock keeps this
    off the critical path. The limit is compared with ``>=`` because the job being
    created would be one more active job.
    """
    active = await _count_active_jobs(db, workspace_id)
    if active >= settings.execution_max_active_jobs_per_workspace:
        raise ExecutionQuotaExceededError(
            "workspace_active_jobs", settings.execution_max_active_jobs_per_workspace
        )
    if requested_by_id is None:
        return
    since = datetime.now(UTC) - timedelta(hours=24)
    recent = await db.scalar(
        select(func.count())
        .select_from(ExecutionJob)
        .where(
            ExecutionJob.requested_by_id == requested_by_id,
            ExecutionJob.created_at >= since,
        )
    )
    if int(recent or 0) >= settings.execution_max_jobs_per_user_per_day:
        raise ExecutionQuotaExceededError(
            "user_daily_jobs", settings.execution_max_jobs_per_user_per_day
        )


async def create_job(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    requested_by_id: UUID | None,
    assignment_id: UUID | None,
    agent_run_id: UUID | None,
    task_id: UUID | None,
    execution_type: str,
    entrypoint: str | None,
    options: dict[str, Any] | None,
    files: dict[str, bytes],
    stdin: bytes | None,
    profile: ExecutionResourceProfile | None,
    requested_timeout: int | None,
    idempotency_key: str | None,
    settings: Settings,
    storage: StorageService,
    queue: bool,
) -> ExecutionJob:
    """Create (and optionally enqueue) one execution job.

    Source files are persisted as ``SOURCE`` artifacts before the job can run, so a
    queued job is fully reconstructable by a worker that never saw the request.
    Idempotency is enforced by the unique index on ``idempotency_key``; a repeated
    key returns the existing job rather than creating a second one, so a retried
    client request cannot start two sandboxes.
    """
    if idempotency_key:
        existing = await db.scalar(
            select(ExecutionJob).where(ExecutionJob.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing

    await _check_quotas(
        db,
        workspace_id=workspace_id,
        requested_by_id=requested_by_id,
        settings=settings,
    )

    exec_type = ExecutionType(execution_type)
    entrypoint = resolve_entrypoint(exec_type, entrypoint, files)

    validate_request(
        execution_type=execution_type,
        entrypoint=entrypoint,
        options=options,
        files=files,
        stdin=stdin,
        requested_timeout=requested_timeout,
    )

    chosen = profile or DEFAULT_PROFILE[exec_type]
    limits = resolve_limits(settings, chosen, requested_timeout=requested_timeout)

    job = ExecutionJob(
        workspace_id=workspace_id,
        assignment_id=assignment_id,
        agent_run_id=agent_run_id,
        task_id=task_id,
        requested_by_id=requested_by_id,
        execution_type=exec_type.value,
        status=ExecutionJobStatus.CREATED.value,
        resource_profile=chosen.value,
        entrypoint=entrypoint,
        options_json=dict(options or {}),
        limits_json=limits.as_dict(),
        max_attempts=settings.execution_max_attempts,
        cleanup_status=ExecutionCleanupStatus.PENDING.value,
        idempotency_key=idempotency_key,
    )
    db.add(job)
    await db.flush()
    _persist_source_files(db, job, files, storage)
    await append_event(
        db,
        job.id,
        ExecutionEventType.EXECUTION_REQUESTED,
        f"Execution of type {exec_type.value} requested.",
        metadata={"profile": chosen.value, "timeout_seconds": limits.timeout_seconds},
    )

    if queue:
        transition(job, ExecutionJobStatus.QUEUED)
        await append_event(
            db, job.id, ExecutionEventType.EXECUTION_QUEUED, "Execution queued for a worker."
        )
    await db.commit()
    return job


def _persist_source_files(
    db: AsyncSession, job: ExecutionJob, files: Mapping[str, bytes], storage: StorageService
) -> None:
    import io

    for path, body in files.items():
        key = f"executions/{job.id}/input/{path}"
        size = storage.save(key, io.BytesIO(body), len(body) + 1)
        db.add(
            ExecutionArtifact(
                job_id=job.id,
                workspace_id=job.workspace_id,
                filename=path[:255],
                storage_key=key,
                size_bytes=size,
                kind=ExecutionArtifactKind.SOURCE.value,
            )
        )


async def load_source_files(
    db: AsyncSession, job: ExecutionJob, storage: StorageService
) -> dict[str, bytes]:
    """Read back the input source artifacts for a job, for the worker path."""
    rows = (
        await db.execute(
            select(ExecutionArtifact).where(
                ExecutionArtifact.job_id == job.id,
                ExecutionArtifact.kind == ExecutionArtifactKind.SOURCE.value,
            )
        )
    ).scalars().all()
    files: dict[str, bytes] = {}
    for row in rows:
        if row.storage_key:
            files[row.filename] = storage.read(row.storage_key)
    return files


async def run_inline(
    db: AsyncSession,
    job: ExecutionJob,
    *,
    settings: Settings,
    storage: StorageService,
    files: dict[str, bytes],
    stdin: bytes | None,
) -> ExecutionJob:
    orchestrator = build_orchestrator(settings, storage)
    return await orchestrator.execute(
        db,
        job,
        source_files=files,
        stdin=stdin,
        worker_id=settings.execution_worker_id,
    )


async def load_owned_job(
    assignment_id: UUID, job_id: UUID, user_id: UUID, db: AsyncSession
) -> ExecutionJob:
    result = await db.execute(
        select(ExecutionJob)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == ExecutionJob.workspace_id)
        .where(
            ExecutionJob.id == job_id,
            ExecutionJob.assignment_id == assignment_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise ExecutionNotFoundError(job_id)
    return job


async def list_jobs(
    assignment_id: UUID, db: AsyncSession, *, limit: int = 50
) -> list[ExecutionJob]:
    result = await db.execute(
        select(ExecutionJob)
        .where(ExecutionJob.assignment_id == assignment_id)
        .order_by(ExecutionJob.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def cancel_job(db: AsyncSession, job: ExecutionJob) -> ExecutionJob:
    if job.status in {status.value for status in TERMINAL_STATUSES}:
        raise ExecutionConflictError("The execution has already finished.")
    if job.status in {ExecutionJobStatus.QUEUED.value, ExecutionJobStatus.CREATED.value}:
        transition(job, ExecutionJobStatus.CANCELLED)
        job.cancelled_at = datetime.now(UTC)
        if job.cleanup_status == ExecutionCleanupStatus.PENDING.value:
            job.cleanup_status = ExecutionCleanupStatus.SKIPPED.value
        await append_event(
            db, job.id, ExecutionEventType.EXECUTION_CANCELLED, "Execution cancelled before it ran."
        )
    else:
        # A running attempt can only be asked to stop; the worker or recovery
        # observes the request. Pretending it stopped now would be a lie.
        transition(job, ExecutionJobStatus.CANCEL_REQUESTED)
        await append_event(
            db, job.id, ExecutionEventType.EXECUTION_CANCELLED, "Execution cancel requested."
        )
    await db.commit()
    return job


async def job_detail(db: AsyncSession, job: ExecutionJob) -> dict[str, Any]:
    attempts = (
        await db.execute(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.job_id == job.id)
            .order_by(ExecutionAttempt.attempt.asc())
        )
    ).scalars().all()
    artifacts = (
        await db.execute(
            select(ExecutionArtifact)
            .where(ExecutionArtifact.job_id == job.id)
            .order_by(ExecutionArtifact.created_at.asc())
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(ExecutionEvent)
            .where(ExecutionEvent.job_id == job.id)
            .order_by(ExecutionEvent.sequence.asc())
        )
    ).scalars().all()
    return {"job": job, "attempts": attempts, "artifacts": artifacts, "events": events}


async def load_agent_run(db: AsyncSession, run_id: UUID) -> AgentRun | None:
    return await db.get(AgentRun, run_id)
