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
from app.ai.golden import golden_fixtures
from app.ai.parsing import parse_analyzer_output
from app.ai.specialized import SpecializationContext, analyze_specializations

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
    assert summary["requirement_recall"] >= 0.9
    assert summary["deliverable_recall"] >= 0.9
    assert summary["evidence_grounding"] == 1.0
    assert summary["hallucination_rate"] == 0.0


@pytest.mark.asyncio
async def test_evaluation_metrics_have_expected_keys() -> None:
    report = await run_evaluation()
    metrics = report.summary()
    for key in (
        "classification_accuracy",
        "requirement_recall",
        "ambiguity_rate",
        "contradiction_rate",
        "dependency_recall",
        "rubric_recall",
        "evidence_grounding",
        "hallucination_rate",
        "schema_validity",
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
