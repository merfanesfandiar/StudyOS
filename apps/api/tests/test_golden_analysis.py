"""Golden dataset and AI evaluation framework tests.

These prove the analyzer is structurally correct across heterogeneous academic
assignments and that the evaluation itself is meaningful, without any live model
or network access.
"""

from __future__ import annotations

import json

import pytest
from app.ai import heuristics
from app.ai.evaluation import run_evaluation
from app.ai.evaluation.metrics import coverage_of, tally_grounding
from app.ai.evaluation.runner import _context, allowed_sources
from app.ai.golden import golden_fixtures
from app.ai.parsing import parse_analyzer_output
from app.ai.specialized import SpecializationContext, analyze_specializations
from app.models.enums import SourceKind

REQUIRED_FIXTURES = {
    "mathematics_proof",
    "mathematics_problem_set",
    "programming_assignment",
    "research_paper",
    "essay",
    "lab_report",
    "data_analysis",
    "presentation",
    "reading_assignment",
    "research_and_presentation",
    "programming_and_report",
    "group_project",
}


def test_golden_dataset_covers_every_required_academic_case() -> None:
    names = {fixture.name for fixture in golden_fixtures()}
    assert REQUIRED_FIXTURES.issubset(names)
    assert len(golden_fixtures()) >= 10


def test_golden_dataset_is_heterogeneous() -> None:
    domains = set()
    types = set()
    for fixture in golden_fixtures():
        domains.update(fixture.expected_domains)
        types.update(fixture.expected_types)
    assert len(domains) >= 5
    assert len(types) >= 8


def test_mock_provider_is_deterministic() -> None:
    fixture = next(item for item in golden_fixtures() if item.name == "programming_assignment")
    first = heuristics.analyze(fixture.payload)
    second = heuristics.analyze(fixture.payload)
    assert first == second


@pytest.mark.asyncio
async def test_evaluation_passes_every_fixture() -> None:
    report = await run_evaluation()
    failing = [result.name for result in report.results if not result.passed]
    assert not failing, f"golden fixtures failed: {failing}"
    summary = report.summary()
    assert summary["fixtures"] >= 10
    assert summary["schema_validity"] == 1.0
    assert summary["classification_accuracy"] >= 0.9
    assert summary["requirement_coverage"] >= 0.9
    assert summary["deliverable_recall"] >= 0.9
    assert summary["evidence_grounding"] == 1.0
    assert summary["hallucination_rate"] == 0.0
    assert summary["assertions"] > 0, "grounding must be measured over real assertions"


@pytest.mark.asyncio
async def test_evaluation_metrics_have_expected_keys() -> None:
    report = await run_evaluation()
    metrics = report.summary()
    for key in (
        "classification_accuracy",
        "requirement_coverage",
        "ambiguity_detection",
        "contradiction_detection",
        "dependency_recall",
        "rubric_recall",
        "evidence_grounding",
        "hallucination_rate",
        "schema_validity",
        "assertions",
        "mutation_detection_rate",
    ):
        assert key in metrics


def _context_for(fixture_name: str) -> SpecializationContext:
    fixture = next(item for item in golden_fixtures() if item.name == fixture_name)
    output = parse_analyzer_output(json.dumps(heuristics.analyze(fixture.payload)))
    return SpecializationContext(payload=fixture.payload, analysis=output)


def test_mathematics_specialization_detects_proof_work() -> None:
    specializations = analyze_specializations(_context_for("mathematics_proof"))
    names = {item.analyzer for item in specializations}
    assert "mathematics" in names
    mathematics = next(item for item in specializations if item.analyzer == "mathematics")
    assert mathematics.data["proof_required"] is True
    assert mathematics.data["expected_rigor"] == "HIGH"


def test_programming_specialization_stays_inside_its_namespace() -> None:
    specializations = analyze_specializations(_context_for("programming_assignment"))
    programming = next(item for item in specializations if item.analyzer == "programming")
    assert programming.data["language_requirements"]
    # The universal contract itself is unchanged by specialization.
    context = _context_for("programming_assignment")
    assert all(
        item.type.value not in {"LANGUAGE", "FRAMEWORK"}
        for item in context.analysis.assignment_types
    )


def test_essay_and_lab_specializations_run_for_their_types() -> None:
    essay_names = {item.analyzer for item in analyze_specializations(_context_for("essay"))}
    lab_names = {item.analyzer for item in analyze_specializations(_context_for("lab_report"))}
    data_names = {item.analyzer for item in analyze_specializations(_context_for("data_analysis"))}
    presentation_names = {
        item.analyzer for item in analyze_specializations(_context_for("presentation"))
    }
    research_names = {
        item.analyzer for item in analyze_specializations(_context_for("research_paper"))
    }
    assert "essay" in essay_names
    assert "lab" in lab_names
    assert "data_analysis" in data_names
    assert "presentation" in presentation_names
    assert "research" in research_names


