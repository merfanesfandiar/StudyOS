"""Server-Sent Events stream for one agent run's persisted event log.

Push transport over the *same* source of truth the cursor-paged endpoint
reads: ``agent_events``. Nothing here fabricates progress — a frame is only
sent when a row actually exists. The stream:

* starts from ``Last-Event-ID`` (the run-local ``sequence``), so a reconnect
  after a refresh or dropped connection resumes exactly where the client
  stopped, without re-reading history or losing events;
* emits ``run-status`` frames when the run's status changes, and ends with a
  terminal ``run-status`` frame followed by ``event: done``;
* sends comment heartbeats while idle so proxies do not buffer the stream;
* is read-only: it never mutates run state and only ever advances forward.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import AgentEvent, AgentRun

#: How often the stream polls the events table. Small enough to feel live,
#: large enough to stay cheap; tests may monkeypatch it.
EVENT_POLL_SECONDS = 1.0
#: Keepalive cadence while idle, in emitted iterations.
HEARTBEAT_EVERY = 15
#: Statuses after which the run's event log can only stop changing.
STREAM_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "BLOCKED", "PAUSED"}


def session_opener_for(request: Request) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """Open short-lived sessions through the app's ``get_db`` wiring.

    Resolving through the dependency override (when present) keeps tests on
    the same per-test database the client fixture uses; production falls back
    to the configured session factory.
    """
    override = request.app.dependency_overrides.get(get_db)
    if override is not None:
        return asynccontextmanager(override)
    return asynccontextmanager(get_db)


def _serialize_event(event: AgentEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "summary": event.summary,
        "metadata_json": event.metadata_json or {},
        "task_id": str(event.task_id) if event.task_id else None,
        "execution_id": str(event.execution_id) if event.execution_id else None,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "trace_id": event.trace_id,
        "span_id": event.span_id,
        "severity": event.severity,
        "source_component": event.source_component,
        "outcome": event.outcome,
        "duration_ms": event.duration_ms,
        "schema_version": event.schema_version,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _frame(event: str, data: dict[str, Any], *, seq: int | None = None) -> str:
    lines = [f"event: {event}"]
    if seq is not None:
        lines.append(f"id: {seq}")
    payload = json.dumps(data, separators=(",", ":"), default=str)
    for chunk in payload.split("\n"):
        lines.append(f"data: {chunk}")
    return "\n".join(lines) + "\n\n"


async def run_event_stream(
    opener: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    *,
    run_id: UUID,
    last_sequence: int,
) -> AsyncIterator[str]:
    """Yield SSE frames for everything this run does from ``last_sequence`` on.

    Ownership is checked by the route before this generator starts; the
    generator itself only reads. Each poll uses a short-lived session so no
    transaction is held open across sleeps.
    """
    last_seq = last_sequence
    last_status: str | None = None
    idle_polls = 0
    while True:
        async with opener() as db:
            run = await db.get(AgentRun, run_id)
            if run is None:
                yield _frame("error", {"code": "AGENT_RUN_NOT_FOUND"})
                yield "event: done\ndata: {}\n\n"
                return
            status = run.status
            stmt = (
                select(AgentEvent)
                .where(AgentEvent.run_id == run.id, AgentEvent.sequence > last_seq)
                .order_by(AgentEvent.sequence.asc())
                .limit(200)
            )
            events = list((await db.scalars(stmt)).all())

        for event in events:
            last_seq = event.sequence
            yield _frame("agent-event", _serialize_event(event), seq=event.sequence)
            idle_polls = 0

        if status != last_status:
            last_status = status
            yield _frame("run-status", {"run_id": str(run_id), "status": status})
            idle_polls = 0
        if status in STREAM_TERMINAL_STATUSES and not events:
            # Drain once more for stragglers, then end: the run is terminal
            # and the log is caught up, so the client needs no reconnection.
            async with opener() as db:
                stmt = (
                    select(AgentEvent)
                    .where(
                        AgentEvent.run_id == run_id,
                        AgentEvent.sequence > last_seq,
                    )
                    .order_by(AgentEvent.sequence.asc())
                    .limit(200)
                )
                trailing = list((await db.scalars(stmt)).all())
            if not trailing:
                yield "event: done\ndata: {}\n\n"
                return
            for event in trailing:
                last_seq = event.sequence
                yield _frame("agent-event", _serialize_event(event), seq=event.sequence)
            yield "event: done\ndata: {}\n\n"
            return

        idle_polls += 1
        if idle_polls % HEARTBEAT_EVERY == 0:
            yield ": keepalive\n\n"
        await asyncio.sleep(EVENT_POLL_SECONDS)
