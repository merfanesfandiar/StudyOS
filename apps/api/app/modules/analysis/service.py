"""Analysis persistence, retrieval, staleness and human review.

The invariant this module protects: an analysis is an *interpretation*. Review
actions never write to the authoritative specification tables. When an analysis
no longer matches the specification it was computed against it is marked stale
rather than silently reused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import (
    AnalysisClassification,
    AnalysisQuestion,
    AnalysisRun,
    Assignment,
    AssignmentAnalysis,
    WorkspaceMember,
)
from app.models.enums import (
    AcademicDomain,
    AnalysisReviewStatus,
    AssignmentType,
    ClassificationKind,
    ClassificationSource,
    QuestionPriority,
    QuestionStatus,
)
from app.modules.analysis.input_builder import build_analyzer_input
from app.schemas.analysis import (
    AnalyzerOutput,
    AssignmentAnalysisResponse,
    ClassifiedDomain,
    ClassifiedType,
    ConstraintSnapshot,
    Evidence,
    PlanningContractDeliverable,
    PlanningContractRequirement,
    PlanningContractResponse,
    QuestionResponse,
    SpecializedAnalysis,
)

ANALYSIS_LOADERS = (
    selectinload(AssignmentAnalysis.questions),
    selectinload(AssignmentAnalysis.classifications),
)


async def load_owned_analysis(
    assignment_id: UUID, analysis_id: UUID, user_id: UUID, db: AsyncSession
) -> AssignmentAnalysis:
    result = await db.execute(
        select(AssignmentAnalysis)
        .join(Assignment, Assignment.id == AssignmentAnalysis.assignment_id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Assignment.workspace_id)
        .where(
            AssignmentAnalysis.id == analysis_id,
            AssignmentAnalysis.assignment_id == assignment_id,
            WorkspaceMember.user_id == user_id,
        )
        .options(*ANALYSIS_LOADERS)
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        raise AppError(404, "ANALYSIS_NOT_FOUND", "Analysis not found.")
    return analysis


async def find_idempotent(
    assignment_id: UUID, idempotency_key: str, db: AsyncSession
) -> AssignmentAnalysis | None:
    result = await db.execute(
        select(AssignmentAnalysis)
        .where(
            AssignmentAnalysis.assignment_id == assignment_id,
            AssignmentAnalysis.idempotency_key == idempotency_key,
            AssignmentAnalysis.is_stale.is_(False),
        )
        .options(*ANALYSIS_LOADERS)
    )
    return result.scalar_one_or_none()


async def list_analyses(assignment_id: UUID, db: AsyncSession) -> list[AssignmentAnalysis]:
    result = await db.execute(
        select(AssignmentAnalysis)
        .where(AssignmentAnalysis.assignment_id == assignment_id)
        .options(*ANALYSIS_LOADERS)
        .order_by(AssignmentAnalysis.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def latest_analysis(assignment_id: UUID, db: AsyncSession) -> AssignmentAnalysis | None:
    result = await db.execute(
        select(AssignmentAnalysis)
        .where(AssignmentAnalysis.assignment_id == assignment_id)
        .options(*ANALYSIS_LOADERS)
        .order_by(AssignmentAnalysis.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_runs(assignment_id: UUID, db: AsyncSession, *, limit: int) -> list[AnalysisRun]:
    result = await db.execute(
        select(AnalysisRun)
        .where(AnalysisRun.assignment_id == assignment_id)
        .order_by(AnalysisRun.started_at.desc(), AnalysisRun.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def active_run(assignment_id: UUID, db: AsyncSession) -> AnalysisRun | None:
    run: AnalysisRun | None = await db.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.assignment_id == assignment_id,
            AnalysisRun.status == "RUNNING",
        )
        .limit(1)
    )
    return run


async def mark_stale_analyses(db: AsyncSession, assignment: Assignment) -> list[AssignmentAnalysis]:
    """Mark analyses whose specification hash no longer matches as stale."""
    current_hash = build_analyzer_input(assignment).specification_hash
    result = await db.execute(
        select(AssignmentAnalysis).where(
            AssignmentAnalysis.assignment_id == assignment.id,
            AssignmentAnalysis.is_stale.is_(False),
            AssignmentAnalysis.specification_hash != current_hash,
        )
    )
    stale = list(result.scalars().all())
    moment = datetime.now(UTC)
    for analysis in stale:
        analysis.is_stale = True
        analysis.stale_at = moment
    return stale


def is_analysis_stale(analysis: AssignmentAnalysis, assignment: Assignment) -> bool:
    if analysis.is_stale:
        return True
    return analysis.specification_hash != build_analyzer_input(assignment).specification_hash


def effective_payload(analysis: AssignmentAnalysis) -> dict[str, Any]:
    """The AI snapshot with any human edits overlaid on top."""
    payload = dict(analysis.payload)
    if analysis.edited_payload:
        for key, value in analysis.edited_payload.items():
            payload[key] = value
    return payload


def _effective_classification(
    analysis: AssignmentAnalysis, kind: ClassificationKind
) -> list[AnalysisClassification]:
    rows = [row for row in analysis.classifications if row.kind == kind.value]
    user_rows = [row for row in rows if row.source == ClassificationSource.USER.value]
    effective = user_rows or [row for row in rows if row.source == ClassificationSource.AI.value]
    return sorted(effective, key=lambda row: row.position)


def build_analysis_response(
    analysis: AssignmentAnalysis, *, stale: bool
) -> AssignmentAnalysisResponse:
    payload = effective_payload(analysis)
    output = AnalyzerOutput.model_validate(payload)

    types = [
        ClassifiedType(
            type=AssignmentType(row.value),
            confidence=row.confidence,
            source=ClassificationSource(row.source),
        )
        for row in _effective_classification(analysis, ClassificationKind.TYPE)
    ]
    domains = [
        ClassifiedDomain(
            domain=AcademicDomain(row.value),
            confidence=row.confidence,
            source=ClassificationSource(row.source),
        )
        for row in _effective_classification(analysis, ClassificationKind.DOMAIN)
    ]

    constraints = [
        ConstraintSnapshot.model_validate(item) for item in payload.get("constraints_snapshot", [])
    ]
    specializations = [
        SpecializedAnalysis.model_validate(item) for item in payload.get("specialized_analysis", [])
    ]

    evidence: list[Evidence] = []
    for requirement in output.normalized_requirements:
        evidence.extend(requirement.evidence)
    for deliverable in output.deliverables:
        evidence.extend(deliverable.evidence)
    for collection in (
        output.ambiguities,
        output.contradictions,
        output.missing_information,
        output.assumptions,
        output.risks,
    ):
        for item in collection:
            evidence.extend(item.evidence)

    questions = sorted(analysis.questions, key=lambda item: (item.position, str(item.id)))
    return AssignmentAnalysisResponse(
        id=analysis.id,
        assignment_id=analysis.assignment_id,
        analysis_version=analysis.analysis_version,
        specification_version=analysis.specification_version,
        specification_hash=analysis.specification_hash,
        prompt_version=analysis.prompt_version,
        provider=analysis.provider,
        model=analysis.model,
        status=AnalysisReviewStatus(analysis.status),
        is_stale=stale,
        stale_at=analysis.stale_at,
        summary=analysis.summary,
        confidence=analysis.confidence,
        assignment_types=types,
        academic_domains=domains,
        objectives=output.objectives,
        normalized_requirements=output.normalized_requirements,
        constraints=constraints,
        ambiguities=output.ambiguities,
        contradictions=output.contradictions,
        missing_information=output.missing_information,
        assumptions=output.assumptions,
        clarification_questions=[
            QuestionResponse(
                id=question.id,
                code=question.code,
                priority=QuestionPriority(question.priority),
                status=QuestionStatus(question.status),
                question=question.question,
                rationale=question.rationale,
                related_requirements=[],
                answer=question.answer,
                answered_at=question.answered_at,
                position=question.position,
            )
            for question in questions
        ],
        deliverables=output.deliverables,
        evaluation=output.evaluation,
        scope=output.scope,
        work_areas=output.work_areas,
        resources=output.resources,
        dependencies=output.dependencies,
        verification=output.verification,
        risks=output.risks,
        specialized_analysis=specializations,
        evidence=evidence,
        edited=analysis.edited_payload is not None,
        reviewed_at=analysis.reviewed_at,
        review_note=analysis.review_note,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


def build_planning_contract(
    analysis: AssignmentAnalysis, *, stale: bool
) -> PlanningContractResponse:
    """The frozen, structured contract the Phase 4 Planning Engine consumes."""
    response = build_analysis_response(analysis, stale=stale)
    return PlanningContractResponse(
        analysis_id=analysis.id,
        assignment_id=analysis.assignment_id,
        analysis_version=analysis.analysis_version,
        specification_version=analysis.specification_version,
        specification_hash=analysis.specification_hash,
        prompt_version=analysis.prompt_version,
        provider=analysis.provider,
        model=analysis.model,
        is_stale=stale,
        assignment_types=response.assignment_types,
        academic_domains=response.academic_domains,
        objectives=response.objectives,
        requirements=[
            PlanningContractRequirement(
                key=item.key,
                title=item.title,
                description=item.description,
                category=item.category,
                priority=item.priority,
                required=item.required,
                source_kind=item.source,
                source_reference=item.source_reference,
                confidence=item.confidence,
            )
            for item in response.normalized_requirements
        ],
        constraints=response.constraints,
        deliverables=[
            PlanningContractDeliverable(
                key=item.key,
                title=item.title,
                description=item.description,
                required=item.required,
                format=item.format,
                related_requirements=item.related_requirements,
                verification_needs=item.verification_needs,
                depends_on=item.depends_on,
                uncertainty=item.uncertainty,
                confidence=item.confidence,
            )
            for item in response.deliverables
        ],
        dependencies=response.dependencies,
        work_areas=response.work_areas,
        risks=response.risks,
        verification_strategy=response.verification,
        clarification_questions=response.clarification_questions,
        specialized_analysis=response.specialized_analysis,
        evaluation=response.evaluation,
        scope=response.scope,
    )


async def correct_classification(
    db: AsyncSession,
    analysis: AssignmentAnalysis,
    *,
    types: list[str] | None,
    domains: list[str] | None,
) -> None:
    """Replace the user's classification rows for the supplied kinds."""
    if types is not None:
        await db.execute(
            delete(AnalysisClassification).where(
                AnalysisClassification.analysis_id == analysis.id,
                AnalysisClassification.kind == ClassificationKind.TYPE.value,
                AnalysisClassification.source == ClassificationSource.USER.value,
            )
        )
        for position, value in enumerate(types):
            db.add(
                AnalysisClassification(
                    analysis_id=analysis.id,
                    kind=ClassificationKind.TYPE.value,
                    value=value,
                    confidence=1.0,
                    source=ClassificationSource.USER.value,
                    position=position,
                )
            )
    if domains is not None:
        await db.execute(
            delete(AnalysisClassification).where(
                AnalysisClassification.analysis_id == analysis.id,
                AnalysisClassification.kind == ClassificationKind.DOMAIN.value,
                AnalysisClassification.source == ClassificationSource.USER.value,
            )
        )
        for position, value in enumerate(domains):
            db.add(
                AnalysisClassification(
                    analysis_id=analysis.id,
                    kind=ClassificationKind.DOMAIN.value,
                    value=value,
                    confidence=1.0,
                    source=ClassificationSource.USER.value,
                    position=position,
                )
            )
    await db.flush()
    await db.refresh(analysis, ["classifications"])


