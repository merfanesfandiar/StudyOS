"""The execution worker: a separate process that drains the database queue.

Run it with::

    python -m app.modules.execution.worker

It is deliberately not part of the API process. Executing untrusted code belongs
in a process whose only job is to hand work to the sandbox, so a hostile workload
cannot share an address space with request handling, and so the API can scale
independently of execution capacity.

The loop is small and honest: claim one job atomically, run it, repeat. Between
poll cycles it also sweeps for jobs whose worker was lost. There is no in-memory
queue and no state that a restart would lose — everything the worker needs is in
the row it claimed.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.modules.execution.adapters import build_adapter_registry
from app.modules.execution.backends.registry import build_backend
from app.modules.execution.orchestrator import ExecutionOrchestrator
from app.modules.execution.queue import claim_job, recover_stale_jobs
from app.modules.execution.service import load_source_files
from app.storage import get_storage

logger = logging.getLogger(__name__)


async def run_once(orchestrator: ExecutionOrchestrator, worker_id: str, storage: object) -> bool:
    """Claim and run one job. Returns ``False`` when the queue was empty."""
    settings = get_settings()
    async with SessionFactory() as db:
        job = await claim_job(db, worker_id=worker_id, settings=settings)
        if job is None:
            return False
        files = await load_source_files(db, job, storage)  # type: ignore[arg-type]
        # Per-execution stdin is not persisted; a queued job runs without it.
        await orchestrator.execute(
            db, job, source_files=files, stdin=None, worker_id=worker_id
        )
        logger.info("execution_finished job_id=%s status=%s", job.id, job.status)
        return True


async def main() -> None:  # pragma: no cover - process entrypoint
    settings = get_settings()
    storage = get_storage()
    worker_id = settings.execution_worker_id
    backend = build_backend(settings)
    orchestrator = ExecutionOrchestrator(
        backend=backend, adapters=build_adapter_registry(settings), storage=storage
    )

    stop = asyncio.Event()

    def _request_stop(*_: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    logger.info("execution_worker_started worker_id=%s backend=%s", worker_id, backend.kind.value)
    cycles = 0
    while not stop.is_set():
        try:
            did_work = await run_once(orchestrator, worker_id, storage)
        except Exception as exc:  # pragma: no cover - keep the worker alive
            logger.error("execution_worker_error type=%s", type(exc).__name__)
            did_work = False
        cycles += 1
        if cycles % 30 == 0:
            async with SessionFactory() as db:
                report = await recover_stale_jobs(db, settings)
                if report["scanned"]:
                    logger.info("execution_recovery report=%s", report)
        if not did_work:
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.execution_worker_poll_seconds)
            except TimeoutError:
                pass
    logger.info("execution_worker_stopped worker_id=%s", worker_id)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
