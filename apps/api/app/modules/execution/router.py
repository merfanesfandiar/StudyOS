"""Execution endpoints.

Everything a student can reach is scoped to an assignment they own, exactly like
the rest of the API: an execution is submitted *for* an assignment, never as a
free-floating job. The router is thin on purpose — it resolves ownership, hands
the request to the service, and returns a bounded read model. All the interesting
decisions (profiles, limits, backend availability, idempotency) happen behind the
service boundary so they cannot be bypassed by calling a different URL.

Two endpoints describe rather than act. ``/capabilities`` answers what this
deployment can actually run, so the UI can hide what is not there instead of
offering it and failing. Nothing here exposes a sandbox id or a host path.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import User
from app.modules.assignments.service import load_owned_assignment
from app.modules.execution import metrics, service
from app.modules.execution.adapters import build_adapter_registry
from app.modules.execution.backends.registry import build_backend
from app.modules.execution.external_agent import build_external_agent
from app.modules.execution.policies import DEFAULT_PROFILE, profile_ceilings
from app.schemas.common import Page, PageParams, PageResponse
from app.schemas.execution import (
    ExecutionCancelRequest,
    ExecutionCapabilitiesResponse,
    ExecutionCreateRequest,
    ExecutionJobDetailResponse,
    ExecutionJobResponse,
    ExternalAgentCapability,
)
from app.storage import get_storage

router = APIRouter(prefix="/api/v1/assignments", tags=["Execution"])
capabilities_router = APIRouter(prefix="/api/v1/executions", tags=["Execution"])

settings = get_settings()

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/{assignment_id}/executions",
    response_model=ExecutionJobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an execution for an assignment",
)
async def create_execution(
    assignment_id: UUID,
    payload: ExecutionCreateRequest,
    db: Db,
    user: CurrentUser,
) -> Any:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    service.ensure_enabled(settings)

    try:
        files = service.encode_files(payload.files)
    except UnicodeEncodeError as exc:
        raise AppError(
            422, "EXECUTION_SOURCE_NOT_UTF8", "Source files must be UTF-8 text."
        ) from exc

    stdin = payload.stdin.encode("utf-8") if payload.stdin is not None else None
    storage = get_storage()
    job = await service.create_job(
        db,
        workspace_id=assignment.workspace_id,
        requested_by_id=user.id,
        assignment_id=assignment.id,
        agent_run_id=None,
        task_id=None,
        execution_type=payload.execution_type.value,
        entrypoint=payload.entrypoint,
        options=payload.options,
        files=files,
        stdin=stdin,
        profile=payload.resource_profile,
        requested_timeout=payload.timeout_seconds,
        idempotency_key=payload.idempotency_key,
        settings=settings,
        storage=storage,
        queue=payload.mode == "queue",
    )
    if payload.mode == "sync":
        job = await service.run_inline(
            db, job, settings=settings, storage=storage, files=files, stdin=stdin
        )
    return job


@router.get(
    "/{assignment_id}/executions",
    response_model=PageResponse[ExecutionJobResponse],
    summary="List an assignment's executions, newest first",
)
async def list_executions(
    assignment_id: UUID,
    db: Db,
    user: CurrentUser,
    params: Annotated[PageParams, Depends()],
) -> Any:
    await load_owned_assignment(assignment_id, user.id, db)
    jobs = await service.list_jobs(assignment_id, db, limit=params.limit)
    total = len(jobs)
    return PageResponse[ExecutionJobResponse](
        items=[ExecutionJobResponse.model_validate(job) for job in jobs],
        page=Page(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=1 if total == 0 else (total + params.page_size - 1) // params.page_size,
        ),
    )


@router.get(
    "/{assignment_id}/executions/{job_id}",
    response_model=ExecutionJobDetailResponse,
    summary="One execution with its attempts, artifacts and event log",
)
async def get_execution(
    assignment_id: UUID, job_id: UUID, db: Db, user: CurrentUser
) -> Any:
    await load_owned_assignment(assignment_id, user.id, db)
    job = await service.load_owned_job(assignment_id, job_id, user.id, db)
    return await service.job_detail(db, job)


@router.post(
    "/{assignment_id}/executions/{job_id}/cancel",
    response_model=ExecutionJobResponse,
    summary="Cancel an execution",
)
async def cancel_execution(
    assignment_id: UUID,
    job_id: UUID,
    payload: ExecutionCancelRequest,
    db: Db,
    user: CurrentUser,
) -> Any:
    await load_owned_assignment(assignment_id, user.id, db)
    job = await service.load_owned_job(assignment_id, job_id, user.id, db)
    return await service.cancel_job(db, job)


@capabilities_router.get(
    "/capabilities",
    response_model=ExecutionCapabilitiesResponse,
    summary="What this deployment can execute",
    description=(
        "Reports the configured backend, whether it is actually available on this "
        "host, which runtimes have adapters, and the resource ceilings in force. "
        "The UI reads this to offer only what exists; a disabled or unavailable "
        "backend is reported as such rather than omitted."
    ),
)
async def capabilities(user: CurrentUser) -> Any:
    backend = build_backend(settings)
    adapters = build_adapter_registry(settings)
    external_agent = build_external_agent(settings)
    absent: list[str] = []
    if not settings.execution_enabled:
        absent.append("execution_disabled")
    if not backend.available:
        absent.append("backend_unavailable")
    if not external_agent.available:
        absent.append("external_coding_agent")
    return ExecutionCapabilitiesResponse(
        enabled=settings.execution_enabled,
        backend=backend.kind,
        available=backend.available,
        execution_types=list(adapters.execution_types()),
        resource_profiles=profile_ceilings(),
        default_profile={
            exec_type.value: profile for exec_type, profile in DEFAULT_PROFILE.items()
        },
        limits={
            "max_timeout_seconds": settings.execution_max_timeout_seconds,
            "max_memory_mb": settings.execution_max_memory_mb,
            "max_cpus": settings.execution_max_cpus,
            "max_pids": settings.execution_max_pids,
            "max_output_bytes": settings.execution_max_output_bytes,
            "max_artifact_bytes": settings.execution_max_artifact_bytes,
            "max_artifacts": settings.execution_max_artifacts,
            "max_active_jobs_per_workspace": (
                settings.execution_max_active_jobs_per_workspace
            ),
            "max_jobs_per_user_per_day": settings.execution_max_jobs_per_user_per_day,
        },
        external_agent=ExternalAgentCapability(
            kind=external_agent.kind,
            available=external_agent.available,
            reason=external_agent.unavailable_reason,
        ),
        absent_capabilities=absent,
    )


@capabilities_router.get(
    "/metrics",
    summary="Aggregate execution counters (Prometheus text format)",
    description=(
        "Process-local counters for this API replica. Counts and enum labels only; "
        "no source, no secrets. Disabled when ``execution_metrics_enabled`` is false."
    ),
)
async def execution_metrics(user: CurrentUser) -> PlainTextResponse:
    if not settings.execution_metrics_enabled:
        raise AppError(
            404, "EXECUTION_METRICS_DISABLED", "Execution metrics are not enabled."
        )
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")