async def apply_edits(
    db: AsyncSession, analysis: AssignmentAnalysis, edits: dict[str, Any]
) -> None:
    """Overlay human edits on the AI payload, rejecting anything that breaks the shape."""
    overlay = dict(analysis.edited_payload or {})
    overlay.update(edits)
    merged = dict(analysis.payload)
    merged.update(overlay)
    try:
        AnalyzerOutput.model_validate(merged)
    except Exception as exc:  # noqa: BLE001
        raise AppError(
            422,
            "ANALYSIS_EDIT_INVALID",
            "That edit does not fit the analysis structure.",
            {"reason": str(exc)[:200]},
        ) from exc
    analysis.edited_payload = overlay
    await db.flush()


async def review(
    db: AsyncSession,
    analysis: AssignmentAnalysis,
    *,
    accept: bool,
    user_id: UUID,
    note: str | None,
) -> None:
    analysis.status = (
        AnalysisReviewStatus.ACCEPTED.value if accept else AnalysisReviewStatus.REJECTED.value
    )
    analysis.reviewed_by_id = user_id
    analysis.reviewed_at = datetime.now(UTC)
    analysis.review_note = note
    await db.flush()


async def get_question(
    analysis: AssignmentAnalysis, question_id: UUID, db: AsyncSession
) -> AnalysisQuestion:
    question = await db.scalar(
        select(AnalysisQuestion).where(
            AnalysisQuestion.id == question_id,
            AnalysisQuestion.analysis_id == analysis.id,
        )
    )
    if question is None:
        raise AppError(404, "QUESTION_NOT_FOUND", "Clarification question not found.")
    return question


async def answer_question(
    db: AsyncSession,
    question: AnalysisQuestion,
    *,
    answer: str,
    user_id: UUID,
) -> None:
    question.answer = answer
    question.status = QuestionStatus.ANSWERED.value
    question.answered_by_id = user_id
    question.answered_at = datetime.now(UTC)
    await db.flush()


async def dismiss_question(
    db: AsyncSession, question: AnalysisQuestion, *, reason: str | None
) -> None:
    question.status = QuestionStatus.DISMISSED.value
    if reason:
        question.rationale = f"{question.rationale or ''}\nDismissed: {reason}".strip()
    await db.flush()
