"""The database-backed queue.

There is no broker. A job is a row, and claiming one is a compare-and-swap:
``UPDATE execution_jobs SET status='STARTING', lock_version = lock_version + 1
WHERE id = :id AND status = 'QUEUED'``. Exactly one worker can win that update, so
a redelivered or duplicated claim cannot start two sandboxes — the same guarantee
the agent runtime gets from its run lock.

Recovery is the other half of the queue. A job whose lease has expired was
claimed by a worker that then died; the recovery sweep decides, from the recorded
attempt count and the failure class, whether to requeue it or fail it. "Queued" is
never inferred from a missing timestamp; it is a status the sweep sets explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ExecutionJob
from app.models.enums import (
    ExecutionCleanupStatus,
    ExecutionEventType,
    ExecutionFailureClass,
    ExecutionJobStatus,
)
from app.modules.execution import metrics
from app.modules.execution.events import append_event
from app.modules.execution.state_machine import transition


async def claim_job(
    db: AsyncSession, *, worker_id: str, settings: Settings
) -> ExecutionJob | None:
    """Atomically claim the next queued job, or return ``None`` if the queue is empty."""
    candidate_id = await db.scalar(
        select(ExecutionJob.id)
        .where(ExecutionJob.status == ExecutionJobStatus.QUEUED.value)
        .order_by(ExecutionJob.priority.desc(), ExecutionJob.queued_at.asc())
        .limit(1)
    )
    if candidate_id is None:
        return None

    lease_expires = datetime.now(UTC)
    result = await db.execute(
        update(ExecutionJob)
        .where(
            ExecutionJob.id == candidate_id,
            ExecutionJob.status == ExecutionJobStatus.QUEUED.value,
        )
        .values(
            status=ExecutionJobStatus.STARTING.value,
            lock_version=ExecutionJob.lock_version + 1,
            lease_owner=worker_id,
            lease_expires_at=lease_expires,
        )
    )
    if getattr(result, "rowcount", 0) != 1:
        # Another worker won the race; the caller should simply poll again.
        await db.rollback()
        return None
    await db.commit()
    job = await db.get(ExecutionJob, candidate_id)
    if job is not None:
        # The UPDATE bypassed the ORM, so refresh the instance the session may
        # already hold; otherwise the caller sees the pre-claim values.
        await db.refresh(job)
    return job


async def recover_stale_jobs(db: AsyncSession, settings: Settings) -> dict[str, int]:
    """Reclaim jobs whose worker stopped reporting.

    A stale job with attempts left is re-queued; one with none left — or one that
    was already asked to cancel — is failed as an infrastructure failure. Recovery
    never *runs* work itself; it only moves a job back to a state a worker will pick
    up, so a crash loop cannot turn recovery into an execution path of its own.
    """
    now = datetime.now(UTC)
    stale = (
        await db.execute(
            select(ExecutionJob).where(
                ExecutionJob.status.in_(
                    [
                        ExecutionJobStatus.STARTING.value,
                        ExecutionJobStatus.RUNNING.value,
                        ExecutionJobStatus.COLLECTING_RESULTS.value,
                        ExecutionJobStatus.CANCEL_REQUESTED.value,
                    ]
                ),
                ExecutionJob.lease_expires_at.is_not(None),
                ExecutionJob.lease_expires_at < now,
            )
        )
    ).scalars().all()

    requeued = 0
    failed = 0
    for job in stale:
        if job.status == ExecutionJobStatus.CANCEL_REQUESTED.value:
            transition(job, ExecutionJobStatus.CANCELLED)
            job.cancelled_at = now
            job.cleanup_status = ExecutionCleanupStatus.SKIPPED.value
            await append_event(
                db, job.id, ExecutionEventType.EXECUTION_CANCELLED, "Cancelled during recovery."
            )
            failed += 1
            continue
        if (job.attempt_count or 0) < (job.max_attempts or 1):
            transition(job, ExecutionJobStatus.QUEUED)
            job.queued_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            await append_event(
                db, job.id, ExecutionEventType.EXECUTION_QUEUED, "Re-queued after a lost worker."
            )
            requeued += 1
        else:
            transition(job, ExecutionJobStatus.FAILED)
            job.failure_class = ExecutionFailureClass.INFRASTRUCTURE.value
            job.error_code = "EXECUTION_WORKER_LOST"
            job.error_message = "The worker running this execution stopped responding."
            job.failed_at = now
            job.cleanup_status = ExecutionCleanupStatus.FAILED.value
            await append_event(
                db,
                job.id,
                ExecutionEventType.EXECUTION_FAILED,
                "Execution failed: its worker was lost.",
            )
            failed += 1
    if stale:
        await db.commit()
    if requeued:
        metrics.incr("execution_recovery_total", requeued, action="requeued")
    if failed:
        metrics.incr("execution_recovery_total", failed, action="failed")
    return {"requeued": requeued, "failed": failed, "scanned": len(stale)}
