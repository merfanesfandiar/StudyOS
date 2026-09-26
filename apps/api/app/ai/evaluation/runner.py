"""Run the analyzer pipeline over the golden dataset using recorded transcripts.

The report answers two questions separately:

* Did the pipeline do its job on each fixture? (quality rates)
* Would the report notice if it had not? (mutation detection)

The second question is the point. A suite that reports 1.0 on everything tells you
nothing unless it can also fail, so every fixture's output is corrupted in ways a
real system could ship and the checks must reject each one.

The answers being scored are **recorded**, not computed. ``RecordedTranscriptProvider``
replays hand-written model-style outputs from ``app.ai.evaluation.transcripts``, so
the thing under test is the pipeline (parsing, schema and semantic validation,
coverage, grounding) rather than the heuristic engine that used to generate the very
words being graded. This still does not measure how a real model would answer; that
needs credentials and is deliberately not in CI.
"""

from __future__ import annotations

from typing import Any

from app.ai.evaluation.metrics import (
    EvaluationReport,
    FixtureResult,
    all_confidences_valid,
    coverage_of,
    discrimination,
    tally_grounding,
)
from app.ai.evaluation.metrics_types import MutationResult
from app.ai.evaluation.provider import RecordedTranscriptProvider
from app.ai.golden import GoldenFixture, golden_fixtures
from app.ai.parsing import parse_analyzer_output
from app.ai.prompts import PROMPT_VERSION, analyzer_response_schema, build_analyzer_messages
from app.ai.provider import LLMRequest
from app.ai.validation import ValidationContext, validate_analysis
from app.models.enums import EvidenceSourceType
from app.schemas.analysis import AnalyzerOutput


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


def allowed_sources(context: ValidationContext) -> dict[EvidenceSourceType, frozenset[str]]:
    """The id pool each evidence source type may legitimately point into."""
    return {
        EvidenceSourceType.REQUIREMENT: context.requirement_codes | context.requirement_ids,
        EvidenceSourceType.CONSTRAINT: context.constraint_ids,
        EvidenceSourceType.CRITERION: context.criterion_ids,
        EvidenceSourceType.DELIVERABLE: context.deliverable_ids,
        EvidenceSourceType.RESOURCE: context.document_ids,
    }


def _brief_requirements(payload: dict[str, Any]) -> list[str]:
    """The requirements as the student wrote them, used as the coverage target."""
    return [
        str(item.get("title") or item.get("description") or "")
        for item in (payload.get("requirements") or [])
        if isinstance(item, dict)
    ]


def _brief_deliverables(payload: dict[str, Any]) -> list[str]:
    return [
        str(item.get("title") or "")
        for item in (payload.get("deliverables") or [])
        if isinstance(item, dict)
    ]


async def _analyze(fixture: GoldenFixture) -> AnalyzerOutput:
    # Recorded transcripts, not MockLLMProvider. The mock provider runs the
    # heuristic engine, so using it here meant the golden dataset scored the
    # engine against metrics derived from the engine.
    provider = RecordedTranscriptProvider()
    response = await provider.complete(
        LLMRequest(
            messages=build_analyzer_messages(fixture.payload, include_questions=True),
            response_schema=analyzer_response_schema(),
            prompt_version=PROMPT_VERSION,
            metadata={
                "analyzer_input": fixture.payload,
                "include_questions": True,
                "fixture_name": fixture.name,
            },
        )
    )
    output = parse_analyzer_output(response.content)
    return validate_analysis(output, _context(fixture.payload, "golden")).output


async def _evaluate_fixture(
    fixture: GoldenFixture,
) -> tuple[FixtureResult, list[MutationResult]]:
    try:
        output = await _analyze(fixture)
    except Exception as exc:  # noqa: BLE001 - evaluation records failures, never crashes
        return (
            FixtureResult(
                name=fixture.name,
                schema_valid=False,
                classification_hit=False,
                requirement_coverage=None,
                deliverable_hit=False,
                ambiguity_hit=False,
                contradiction_hit=False,
                dependency_hit=False,
                rubric_hit=False,
                confidence_valid=False,
                details=[str(exc)[:200]],
            ),
            [],
        )

    context = _context(fixture.payload, "golden")
    pools = allowed_sources(context)
    tally = tally_grounding(output, pools)
    mutations = discrimination(output, pools)

    detected_types = {item.type.value for item in output.assignment_types}
    detected_domains = {item.domain.value for item in output.academic_domains}
    classification_hit = set(fixture.expected_types).issubset(detected_types) and bool(
        set(fixture.expected_domains).intersection(detected_domains)
    )

    coverage = coverage_of(
        _brief_requirements(fixture.payload),
        [f"{item.title} {item.description or ''}" for item in output.normalized_requirements],
    )
    deliverable_coverage = coverage_of(
        _brief_deliverables(fixture.payload),
        [f"{item.title} {item.format or ''}" for item in output.deliverables],
    )
    dependency_kinds = {edge.kind for edge in output.dependencies}

    checks = {
        "classification": classification_hit,
        "deliverables": deliverable_coverage >= 0.99 or not _brief_deliverables(fixture.payload),
        "ambiguities": (len(output.ambiguities) > 0) if fixture.expect_ambiguities else True,
        "contradictions": (len(output.contradictions) > 0)
        if fixture.expect_contradictions
        else True,
        "dependencies": set(fixture.expected_dependency_kinds).issubset(dependency_kinds),
        "rubric": output.evaluation.rubric_available if fixture.expect_rubric else True,
        "confidence": all_confidences_valid(output),
        "grounding": tally.ungrounded == 0,
    }
    failed = [name for name, ok in checks.items() if not ok]
    details = [
        f"types={sorted(detected_types)}",
        f"domains={sorted(detected_domains)}",
        f"assertions={tally.total}",
        f"ungrounded={tally.ungrounded}",
        f"failed={','.join(failed) if failed else 'none'}",
        *tally.offenders[:3],
    ]
    return (
        FixtureResult(
            name=fixture.name,
            schema_valid=True,
            classification_hit=classification_hit,
            requirement_coverage=coverage,
            deliverable_hit=checks["deliverables"],
            ambiguity_hit=checks["ambiguities"],
            contradiction_hit=checks["contradictions"],
            dependency_hit=checks["dependencies"],
            rubric_hit=checks["rubric"],
            confidence_valid=checks["confidence"],
            assertions=tally.total,
            grounded=tally.grounded,
            ungrounded=tally.ungrounded,
            details=details,
            offenders=tally.offenders,
        ),
        mutations,
    )


async def run_evaluation(
    fixtures: list[GoldenFixture] | None = None,
) -> EvaluationReport:
    dataset = fixtures if fixtures is not None else golden_fixtures()
    results: list[FixtureResult] = []
    mutations: list[MutationResult] = []
    for fixture in dataset:
        result, fixture_mutations = await _evaluate_fixture(fixture)
        results.append(result)
        mutations.extend(fixture_mutations)
    return EvaluationReport(results=results, mutations=mutations)
