"""Build a Phase 3 planning contract from a Phase 3 analyzer output.

In production the contract comes from a persisted ``AssignmentAnalysis`` via
``app.modules.analysis.service.build_planning_contract``. The planner's tests need
the same contract without a database, and duplicating that mapping inside a test
would let the two drift apart unnoticed.

This module is therefore the single non-database path to a contract, and it is
explicitly a test and tooling seam: the mapping is the same field-for-field one
the analysis service performs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.models.enums import ClassificationSource, QuestionStatus
from app.schemas.analysis import (
    AnalyzerOutput,
    ClassifiedDomain,
    ClassifiedType,
    PlanningContractDeliverable,
    PlanningContractRequirement,
    PlanningContractResponse,
    QuestionResponse,
)


def contract_from_analyzer(
    output: AnalyzerOutput,
    *,
    analysis_id: UUID | None = None,
    assignment_id: UUID | None = None,
    is_stale: bool = False,
) -> PlanningContractResponse:
    """Project an analyzer output onto the planning contract the planner consumes."""
    return PlanningContractResponse(
        analysis_id=analysis_id or uuid4(),
        assignment_id=assignment_id or uuid4(),
        analysis_version=1,
        revision=1,
        specification_version=1,
        specification_hash="test-specification-hash",
        prompt_version=output_confidence_probe(output),
        provider="mock",
        model="mock-academic-analyzer-v1",
        is_stale=is_stale,
        assignment_types=[
            ClassifiedType(
                type=item.type,
                confidence=item.confidence,
                source=ClassificationSource.AI,
                rationale=item.rationale,
            )
            for item in output.assignment_types
        ],
        academic_domains=[
            ClassifiedDomain(
                domain=item.domain,
                confidence=item.confidence,
                source=ClassificationSource.AI,
                rationale=item.rationale,
            )
            for item in output.academic_domains
        ],
        objectives=output.objectives,
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
            for item in output.normalized_requirements
        ],
        constraints=[],
        deliverables=[
            PlanningContractDeliverable(
                key=item.key,
                title=item.title,
                description=item.description,
                required=item.required,
                format=item.format,
                related_requirements=list(item.related_requirements),
                verification_needs=list(item.verification_needs),
                depends_on=list(item.depends_on),
                uncertainty=item.uncertainty,
                confidence=item.confidence,
            )
            for item in output.deliverables
        ],
        dependencies=output.dependencies,
        work_areas=output.work_areas,
        risks=output.risks,
        verification_strategy=output.verification,
        clarification_questions=[
            QuestionResponse(
                # The persisted question row owns the id; a forged contract has no
                # row, so a fresh one is minted per question.
                id=uuid4(),
                code=item.code,
                priority=item.priority,
                status=QuestionStatus.OPEN,
                question=item.question,
                rationale=item.rationale,
                related_requirements=list(item.related_requirements),
                answer=None,
                answered_at=None,
                position=index,
            )
            for index, item in enumerate(output.clarification_questions)
        ],
        specialized_analysis=[],
        evaluation=output.evaluation,
        scope=output.scope,
    )


def output_confidence_probe(output: AnalyzerOutput) -> str:
    """A stable prompt-version stand-in for a contract built without a run row."""
    return f"analysis-confidence-{output.confidence:.2f}"


def contracts_for_fixtures(fixtures: list[Any]) -> list[tuple[str, PlanningContractResponse]]:
    """Pair each golden fixture with a contract, for cross-domain planner tests.

    Running the planner over every fixture is the cheapest way to catch a planner
    that only works for one kind of assignment, which is exactly the failure mode
    the generic-task-type requirement exists to prevent.
    """
    from app.ai import heuristics
    from app.ai.golden import golden_fixtures

    pairs: list[tuple[str, PlanningContractResponse]] = []
    for fixture in fixtures or golden_fixtures():
        raw = heuristics.analyze(fixture.payload, include_questions=True)
        output = AnalyzerOutput.model_validate(raw)
        pairs.append((fixture.name, contract_from_analyzer(output)))
    return pairs
