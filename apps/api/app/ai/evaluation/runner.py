"""Run the analyzer over the golden dataset and produce a structural report."""

from __future__ import annotations

from typing import Any

from app.ai.evaluation.metrics import EvaluationReport, FixtureResult, all_confidences_valid
from app.ai.golden import GoldenFixture, golden_fixtures
from app.ai.parsing import parse_analyzer_output
from app.ai.prompts import PROMPT_VERSION, analyzer_response_schema, build_analyzer_messages
from app.ai.provider import LLMRequest
from app.ai.providers.mock import MockLLMProvider
from app.ai.validation import ValidationContext, validate_analysis
from app.models.enums import EvidenceSourceType
from app.schemas.analysis import AnalyzerOutput, Evidence


def _context(payload: dict[str, Any], specification_hash: str) -> ValidationContext:
    requirements = payload.get("requirements") or []
    constraints = payload.get("constraints") or []
    criteria = payload.get("criteria") or []
    deliverables = payload.get("deliverables") or []
    resources = payload.get("resources") or []
    return ValidationContext(
        specification_hash=specification_hash,
        requirement_codes=frozenset(
            str(item.get("code")) for item in requirements if isinstance(item, dict)
        ),
        requirement_ids=frozenset(
            str(item.get("id")) for item in requirements if isinstance(item, dict)
        ),
        constraint_ids=frozenset(
            str(item.get("id")) for item in constraints if isinstance(item, dict)
        ),
        criterion_ids=frozenset(str(item.get("id")) for item in criteria if isinstance(item, dict)),
        deliverable_ids=frozenset(
            str(item.get("id")) for item in deliverables if isinstance(item, dict)
        ),
        document_ids=frozenset(str(item.get("id")) for item in resources if isinstance(item, dict)),
    )


def _grounded(output: AnalyzerOutput, context: ValidationContext) -> bool:
    """Every pointed evidence reference must resolve to a real source."""
    needs_id = {
        EvidenceSourceType.REQUIREMENT: context.requirement_codes | context.requirement_ids,
        EvidenceSourceType.CONSTRAINT: context.constraint_ids,
        EvidenceSourceType.CRITERION: context.criterion_ids,
        EvidenceSourceType.DELIVERABLE: context.deliverable_ids,
        EvidenceSourceType.RESOURCE: context.document_ids,
    }
    pools: list[Evidence] = []
    for requirement in output.normalized_requirements:
        pools.extend(requirement.evidence)
    for deliverable_item in output.deliverables:
        pools.extend(deliverable_item.evidence)
    for ambiguity in output.ambiguities:
        pools.extend(ambiguity.evidence)
    for contradiction in output.contradictions:
        pools.extend(contradiction.evidence)
    for missing in output.missing_information:
        pools.extend(missing.evidence)
    for risk in output.risks:
        pools.extend(risk.evidence)
    for evidence in pools:
        allowed = needs_id.get(evidence.source_type)
        if allowed is None:
            continue
        if not evidence.source_id:
            return False
        if allowed and evidence.source_id not in allowed:
            return False
    return True


async def _evaluate_fixture(fixture: GoldenFixture) -> FixtureResult:
    provider = MockLLMProvider()
    messages = build_analyzer_messages(fixture.payload, include_questions=True)
    response = await provider.complete(
        LLMRequest(
            messages=messages,
            response_schema=analyzer_response_schema(),
            prompt_version=PROMPT_VERSION,
            metadata={"analyzer_input": fixture.payload, "include_questions": True},
        )
    )
    try:
        output = parse_analyzer_output(response.content)
        context = _context(fixture.payload, "golden")
        outcome = validate_analysis(output, context)
        output = outcome.output
        schema_valid = True
        evidence_grounded = _grounded(output, context)
    except Exception as exc:  # noqa: BLE001 - evaluation must record failures, not crash
        return FixtureResult(
            name=fixture.name,
            schema_valid=False,
            classification_hit=False,
            requirement_hit=False,
            deliverable_hit=False,
            ambiguity_hit=False,
            contradiction_hit=False,
            dependency_hit=False,
            rubric_hit=False,
            evidence_grounded=False,
            confidence_valid=False,
            details=[str(exc)[:200]],
        )

    detected_types = {item.type.value for item in output.assignment_types}
    detected_domains = {item.domain.value for item in output.academic_domains}
    classification_hit = set(fixture.expected_types).issubset(detected_types) and bool(
        set(fixture.expected_domains).intersection(detected_domains)
    )
    requirement_text = " ".join(
        f"{item.title} {item.description or ''}".lower() for item in output.normalized_requirements
    )
    requirement_hit = len(output.normalized_requirements) >= fixture.min_requirements and all(
        keyword.lower() in requirement_text for keyword in fixture.expected_requirement_keywords
    )
    deliverable_text = " ".join(
        f"{item.title} {item.format or ''}".lower() for item in output.deliverables
    )
    deliverable_hit = all(
        keyword.lower() in deliverable_text for keyword in fixture.expected_deliverable_keywords
    )
    dependency_kinds = {edge.kind for edge in output.dependencies}
    metrics = {
        "classification": classification_hit,
        "requirements": requirement_hit,
        "deliverables": deliverable_hit,
        "ambiguities": (len(output.ambiguities) > 0) if fixture.expect_ambiguities else True,
        "contradictions": (len(output.contradictions) > 0)
        if fixture.expect_contradictions
        else True,
        "dependencies": set(fixture.expected_dependency_kinds).issubset(dependency_kinds),
        "rubric": output.evaluation.rubric_available if fixture.expect_rubric else True,
        "evidence": evidence_grounded,
        "confidence": all_confidences_valid(output),
    }
    failed_names = [name for name, ok in metrics.items() if not ok]
    details = [
        f"types={sorted(detected_types)}",
        f"domains={sorted(detected_domains)}",
        "failed=" + (",".join(failed_names) if failed_names else "none"),
    ]
    return FixtureResult(
        name=fixture.name,
        schema_valid=schema_valid,
        classification_hit=classification_hit,
        requirement_hit=requirement_hit,
        deliverable_hit=deliverable_hit,
        ambiguity_hit=metrics["ambiguities"],
        contradiction_hit=metrics["contradictions"],
        dependency_hit=metrics["dependencies"],
        rubric_hit=metrics["rubric"],
        evidence_grounded=evidence_grounded,
        confidence_valid=all_confidences_valid(output),
        details=details,
    )


async def run_evaluation(
    fixtures: list[GoldenFixture] | None = None,
) -> EvaluationReport:
    dataset = fixtures if fixtures is not None else golden_fixtures()
    results = [await _evaluate_fixture(fixture) for fixture in dataset]
    return EvaluationReport(results=results)
