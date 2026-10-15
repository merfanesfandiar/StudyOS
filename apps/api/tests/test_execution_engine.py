"""The Phase 7 execution engine, driven through its real services.

The sandbox backend here is the deterministic ``mock``, which reports a scripted
outcome instead of running anything. That lets the parts that are not the sandbox
— path validation, profile clamping, the phase sequence, attempts, artifacts,
cleanup, the event log, the queue CAS and recovery — be tested end to end without
a Docker daemon. The one thing these tests cannot prove is isolation itself; that
is what the Docker backend's own command-building tests are for, and what the
daemon-gated integration test covers where a daemon exists.

The security properties are asserted, not assumed: a path with ``..`` is refused
before a job row exists, execution turned off refuses creation, and a backend that
is not configured reports a rejection rather than quietly succeeding at nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import get_settings
from app.models import User, Workspace
from app.models.enums import (
    ExecutionArtifactKind,
    ExecutionCleanupStatus,
    ExecutionFailureClass,
    ExecutionJobStatus,
    ExecutionResourceProfile,
    ExecutionType,
)
from app.modules.execution import queue, service
from app.modules.execution.backends.registry import build_backend
from app.modules.execution.errors import ExecutionDisabledError, ExecutionRejectedError
from app.modules.execution.policies import (
    DEFAULT_PROFILE,
    resolve_limits,
)
from app.storage.local import LocalStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def exec_settings(tmp_path):
    return get_settings().model_copy(
        update={
            "execution_enabled": True,
            "execution_backend": "mock",
            "execution_max_attempts": 2,
            "execution_lease_seconds": 120,
        }
    )


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "exec-uploads")



async def _workspace(db: AsyncSession) -> Workspace:
    user = User(email="exec@example.com", name="Exec Student", password_hash="x")
    db.add(user)
    await db.flush()
    workspace = Workspace(name="Exec WS", owner_id=user.id)
    db.add(workspace)
    await db.flush()
    return workspace


def _job_kwargs(workspace: Workspace, **overrides):
    base = dict(
        workspace_id=workspace.id,
        requested_by_id=workspace.owner_id,
        assignment_id=None,
        agent_run_id=None,
        task_id=None,
        execution_type=ExecutionType.PYTHON.value,
        entrypoint="main.py",
        options=None,
        profile=None,
        requested_timeout=None,
        idempotency_key=None,
        queue=False,
    )
    base.update(overrides)
    return base


async def _create(db, settings, storage, workspace, code: str, **overrides):
    return await service.create_job(
        db,
        files={"main.py": code.encode()},
        stdin=None,
        settings=settings,
        storage=storage,
        **_job_kwargs(workspace, **overrides),
    )


async def _run(db, settings, storage, workspace, code: str, **overrides):
    job = await _create(db, settings, storage, workspace, code, **overrides)
    return await service.run_inline(
        db, job, settings=settings, storage=storage, files={"main.py": code.encode()}, stdin=None
    )


# ---------------------------------------------------------------------------
# The happy path and the failure classifications
# ---------------------------------------------------------------------------


async def test_a_python_job_runs_end_to_end(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    job = await _run(db_session, exec_settings, storage, workspace, "# @mock:stdout=hello world\n")

    assert job.status == ExecutionJobStatus.SUCCEEDED.value
    assert job.exit_code == 0
    assert job.attempt_count == 1
    assert job.cleanup_status == ExecutionCleanupStatus.CLEANED.value
    assert "hello world" in (job.result_excerpt or "")

    detail = await service.job_detail(db_session, job)
    assert len(detail["attempts"]) == 1
    # The source file is persisted as a SOURCE artifact before the run.
    kinds = {a.kind for a in detail["artifacts"]}
    assert ExecutionArtifactKind.SOURCE.value in kinds
    # The event log is dense and ordered from 1.
    sequences = [e.sequence for e in detail["events"]]
    assert sequences == list(range(1, len(sequences) + 1))


async def test_a_nonzero_exit_is_a_failed_program_not_a_failed_sandbox(
    db_session, exec_settings, storage
) -> None:
    workspace = await _workspace(db_session)
    job = await _run(db_session, exec_settings, storage, workspace, "# @mock:exit=3\n")

    assert job.status == ExecutionJobStatus.FAILED.value
    assert job.exit_code == 3
    assert job.failure_class == ExecutionFailureClass.USER_CODE_FAILED.value
    assert job.cleanup_status == ExecutionCleanupStatus.CLEANED.value


async def test_a_timeout_marker_is_a_timed_out_job(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    job = await _run(db_session, exec_settings, storage, workspace, "# @mock:timeout\n")
    assert job.status == ExecutionJobStatus.TIMED_OUT.value
    assert job.failure_class == ExecutionFailureClass.TIMEOUT.value


async def test_memory_exhaustion_is_its_own_class(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    job = await _run(db_session, exec_settings, storage, workspace, "# @mock:oom\n")
    assert job.status == ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED.value
    assert job.failure_class == ExecutionFailureClass.RESOURCE_EXHAUSTED.value


async def test_an_emitted_artifact_is_persisted_and_classified(
    db_session, exec_settings, storage
) -> None:
    workspace = await _workspace(db_session)
    job = await _run(
        db_session, exec_settings, storage, workspace, "# @mock:artifact=results.csv\n"
    )
    assert job.status == ExecutionJobStatus.SUCCEEDED.value
    detail = await service.job_detail(db_session, job)
    by_name = {a.filename: a.kind for a in detail["artifacts"]}
    assert by_name.get("results.csv") == ExecutionArtifactKind.DATA_OUTPUT.value


# ---------------------------------------------------------------------------
# Refusals: disabled, unavailable, and hostile input
# ---------------------------------------------------------------------------


async def test_execution_disabled_refuses_creation(db_session, storage) -> None:
    settings = get_settings().model_copy(update={"execution_enabled": False})
    with pytest.raises(ExecutionDisabledError):
        service.ensure_enabled(settings)


async def test_a_disabled_backend_rejects_rather_than_pretending(
    db_session, storage
) -> None:
    workspace = await _workspace(db_session)
    settings = get_settings().model_copy(
        update={"execution_enabled": True, "execution_backend": "disabled"}
    )
    job = await _run(db_session, settings, storage, workspace, "print('x')\n")
    assert job.status == ExecutionJobStatus.REJECTED.value
    assert job.failure_class == ExecutionFailureClass.POLICY_REJECTED.value
    assert job.cleanup_status == ExecutionCleanupStatus.SKIPPED.value


async def test_a_path_traversal_entrypoint_is_refused_before_a_job_exists(
    db_session, exec_settings, storage
) -> None:
    workspace = await _workspace(db_session)
    with pytest.raises(ExecutionRejectedError):
        await service.create_job(
            db_session,
            files={"../outside.py": b"x"},
            stdin=None,
            settings=exec_settings,
            storage=storage,
            **_job_kwargs(workspace, entrypoint="../outside.py"),
        )
    # Nothing was persisted for a refused request.
    count = (await db_session.execute(select(service.ExecutionJob))).scalars().all()
    assert count == []


async def test_an_unknown_option_is_refused(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    with pytest.raises(ExecutionRejectedError):
        await service.create_job(
            db_session,
            files={"main.py": b"x"},
            stdin=None,
            settings=exec_settings,
            storage=storage,
            **_job_kwargs(workspace, options={"dangerous_flag": True}),
        )


# ---------------------------------------------------------------------------
# Policy: the ceilings cannot be widened from a request
# ---------------------------------------------------------------------------


def test_dynamic_profile_defaults_and_clamps() -> None:
    settings = get_settings().model_copy(
        update={"execution_max_timeout_seconds": 20, "execution_max_memory_mb": 256}
    )
    profile = DEFAULT_PROFILE[ExecutionType.DATA_ANALYSIS]
    limits = resolve_limits(settings, profile)
    assert limits.timeout_seconds == 20
    assert limits.memory_mb == 256


def test_a_requested_timeout_only_shortens() -> None:
    settings = get_settings()
    profile = DEFAULT_PROFILE[ExecutionType.PYTHON]
    longer = resolve_limits(settings, profile, requested_timeout=10_000)
    default = resolve_limits(settings, profile)
    assert longer.timeout_seconds <= default.timeout_seconds
    shorter = resolve_limits(settings, profile, requested_timeout=2)
    assert shorter.timeout_seconds == 2


def test_the_profile_base_never_exceeds_the_operator_maximum() -> None:
    settings = get_settings().model_copy(update={"execution_max_cpus": 0.5})
    limits = resolve_limits(settings, ExecutionResourceProfile.BUILD_EXECUTION)
    assert limits.cpus <= 0.5


# ---------------------------------------------------------------------------
# Idempotency and source round-trip
# ---------------------------------------------------------------------------


async def test_an_idempotency_key_returns_the_same_job(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    first = await _create(
        db_session, exec_settings, storage, workspace, "print(1)\n", idempotency_key="K1"
    )
    second = await _create(
        db_session, exec_settings, storage, workspace, "print(2)\n", idempotency_key="K1"
    )
    assert first.id == second.id


async def test_source_files_survive_a_round_trip(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    job = await _create(db_session, exec_settings, storage, workspace, "print('hi')\n")
    reloaded = await service.load_source_files(db_session, job, storage)
    assert reloaded == {"main.py": b"print('hi')\n"}


# ---------------------------------------------------------------------------
# Queue: claim is a compare-and-swap, recovery decides from the attempt count
# ---------------------------------------------------------------------------


async def test_claim_is_atomic(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    job = await _create(
        db_session, exec_settings, storage, workspace, "print(1)\n", queue=True
    )
    assert job.status == ExecutionJobStatus.QUEUED.value

    claimed = await queue.claim_job(db_session, worker_id="w1", settings=exec_settings)
    assert claimed is not None and claimed.id == job.id
    assert claimed.status == ExecutionJobStatus.STARTING.value
    assert claimed.lease_owner == "w1"

    # A second worker finds nothing: the row is no longer QUEUED.
    assert await queue.claim_job(db_session, worker_id="w2", settings=exec_settings) is None


async def test_recovery_requeues_when_attempts_remain(db_session, exec_settings, storage) -> None:
    workspace = await _workspace(db_session)
    job = await _create(db_session, exec_settings, storage, workspace, "print(1)\n", queue=True)
    job.status = ExecutionJobStatus.RUNNING.value
    job.attempt_count = 1
    job.max_attempts = 2
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
    await db_session.commit()

    report = await queue.recover_stale_jobs(db_session, exec_settings)
    await db_session.refresh(job)
    assert report["requeued"] == 1
    assert job.status == ExecutionJobStatus.QUEUED.value


async def test_recovery_fails_when_attempts_are_exhausted(
    db_session, exec_settings, storage
) -> None:
    workspace = await _workspace(db_session)
    job = await _create(db_session, exec_settings, storage, workspace, "print(1)\n", queue=True)
    job.status = ExecutionJobStatus.RUNNING.value
    job.attempt_count = 2
    job.max_attempts = 2
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
    await db_session.commit()

    report = await queue.recover_stale_jobs(db_session, exec_settings)
    await db_session.refresh(job)
    assert report["failed"] == 1
    assert job.status == ExecutionJobStatus.FAILED.value
    assert job.failure_class == ExecutionFailureClass.INFRASTRUCTURE.value


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def test_cancelling_a_queued_job_marks_it_cancelled(
    db_session, exec_settings, storage
) -> None:
    workspace = await _workspace(db_session)
    job = await _create(db_session, exec_settings, storage, workspace, "print(1)\n", queue=True)
    cancelled = await service.cancel_job(db_session, job)
    assert cancelled.status == ExecutionJobStatus.CANCELLED.value


async def test_cancelling_a_finished_job_is_a_conflict(db_session, exec_settings, storage) -> None:
    from app.modules.execution.errors import ExecutionConflictError

    workspace = await _workspace(db_session)
    job = await _run(db_session, exec_settings, storage, workspace, "print(1)\n")
    with pytest.raises(ExecutionConflictError):
        await service.cancel_job(db_session, job)


# ---------------------------------------------------------------------------
# Backend selection is total and closed
# ---------------------------------------------------------------------------


def test_backend_selection_maps_configuration_to_a_closed_set() -> None:
    from app.models.enums import ExecutionBackendKind

    assert (
        build_backend(get_settings().model_copy(update={"execution_backend": "mock"})).kind
        is ExecutionBackendKind.MOCK
    )
    assert (
        build_backend(get_settings().model_copy(update={"execution_backend": "disabled"})).kind
        is ExecutionBackendKind.DISABLED
    )


# ---------------------------------------------------------------------------
# Quotas: a ceiling refuses the next job, and a finished job frees its slot
# ---------------------------------------------------------------------------


async def test_a_full_workspace_refuses_the_next_job(
    db_session, exec_settings, storage
) -> None:
    from app.modules.execution.errors import ExecutionQuotaExceededError

    settings = exec_settings.model_copy(
        update={"execution_max_active_jobs_per_workspace": 1}
    )
    workspace = await _workspace(db_session)
    await _create(db_session, settings, storage, workspace, "print(1)\n", queue=True)

    with pytest.raises(ExecutionQuotaExceededError) as exc_info:
        await _create(db_session, settings, storage, workspace, "print(2)\n", queue=True)
    error = exc_info.value
    assert error.status_code == 429
    assert error.code == "EXECUTION_QUOTA_EXCEEDED"
    assert error.details["scope"] == "workspace_active_jobs"
    assert error.details["limit"] == 1


async def test_a_finished_job_frees_its_workspace_slot(
    db_session, exec_settings, storage
) -> None:
    settings = exec_settings.model_copy(
        update={"execution_max_active_jobs_per_workspace": 1}
    )
    workspace = await _workspace(db_session)
    # The first job runs to a terminal state, so it no longer counts as active.
    await _run(db_session, settings, storage, workspace, "print(1)\n")
    second = await _create(
        db_session, settings, storage, workspace, "print(2)\n", queue=True
    )
    assert second.status == ExecutionJobStatus.QUEUED.value


async def test_the_daily_user_quota_refuses_further_jobs(
    db_session, exec_settings, storage
) -> None:
    from app.modules.execution.errors import ExecutionQuotaExceededError

    settings = exec_settings.model_copy(
        update={"execution_max_jobs_per_user_per_day": 1}
    )
    workspace = await _workspace(db_session)
    await _create(db_session, settings, storage, workspace, "print(1)\n", queue=True)

    with pytest.raises(ExecutionQuotaExceededError) as exc_info:
        await _create(db_session, settings, storage, workspace, "print(2)\n", queue=True)
    assert exc_info.value.details["scope"] == "user_daily_jobs"


async def test_an_idempotent_repeat_does_not_consume_a_slot(
    db_session, exec_settings, storage
) -> None:
    settings = exec_settings.model_copy(
        update={"execution_max_active_jobs_per_workspace": 1}
    )
    workspace = await _workspace(db_session)
    first = await _create(
        db_session, settings, storage, workspace, "print(1)\n", queue=True, idempotency_key="k"
    )
    # A retried request with the same key returns the original job, so the quota
    # check is never reached and the caller is not punished for a retry.
    repeat = await _create(
        db_session, settings, storage, workspace, "print(1)\n", queue=True,
        idempotency_key="k",
    )
    assert repeat.id == first.id


# ---------------------------------------------------------------------------
# Named metrics: the lifecycle moves the counters a dashboard reads
# ---------------------------------------------------------------------------


async def test_a_successful_job_moves_the_named_counters(
    db_session, exec_settings, storage
) -> None:
    from app.modules.execution import metrics

    metrics.reset()
    workspace = await _workspace(db_session)
    await _run(db_session, exec_settings, storage, workspace, "# @mock:stdout=ok\n")

    snap = metrics.snapshot()
    assert snap["execution_jobs_total"] == [
        {"labels": {"status": "SUCCEEDED"}, "value": 1.0}
    ]
    assert snap["execution_attempts_total"][0]["labels"] == {"outcome": "SUCCEEDED"}
    assert snap["execution_cleanup_total"][0]["labels"] == {"status": "CLEANED"}
    assert snap["execution_job_duration_seconds_count"][0]["value"] == 1.0
    # The Prometheus rendering names the series and carries no source text.
    rendered = metrics.render()
    assert 'execution_jobs_total{status="SUCCEEDED"} 1' in rendered
    metrics.reset()


async def test_a_rejected_job_is_counted_as_a_rejection(
    db_session, exec_settings, storage
) -> None:
    from app.modules.execution import metrics

    metrics.reset()
    disabled = exec_settings.model_copy(update={"execution_backend": "disabled"})
    workspace = await _workspace(db_session)
    await _run(db_session, disabled, storage, workspace, "print(1)\n")

    snap = metrics.snapshot()
    assert snap["execution_jobs_total"] == [
        {"labels": {"status": "REJECTED"}, "value": 1.0}
    ]
    assert snap["execution_jobs_rejected_total"][0]["labels"] == {"reason": "policy"}
    metrics.reset()