def test_ambiguity_and_contradiction_detection() -> None:
    essay = next(item for item in golden_fixtures() if item.name == "essay")
    result = heuristics.analyze(essay.payload)
    assert result["ambiguities"], "vague essay wording should be flagged"
    assert any(item["key"].startswith("A") for item in result["ambiguities"])

    conflicting = {
        "assignment": {
            "title": "Conflicting sources",
            "description": (
                "Use only sources published before 2020, but also cite sources published "
                "after 2022."
            ),
            "deadline": "2026-12-01T17:00:00Z",
        },
        "requirements": [],
        "constraints": [],
        "criteria": [],
        "deliverables": [],
        "resources": [],
        "document_texts": [],
        "assigned_types": [],
        "assigned_domains": [],
        "user_notes": None,
    }
    result = heuristics.analyze(conflicting)
    assert result["contradictions"]
    assert result["contradictions"][0]["severity"] == "CRITICAL"


# -- the metrics must be able to fail -------------------------------------
# A suite that scores 1.0 on everything is worthless unless it can also reject a
# broken analysis. These tests break the analysis deliberately and assert the
# report notices.


@pytest.mark.asyncio
async def test_every_deliberate_defect_is_detected() -> None:
    report = await run_evaluation()
    blind = [item.name for item in report.mutations if not item.caught]
    assert not blind, f"the evaluation is blind to: {blind}"
    assert report.mutation_detection_rate == 1.0


@pytest.mark.asyncio
async def test_a_hallucinated_requirement_raises_the_hallucination_rate() -> None:
    """The headline metric must respond to invented content, not just count ids."""
    import copy

    fixture = golden_fixtures()[0]
    output = parse_analyzer_output(json.dumps(heuristics.analyze(fixture.payload)))
    pools = allowed_sources(_context(fixture.payload, "golden"))

    clean = tally_grounding(output, pools)
    assert clean.ungrounded == 0

    corrupted = copy.deepcopy(output)
    corrupted.normalized_requirements[0].evidence = []
    corrupted.normalized_requirements[0].source = SourceKind.EXPLICIT.value
    dirty = tally_grounding(corrupted, pools)
    assert dirty.ungrounded == 1
    assert dirty.offenders, "a hallucination must be reported, not merely counted"


@pytest.mark.asyncio
async def test_an_honest_inference_is_not_counted_as_a_hallucination() -> None:
    """The inverse control: flagging admitted uncertainty would make the metric lie."""
    import copy

    fixture = golden_fixtures()[0]
    output = parse_analyzer_output(json.dumps(heuristics.analyze(fixture.payload)))
    pools = allowed_sources(_context(fixture.payload, "golden"))

    hedged = copy.deepcopy(output)
    hedged.normalized_requirements[0].evidence = []
    hedged.normalized_requirements[0].source = SourceKind.AI_INFERENCE.value

    assert tally_grounding(hedged, pools).ungrounded == 0


def test_requirement_coverage_can_be_measured_and_can_fail() -> None:
    """Coverage is a rate against the brief's own wording, not a boolean."""
    required = ["Prove the uniform convergence theorem", "State every theorem used"]

    assert coverage_of(required, required) == 1.0
    # One of two covered is a rate, and it must land on the threshold that a
    # single item out of two clears.
    assert coverage_of(required, ["Prove the uniform convergence theorem"]) == 1.0
    assert coverage_of(required, ["Discuss the weather forecast"]) == 0.0
    assert coverage_of([], []) == 1.0
    # A single shared common word must not count as coverage.
    assert coverage_of(["Implement Dijkstra in Python"], ["Implement Bellman-Ford"]) < 0.99


def test_requirement_coverage_drops_when_an_item_is_dropped() -> None:
    """Losing a requirement has to lower the rate, not round away to 1.0.

    This is the case a fixed threshold can hide: with only two brief items, a
    single hit rounds to the same value as a full match.
    """
    required = [
        "Prove the uniform convergence theorem",
        "State every theorem used in the proof",
        "Include a written solution with every step justified",
    ]
    full = required
    partial = required[:2]

    assert coverage_of(partial, full) == 1.0
    assert coverage_of(full, partial) < 1.0
    # Two of three is a genuinely partial rate, not a pass.
    assert coverage_of(full, full[:2]) < 0.99
    assert coverage_of(full, full[:2]) > 0.0
