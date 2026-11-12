"""Verification endpoints.

Every route loads its resources through workspace membership; ids that are not
visible to the caller return 404 so cross-tenant probing cannot distinguish
"not found" from "someone else's". Triggering is idempotency-keyed per
assignment so a double-submit produces one run.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import User
from app.models.enums import VerificationRunStatus
from app.modules.assignments.service import load_owned_assignment
from app.modules.verification import service as verification_service
from app.schemas.common import Page, PageResponse
from app.schemas.verification import (
    VerificationReportResponse,
    VerificationRunSummaryResponse,
    VerificationTriggerRequest,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/assignments", tags=["Verification"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _run_summary(run: verification_service.VerificationRun) -> VerificationRunSummaryResponse:  # type: ignore[name-defined]
    return VerificationRunSummaryResponse(
        id=run.id,
        assignment_id=run.assignment_id,
        status=run.status,
        scope_kind=run.scope_kind,
        trigger=run.trigger,
        verdict=run.verdict,
        completion_percentage=run.completion_percentage,
        created_at=run.created_at,
        finished_at=run.finished_at,
        previous_run_id=run.previous_run_id,
    )


@router.post(
    "/{assignment_id}/verification",
    response_model=VerificationRunSummaryResponse,
    summary="Trigger verification",
    description=(
        "Runs the verification pipeline over the assignment's artifacts. "
        "Supports full verification, artifact-scoped and requirement-scoped "
        "partial verification, and re-verification against a previous run. "
        "Idempotency-keyed per assignment."
    ),
)
async def trigger_verification(
    assignment_id: UUID,
    payload: VerificationTriggerRequest,
    user: CurrentUser,
    db: Db,
) -> VerificationRunSummaryResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)

    artifact_ids = frozenset(payload.artifact_ids) if payload.artifact_ids else None
    requirement_ids = frozenset(payload.requirement_ids) if payload.requirement_ids else None
    scope_kind = "FULL"
    if payload.re_verification_of is not None:
        scope_kind = "RE_VERIFICATION"
    elif artifact_ids and not requirement_ids:
        scope_kind = "ARTIFACT"
    elif requirement_ids and not artifact_ids:
        scope_kind = "REQUIREMENT"
    elif artifact_ids or requirement_ids:
        scope_kind = "PARTIAL"

    run = await verification_service.trigger_verification(
        assignment,
        user,
        db,
        scope_kind=scope_kind,
        artifact_ids=artifact_ids,
        requirement_ids=requirement_ids,
        previous_run_id=payload.re_verification_of,
        idempotency_key=payload.idempotency_key,
    )
    return _run_summary(run)


@router.get(
    "/{assignment_id}/verification",
    response_model=PageResponse[VerificationRunSummaryResponse],
    summary="List verification runs",
)
async def list_verification_runs(
    assignment_id: UUID,
    user: CurrentUser,
    db: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PageResponse[VerificationRunSummaryResponse]:
    await load_owned_assignment(assignment_id, user.id, db)
    runs, total = await verification_service.list_runs(
        assignment_id, user.id, db, page=page, page_size=page_size
    )
    return PageResponse(
        items=[_run_summary(run) for run in runs],
        page=Page(
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        ),
    )


@router.get(
    "/{assignment_id}/verification/{run_id}",
    response_model=VerificationReportResponse,
    summary="Get the full verification report",
)
async def get_verification_report(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> VerificationReportResponse:
    await load_owned_assignment(assignment_id, user.id, db)
    run = await verification_service.load_owned_run(run_id, user.id, db)
    if run.assignment_id != assignment_id:
        raise AppError(404, "VERIFICATION_RUN_NOT_FOUND", "Verification run not found.")
    report = await verification_service.build_run_report(run, db)
    return VerificationReportResponse(**report)


@router.post(
    "/{assignment_id}/verification/{run_id}/cancel",
    response_model=VerificationRunSummaryResponse,
    summary="Cancel a pending run",
)
async def cancel_verification_run(
    assignment_id: UUID,
    run_id: UUID,
    user: CurrentUser,
    db: Db,
) -> VerificationRunSummaryResponse:
    await load_owned_assignment(assignment_id, user.id, db)
    run = await verification_service.load_owned_run(run_id, user.id, db)
    if run.assignment_id != assignment_id:
        raise AppError(404, "VERIFICATION_RUN_NOT_FOUND", "Verification run not found.")
    # Runs execute synchronously today; cancellation only applies to runs that
    # were left PENDING by an interrupted worker, and is refused otherwise so
    # history cannot be rewritten after the fact.
    if run.status is not VerificationRunStatus.PENDING:
        raise AppError(
            409, "VERIFICATION_RUN_NOT_CANCELLABLE", "Only pending runs can be cancelled."
        )
    run.status = VerificationRunStatus.CANCELLED.value
    await db.flush()
    return _run_summary(run)
