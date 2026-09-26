"""Orchestrates one analysis: input -> provider -> parse -> validate -> persist.

This is application-layer AI orchestration. It depends on the ``LLMProvider``
abstraction, never on a concrete provider. Every failure is mapped to a stable
error code and recorded on the run, so a user sees a useful message and an
operator sees what happened - without a stack trace or a hidden prompt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import (
    AnalysisInputError,
    AnalysisSchemaError,
    AnalysisSemanticError,
    LLMResponseFormatError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.ai.parsing import parse_analyzer_output
from app.ai.prompts import PROMPT_VERSION, analyzer_response_schema, build_analyzer_messages
from app.ai.provider import LLMProvider, LLMRequest
from app.ai.specialized import SpecializationContext, analyze_specializations
from app.ai.validation import ValidationContext, validate_analysis
from app.core.errors import AppError
from app.core.logging import logger
from app.models import (
    AnalysisClassification,
    AnalysisQuestion,
    AnalysisRun,
    Assignment,
    AssignmentAnalysis,
)
from app.models.enums import (
    AnalysisRunStatus,
    ClassificationKind,
    ClassificationSource,
    QuestionStatus,
)
from app.modules.analysis.input_builder import (
    ANALYSIS_VERSION,
    AnalyzerInput,
    attach_document_texts,
    build_analyzer_input,
    canonical_json,
    sha256_hex,
)
from app.schemas.analysis import AnalyzerOutput

#: Errors that mean "the model, not the assignment, misbehaved".
_PROVIDER_ERROR_MAP: tuple[tuple[type[Exception], int, str], ...] = (
    (LLMTimeoutError, 504, "LLM_TIMEOUT"),
    (LLMUnavailableError, 503, "LLM_UNAVAILABLE"),
    (AnalysisSchemaError, 502, "ANALYSIS_SCHEMA_INVALID"),
    (AnalysisSemanticError, 502, "ANALYSIS_SEMANTIC_INVALID"),
    (LLMResponseFormatError, 502, "LLM_RESPONSE_INVALID"),
)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis: AssignmentAnalysis
    run: AnalysisRun
    reused: bool


def _validation_context(assignment: Assignment, specification_hash: str) -> ValidationContext:
    return ValidationContext(
        specification_hash=specification_hash,
        requirement_codes=frozenset(
            f"REQ-{requirement.sequence:03d}" for requirement in assignment.requirements
        ),
        requirement_ids=frozenset(str(requirement.id) for requirement in assignment.requirements),
        constraint_ids=frozenset(str(item.id) for item in assignment.constraints),
        criterion_ids=frozenset(str(item.id) for item in assignment.criteria),
        deliverable_ids=frozenset(str(item.id) for item in assignment.deliverables),
        document_ids=frozenset(str(item.id) for item in assignment.documents),
        course_id=str(assignment.course_id),
    )


def _constraints_snapshot(assignment: Assignment) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item.id),
            "title": item.title,
            "description": item.description,
            "value": item.value,
            "type": item.type,
            "severity": item.severity,
        }
        for item in assignment.constraints
    ]


def _map_provider_error(exc: Exception) -> AppError:
    for error_type, status_code, code in _PROVIDER_ERROR_MAP:
        if isinstance(exc, error_type):
            message = {
                "LLM_TIMEOUT": "The analysis provider timed out. Please try again.",
                "LLM_UNAVAILABLE": "The analysis provider is unavailable right now.",
                "ANALYSIS_SCHEMA_INVALID": (
                    "The provider returned an analysis that did not match the expected structure."
                ),
                "ANALYSIS_SEMANTIC_INVALID": (
                    "The provider returned an analysis that failed consistency checks."
                ),
                "LLM_RESPONSE_INVALID": "The provider returned an unreadable response.",
            }[code]
            details: dict[str, Any] = {}
            if isinstance(exc, AnalysisSemanticError):
                details = {"violations": exc.violations}
            else:
                raw_details = getattr(exc, "details", None)
                if isinstance(raw_details, dict):
                    details = dict(raw_details)
            return AppError(status_code, code, message, details or None)
    if isinstance(exc, AnalysisInputError):
        return AppError(422, exc.code, exc.message, exc.details or None)
    return AppError(502, "ANALYSIS_FAILED", "The analysis could not be completed.")


async def _extract_document_texts(
    assignment: Assignment, analyzer_input: AnalyzerInput, include_text: bool
) -> AnalyzerInput:
    """Attach text for resources that are plain text, when enabled."""
    if not include_text:
        return analyzer_input
    from app.modules.analysis.extraction import extract_texts

    texts = await extract_texts(assignment.documents)
    if not texts:
        return analyzer_input
    return attach_document_texts(analyzer_input, texts)


async def run_analysis(
    db: AsyncSession,
    *,
    assignment: Assignment,
    user_id: UUID,
    provider: LLMProvider,
    user_notes: str | None,
    include_questions: bool,
    include_document_text: bool,
    specification_version: int,
    force: bool = False,
    cost_per_1k_tokens: float = 0.0,
) -> AnalysisResult:
    """Run the analyzer once and persist the result. Raises ``AppError`` on failure."""
    analyzer_input = build_analyzer_input(assignment, user_notes=user_notes)
    analyzer_input = await _extract_document_texts(
        assignment, analyzer_input, include_document_text
    )
    if not (assignment.description or assignment.requirements):
        raise AppError(
            422,
            "ANALYSIS_INPUT_INVALID",
            "The assignment has too little information to analyze. Add a description or at "
            "least one requirement first.",
        )

    base_key = analyzer_input.idempotency_key(
        assignment_id=str(assignment.id),
        prompt_version=PROMPT_VERSION,
        provider=provider.name,
        model=provider.model,
    )
    # A forced re-run must be a distinct row, so it gets a distinct key rather
    # than colliding with the analysis it deliberately replaces.
    idempotency_key = (
        base_key if not force else sha256_hex(f"{base_key}:{uuid4().hex}")
    )

    messages = build_analyzer_messages(analyzer_input.payload, include_questions=include_questions)
    request = LLMRequest(
        messages=messages,
        response_schema=analyzer_response_schema(),
        prompt_version=PROMPT_VERSION,
        max_output_tokens=4000,
        metadata={
            "analyzer_input": analyzer_input.payload,
            "include_questions": include_questions,
        },
    )

    run = AnalysisRun(
        assignment_id=assignment.id,
        status=AnalysisRunStatus.RUNNING.value,
        provider=provider.name,
        model=provider.model,
        prompt_version=PROMPT_VERSION,
        specification_version=specification_version,
        input_hash=analyzer_input.input_hash,
        idempotency_key=idempotency_key,
        started_at=datetime.now(UTC),
        triggered_by_id=user_id,
    )
    db.add(run)
    await db.flush()
    logger.info(
        "ASSIGNMENT_ANALYSIS_STARTED",
        extra={"run_id": str(run.id), "assignment_id": str(assignment.id)},
    )

    started = time.perf_counter()
    try:
        response = await provider.complete(request)
        output = parse_analyzer_output(response.content)
        context = _validation_context(assignment, analyzer_input.specification_hash)
        outcome = validate_analysis(output, context)
        output = outcome.output
        specializations = analyze_specializations(
            SpecializationContext(payload=analyzer_input.payload, analysis=output)
        )

        payload = output.model_dump(mode="json")
        payload["specialized_analysis"] = [item.model_dump(mode="json") for item in specializations]
        payload["constraints_snapshot"] = _constraints_snapshot(assignment)
        payload["specification_hash"] = analyzer_input.specification_hash
        payload["input_hash"] = analyzer_input.input_hash
        payload["validation_warnings"] = outcome.warnings

        analysis = AssignmentAnalysis(
            assignment_id=assignment.id,
            analysis_version=ANALYSIS_VERSION,
            specification_version=specification_version,
            specification_hash=analyzer_input.specification_hash,
            idempotency_key=idempotency_key,
            prompt_version=PROMPT_VERSION,
            provider=response.provider,
            model=response.model,
            summary=output.summary,
            confidence=output.confidence,
            payload=payload,
        )
        db.add(analysis)
        await db.flush()
        _persist_classifications(db, analysis, output)
        _persist_questions(db, analysis, output)

        duration_ms = int((time.perf_counter() - started) * 1000)
        run.analysis_id = analysis.id
        run.status = AnalysisRunStatus.SUCCEEDED.value
        run.completed_at = datetime.now(UTC)
        run.duration_ms = duration_ms
        run.output_hash = sha256_hex(canonical_json(payload))
        run.token_usage = response.usage.as_dict()
        if cost_per_1k_tokens:
            run.estimated_cost = (
                Decimal(response.usage.total_tokens)
                / Decimal(1000)
                * Decimal(str(cost_per_1k_tokens))
            ).quantize(Decimal("0.000001"))
        return AnalysisResult(analysis=analysis, run=run, reused=False)
    except AppError:
        await _fail_run(db, run, "ANALYSIS_INPUT_INVALID", "Invalid analyzer input.", started)
        raise
    except Exception as exc:  # noqa: BLE001 - mapped below, never surfaced raw
        app_error = _map_provider_error(exc)
        await _fail_run(db, run, app_error.code, app_error.message, started)
        logger.warning(
            "ASSIGNMENT_ANALYSIS_FAILED",
            extra={"run_id": str(run.id), "error_type": type(exc).__name__},
        )
        raise app_error from exc


async def _fail_run(
    db: AsyncSession, run: AnalysisRun, code: str, message: str, started: float
) -> None:
    run.status = AnalysisRunStatus.FAILED.value
    run.completed_at = datetime.now(UTC)
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    run.error_code = code[:60]
    run.error_message = message[:500]
    await db.flush()


def _persist_classifications(
    db: AsyncSession, analysis: AssignmentAnalysis, output: AnalyzerOutput
) -> None:
    for position, typed in enumerate(output.assignment_types):
        db.add(
            AnalysisClassification(
                analysis_id=analysis.id,
                kind=ClassificationKind.TYPE.value,
                value=typed.type.value,
                confidence=typed.confidence,
                source=ClassificationSource.AI.value,
                position=position,
            )
        )
    for position, domain in enumerate(output.academic_domains):
        db.add(
            AnalysisClassification(
                analysis_id=analysis.id,
                kind=ClassificationKind.DOMAIN.value,
                value=domain.domain.value,
                confidence=domain.confidence,
                source=ClassificationSource.AI.value,
                position=position,
            )
        )


def _persist_questions(
    db: AsyncSession, analysis: AssignmentAnalysis, output: AnalyzerOutput
) -> None:
    for position, question in enumerate(output.clarification_questions):
        db.add(
            AnalysisQuestion(
                analysis_id=analysis.id,
                code=question.code,
                priority=question.priority.value,
                question=question.question,
                rationale=question.rationale,
                status=QuestionStatus.OPEN.value,
                position=position,
            )
        )
