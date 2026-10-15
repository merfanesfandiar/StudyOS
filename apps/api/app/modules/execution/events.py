"""Append-only execution telemetry (§30).

One function writes every execution event. It stamps a dense per-job sequence
inside the same transaction that changed the job, so the event log and the job's
state cannot disagree: the ``(job_id, sequence)`` unique constraint is the
backstop that turns a lost writer into a loud failure rather than a history with a
hole in it.

Events never carry source code or secrets. A ``summary`` is one sentence for a
person; ``metadata_json`` is bounded structured detail (counts, sizes, exit codes).
An ordinary compiler error is ``EXECUTION_FAILED``; only a genuine breach of the
boundary is ``POLICY_VIOLATION_DETECTED``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExecutionEvent
from app.models.enums import ExecutionEventType


async def append_event(
    db: AsyncSession,
    job_id: UUID,
    event_type: ExecutionEventType,
    summary: str,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionEvent:
    """Append one event, computing the next per-job sequence."""
    current = await db.scalar(
        select(func.coalesce(func.max(ExecutionEvent.sequence), 0)).where(
            ExecutionEvent.job_id == job_id
        )
    )
    event = ExecutionEvent(
        job_id=job_id,
        sequence=int(current or 0) + 1,
        event_type=event_type.value,
        summary=summary[:500],
        metadata_json=dict(metadata or {}),
    )
    db.add(event)
    await db.flush()
    return event
