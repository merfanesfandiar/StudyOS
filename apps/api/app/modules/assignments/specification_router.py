"""Read-side of the specification engine.

These endpoints are the contract a future AI layer would consume: the assembled
specification, a deterministic validation verdict, version history and the
change feed. Nothing here calls a model, parses text or makes a judgement.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models import AuditLog, User
from app.models.enums import AuditEventType
from app.modules.assignments.readiness import analyze_assignment
from app.modules.assignments.service import load_owned_assignment
from app.modules.assignments.specification import build_specification
from app.modules.assignments.versioning import current_version, get_version, list_versions
from app.schemas.common import Page, PageParams, PageResponse
from app.schemas.specification import (
    ActivityEvent,
    ActivityParams,
    AssignmentSpecificationResponse,
    ValidationResponse,
    VersionDetail,
    VersionSummary,
)
from app.services.events import record_audit

router = APIRouter(prefix="/api/v1/assignments", tags=["Specification"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get(
    "/{assignment_id}/specification",
    response_model=AssignmentSpecificationResponse,
    summary="Get the complete assignment specification",
    description=(
        "One payload with every structured section, the readiness verdict and a compact summary. "
        "This is what a future analyzer would receive: no free-text parsing, no hidden state."
    ),
)
async def get_specification(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> AssignmentSpecificationResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    report = analyze_assignment(assignment)
    return build_specification(assignment, report, await current_version(assignment.id, db))


@router.post(
    "/{assignment_id}/validate",
    response_model=ValidationResponse,
    summary="Validate the specification without changing it",
    description=(
        "Runs the deterministic completeness analyzer and records the attempt in the change feed. "
        "`is_valid` is true when no blocking check fails, which is the same gate used to mark an "
        "assignment ready. Validation never mutates the specification itself."
    ),
)
async def validate_specification(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> ValidationResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    report = analyze_assignment(assignment)
    version = await current_version(assignment.id, db)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        event_type=AuditEventType.SPECIFICATION_VALIDATED,
        entity_type="Assignment",
        entity_id=assignment.id,
        assignment_id=assignment.id,
        metadata={
            "is_valid": report.is_ready_for_analysis,
            "score": report.score,
            "failing_checks": report.failing_checks,
        },
    )
    await db.commit()
    return ValidationResponse(
        is_valid=report.is_ready_for_analysis,
        readiness=report,
        validated_at=datetime.now(UTC),
        specification_version=version,
    )


@router.post(
    "/{assignment_id}/readiness",
    response_model=ValidationResponse,
    summary="Re-run the readiness report (alias of validate)",
    description=(
        "Same deterministic report as POST /validate, kept for clients that poll readiness."
    ),
)
async def readiness_report(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> ValidationResponse:
    return await validate_specification(assignment_id, user, db)


@router.get(
    "/{assignment_id}/versions",
    response_model=PageResponse[VersionSummary],
    summary="List specification versions, newest first",
)
async def version_history(
    assignment_id: UUID,
    params: Annotated[PageParams, Query()],
    user: CurrentUser,
    db: Db,
) -> PageResponse[VersionSummary]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    versions, total = await list_versions(
        assignment.id,
        db,
        offset=(params.page - 1) * params.page_size,
        limit=params.page_size,
    )
    return PageResponse[VersionSummary](
        items=[
            VersionSummary(
                version=item.version,
                change_summary=item.change_summary,
                created_at=item.created_at,
                created_by_id=item.created_by_id,
            )
            for item in versions
        ],
        page=Page(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=max(1, -(-total // params.page_size)),
        ),
    )


@router.get(
    "/{assignment_id}/versions/{version}",
    response_model=VersionDetail,
    summary="Get one immutable version snapshot",
    description=(
        "Returns the full specification exactly as it was at that version, so a change can be "
        "diffed against the current state."
    ),
)
async def version_detail(
    assignment_id: UUID, version: int, user: CurrentUser, db: Db
) -> VersionDetail:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    entry = await get_version(assignment.id, version, db)
    return VersionDetail(
        version=entry.version,
        change_summary=entry.change_summary,
        created_at=entry.created_at,
        created_by_id=entry.created_by_id,
        snapshot=entry.snapshot,
    )


@router.get(
    "/{assignment_id}/activity",
    response_model=PageResponse[ActivityEvent],
    summary="Get the change feed for the assignment",
    description=(
        "Every specification change is recorded with a human-readable summary, so the UI can show "
        "when and what changed instead of guessing from timestamps."
    ),
)
async def activity_feed(
    assignment_id: UUID,
    params: Annotated[ActivityParams, Query()],
    user: CurrentUser,
    db: Db,
) -> PageResponse[ActivityEvent]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    filters = [AuditLog.assignment_id == assignment.id]
    if params.event_type:
        filters.append(AuditLog.event_type == params.event_type)
    total: int = (
        await db.scalar(select(func.count(AuditLog.id)).where(*filters)) or 0
    )
    result = await db.execute(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((params.page - 1) * params.page_size)
        .limit(params.page_size)
    )
    return PageResponse[ActivityEvent](
        items=[
            ActivityEvent(
                id=item.id,
                event_type=item.event_type,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                change_summary=(item.metadata_json or {}).get("change_summary"),
                metadata=item.metadata_json or {},
                created_at=item.created_at,
            )
            for item in result.scalars().all()
        ],
        page=Page(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=max(1, -(-total // params.page_size)),
        ),
    )
