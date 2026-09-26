"""Assignment analysis endpoints.

All endpoints enforce ownership: an analysis is loaded through the assignment
and workspace membership, and an id that is not visible returns 404 rather than
leaking existence. Review endpoints only ever touch analysis state, never the
authoritative specification.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import LLMUnavailableError, build_llm_provider
from app.ai.prompts import PROMPT_VERSION
from app.ai.provider import LLMProvider
from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.core.logging import logger
from app.db.session import get_db
from app.models import User
from app.models.enums import AnalysisRunStatus, AssignmentStatus, AuditEventType
from app.modules.analysis import service
from app.modules.analysis.input_builder import build_analyzer_input
from app.modules.analysis.orchestrator import run_analysis
from app.modules.assignments.lifecycle import ALLOWED_TRANSITIONS
from app.modules.assignments.service import load_owned_assignment
from app.modules.assignments.versioning import current_version
from app.schemas.analysis import (
    AnalysisEditRequest,
    AnalysisRequest,
    AnalysisRunResponse,
    AssignmentAnalysisResponse,
    PlanningContractResponse,
    QuestionAnswerRequest,
    QuestionDismissRequest,
    ReviewRequest,
)
from app.schemas.common import Page, PageParams, PageResponse
from app.services.events import record_audit

router = APIRouter(prefix="/api/v1/assignments", tags=["Analysis"])
settings = get_settings()

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _provider() -> LLMProvider:
    try:
        return build_llm_provider(settings)
    except LLMUnavailableError as exc:
        raise AppError(503, exc.code, exc.message, exc.details or None) from exc


@router.post(
    "/{assignment_id}/analysis",
    response_model=AssignmentAnalysisResponse,
    summary="Analyze an assignment specification",
    description=(
        "Runs the universal academic analyzer over the assignment specification and "
        "returns a structured, reviewable analysis. Repeated requests with the same "
        "specification and prompt reuse the existing analysis unless `force` is true."
    ),
)
async def create_analysis(
    assignment_id: UUID,
    payload: AnalysisRequest,
    user: CurrentUser,
    db: Db,
) -> AssignmentAnalysisResponse:
    if not settings.analysis_enabled:
        raise AppError(503, "ANALYSIS_DISABLED", "Assignment analysis is disabled.")

    assignment = await load_owned_assignment(assignment_id, user.id, db)
    provider = _provider()

    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.ASSIGNMENT_ANALYSIS_REQUESTED,
        entity_type="Assignment",
        entity_id=assignment.id,
        metadata={"provider": getattr(provider, "name", "unknown")},
    )

    if await service.active_run(assignment.id, db) is not None:
        raise AppError(
            409, "ANALYSIS_ALREADY_RUNNING", "An analysis is already running for this assignment."
        )

    analyzer_input = build_analyzer_input(assignment, user_notes=payload.user_notes)
    idempotency_key = analyzer_input.idempotency_key(
        assignment_id=str(assignment.id),
        prompt_version=PROMPT_VERSION,
        provider=provider.name,
        model=provider.model,
    )
    if not payload.force:
        existing = await service.find_idempotent(assignment.id, idempotency_key, db)
        if existing is not None:
            stale = service.is_analysis_stale(existing, assignment)
            await db.commit()
            logger.info(
                "ASSIGNMENT_ANALYSIS_REUSED",
                extra={"assignment_id": str(assignment.id), "analysis_id": str(existing.id)},
            )
            return service.build_analysis_response(existing, stale=stale)

    await service.mark_stale_analyses(db, assignment)
    specification_version = await current_version(assignment.id, db)

    try:
        result = await run_analysis(
            db,
            assignment=assignment,
            user_id=user.id,
            provider=provider,
            user_notes=payload.user_notes,
            include_questions=payload.include_questions,
            include_document_text=settings.analysis_include_document_text,
            specification_version=specification_version,
            force=payload.force,
            cost_per_1k_tokens=settings.analysis_cost_per_1k_tokens,
        )
    except AppError:
        await db.commit()
        raise

    # The assignment moves to ANALYZED only if the state machine allows it; the
    # transition is owned by the analysis layer, never set by a client.
    current = AssignmentStatus(assignment.status)
    if AssignmentStatus.ANALYZED in ALLOWED_TRANSITIONS.get(current, frozenset()):
        assignment.status = AssignmentStatus.ANALYZED.value

    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.ASSIGNMENT_ANALYSIS_COMPLETED,
        entity_type="AssignmentAnalysis",
        entity_id=result.analysis.id,
        metadata={
            "provider": result.analysis.provider,
            "model": result.analysis.model,
            "prompt_version": result.analysis.prompt_version,
            "confidence": result.analysis.confidence,
            "change_summary": "AI analysis completed.",
        },
    )
    logger.info(
        "ASSIGNMENT_ANALYSIS_COMPLETED",
        extra={"assignment_id": str(assignment.id), "analysis_id": str(result.analysis.id)},
    )
    await db.commit()
    await db.refresh(result.analysis, ["questions", "classifications"])
    return service.build_analysis_response(result.analysis, stale=False)


@router.get(
    "/{assignment_id}/analysis",
    response_model=AssignmentAnalysisResponse,
    summary="Get the most recent analysis for an assignment",
    description=(
        "Returns the newest analysis regardless of review status, so a client can show the "
        "existing result without paying for a run. Returns 404 when the assignment has never "
        "been analyzed; this endpoint never triggers an analysis itself."
    ),
)
async def get_latest_analysis(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> AssignmentAnalysisResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.latest_analysis(assignment.id, db)
    if analysis is None:
        raise AppError(404, "ANALYSIS_NOT_FOUND", "This assignment has not been analyzed yet.")
    return service.build_analysis_response(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )


@router.get(
    "/{assignment_id}/analysis/runs",
    response_model=PageResponse[AnalysisRunResponse],
    summary="List analysis runs, newest first",
)
async def list_analysis_runs(
    assignment_id: UUID,
    params: Annotated[PageParams, Query()],
    user: CurrentUser,
    db: Db,
) -> PageResponse[AnalysisRunResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    runs = await service.list_runs(assignment.id, db, limit=params.limit + params.offset)
    sliced = runs[params.offset : params.offset + params.limit]
    return PageResponse[AnalysisRunResponse](
        items=[
            AnalysisRunResponse(
                id=run.id,
                assignment_id=run.assignment_id,
                analysis_id=run.analysis_id,
                status=AnalysisRunStatus(run.status),
                provider=run.provider,
                model=run.model,
                prompt_version=run.prompt_version,
                specification_version=run.specification_version,
                input_hash=run.input_hash,
                output_hash=run.output_hash,
                started_at=run.started_at,
                completed_at=run.completed_at,
                duration_ms=run.duration_ms,
                token_usage=run.token_usage,
                estimated_cost=run.estimated_cost,
                error_code=run.error_code,
                error_message=run.error_message,
            )
            for run in sliced
        ],
        page=Page(
            page=params.page,
            page_size=params.page_size,
            total=len(runs),
            pages=max(1, -(-len(runs) // params.page_size)),
        ),
    )


@router.get(
    "/{assignment_id}/analysis/{analysis_id}",
    response_model=AssignmentAnalysisResponse,
    summary="Get one analysis",
)
async def get_analysis(
    assignment_id: UUID, analysis_id: UUID, user: CurrentUser, db: Db
) -> AssignmentAnalysisResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.load_owned_analysis(assignment_id, analysis_id, user.id, db)
    return service.build_analysis_response(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )


@router.get(
    "/{assignment_id}/analysis/{analysis_id}/planning-contract",
    response_model=PlanningContractResponse,
    summary="Get the Phase 4 planning contract for an analysis",
    description=(
        "The stable, structured input the future Planning Engine consumes. It contains "
        "requirements, constraints, deliverables, dependencies, work areas, risks, the "
        "verification strategy, clarification questions, classification and specialized "
        "analysis. A stale contract is flagged, never silently reused."
    ),
)
async def get_planning_contract(
    assignment_id: UUID, analysis_id: UUID, user: CurrentUser, db: Db
) -> PlanningContractResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.load_owned_analysis(assignment_id, analysis_id, user.id, db)
    return service.build_planning_contract(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )


@router.patch(
    "/{assignment_id}/analysis/{analysis_id}",
    response_model=AssignmentAnalysisResponse,
    summary="Edit findings or correct classification on an analysis",
    description=(
        "Overlays human corrections on the AI analysis. Authoritative assignment data is "
        "never modified."
    ),
)
async def edit_analysis(
    assignment_id: UUID,
    analysis_id: UUID,
    payload: AnalysisEditRequest,
    user: CurrentUser,
    db: Db,
) -> AssignmentAnalysisResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.load_owned_analysis(assignment_id, analysis_id, user.id, db)

    if payload.types is not None or payload.domains is not None:
        types = [item.value for item in payload.types] if payload.types is not None else None
        domains = [item.value for item in payload.domains] if payload.domains is not None else None
        await service.correct_classification(db, analysis, types=types, domains=domains)
        await record_audit(
            db,
            user_id=user.id,
            workspace_id=assignment.workspace_id,
            assignment_id=assignment.id,
            event_type=AuditEventType.ASSIGNMENT_CLASSIFICATION_CORRECTED,
            entity_type="AssignmentAnalysis",
            entity_id=analysis.id,
            metadata={"change_summary": "Classification corrected by the student."},
        )
    if payload.edits:
        await service.apply_edits(db, analysis, payload.edits)
    if payload.note is not None:
        analysis.review_note = payload.note
        await db.flush()

    await db.commit()
    return service.build_analysis_response(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )


@router.post(
    "/{assignment_id}/analysis/{analysis_id}/accept",
    response_model=AssignmentAnalysisResponse,
    summary="Accept an analysis",
)
async def accept_analysis(
    assignment_id: UUID,
    analysis_id: UUID,
    payload: ReviewRequest,
    user: CurrentUser,
    db: Db,
) -> AssignmentAnalysisResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.load_owned_analysis(assignment_id, analysis_id, user.id, db)
    await service.review(db, analysis, accept=True, user_id=user.id, note=payload.note)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.ASSIGNMENT_ANALYSIS_REVIEWED,
        entity_type="AssignmentAnalysis",
        entity_id=analysis.id,
        metadata={"decision": "ACCEPTED", "change_summary": "Analysis accepted."},
    )
    await db.commit()
    return service.build_analysis_response(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )


@router.post(
    "/{assignment_id}/analysis/{analysis_id}/reject",
    response_model=AssignmentAnalysisResponse,
    summary="Reject an analysis",
)
async def reject_analysis(
    assignment_id: UUID,
    analysis_id: UUID,
    payload: ReviewRequest,
    user: CurrentUser,
    db: Db,
) -> AssignmentAnalysisResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.load_owned_analysis(assignment_id, analysis_id, user.id, db)
    await service.review(db, analysis, accept=False, user_id=user.id, note=payload.note)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.ASSIGNMENT_ANALYSIS_REJECTED,
        entity_type="AssignmentAnalysis",
        entity_id=analysis.id,
        metadata={"decision": "REJECTED", "change_summary": "Analysis rejected."},
    )
    await db.commit()
    return service.build_analysis_response(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )


@router.post(
    "/{assignment_id}/analysis/{analysis_id}/questions/{question_id}/answer",
    response_model=AssignmentAnalysisResponse,
    summary="Answer a clarification question",
)
async def answer_question(
    assignment_id: UUID,
    analysis_id: UUID,
    question_id: UUID,
    payload: QuestionAnswerRequest,
    user: CurrentUser,
    db: Db,
) -> AssignmentAnalysisResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.load_owned_analysis(assignment_id, analysis_id, user.id, db)
    question = await service.get_question(analysis, question_id, db)
    await service.answer_question(db, question, answer=payload.answer, user_id=user.id)
    await record_audit(
        db,
        user_id=user.id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=AuditEventType.ASSIGNMENT_ANALYSIS_QUESTION_ANSWERED,
        entity_type="AnalysisQuestion",
        entity_id=question.id,
        metadata={"change_summary": f"Answered {question.code}."},
    )
    await db.commit()
    await db.refresh(analysis, ["questions"])
    return service.build_analysis_response(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )


@router.post(
    "/{assignment_id}/analysis/{analysis_id}/questions/{question_id}/dismiss",
    response_model=AssignmentAnalysisResponse,
    summary="Dismiss a clarification question",
)
async def dismiss_question(
    assignment_id: UUID,
    analysis_id: UUID,
    question_id: UUID,
    payload: QuestionDismissRequest,
    user: CurrentUser,
    db: Db,
) -> AssignmentAnalysisResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    analysis = await service.load_owned_analysis(assignment_id, analysis_id, user.id, db)
    question = await service.get_question(analysis, question_id, db)
    await service.dismiss_question(db, question, reason=payload.reason)
    await db.commit()
    await db.refresh(analysis, ["questions"])
    return service.build_analysis_response(
        analysis, stale=service.is_analysis_stale(analysis, assignment)
    )
