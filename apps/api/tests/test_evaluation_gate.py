"""The evaluation gate itself.

A CI step that always passes is worse than no gate, because it is trusted. These
tests break the analyzer in ways a real change could break it and assert the gate
notices, so ``python -m app.ai.evaluation.report`` is a meaningful signal.
"""

from __future__ import annotations

import pytest
from app.ai.evaluation import report as report_module
from app.ai.evaluation.metrics import EvaluationReport
from app.ai.evaluation.metrics_types import FixtureResult, MutationResult


def _result(**overrides: object) -> FixtureResult:
    base: dict[str, object] = {
        "name": "fixture",
        "schema_valid": True,
        "classification_hit": True,
        "requirement_coverage": 1.0,
        "deliverable_hit": True,
        "ambiguity_hit": True,
        "contradiction_hit": True,
        "dependency_hit": True,
        "rubric_hit": True,
        "confidence_valid": True,
        "assertions": 8,
        "grounded": 8,
        "ungrounded": 0,
    }
    base.update(overrides)
    return FixtureResult(**base)  # type: ignore[arg-type]


def _patch_report(monkeypatch: pytest.MonkeyPatch, evaluation: EvaluationReport) -> None:
    async def fake_run(fixtures: object = None) -> EvaluationReport:
        return evaluation

    monkeypatch.setattr(report_module, "run_evaluation", fake_run)


@pytest.mark.asyncio
async def test_a_healthy_run_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_report(
        monkeypatch,
        EvaluationReport(
            results=[_result()],
            mutations=[MutationResult(name="planted", caught=True)],
        ),
    )

    summary, problems = await report_module.build_report()

    assert problems == []
    assert summary["mutation_detection_rate"] == 1.0


@pytest.mark.asyncio
async def test_a_regressed_fixture_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    good = _result()
    bad = _result(name="mathematics_proof", classification_hit=False, requirement_coverage=0.5)
    _patch_report(
        monkeypatch,
        EvaluationReport(results=[good, bad], mutations=[MutationResult("m", True)]),
    )

    _, problems = await report_module.build_report()

    assert any("mathematics_proof" in problem for problem in problems)


@pytest.mark.asyncio
async def test_hallucination_above_zero_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_report(
        monkeypatch,
        EvaluationReport(
            results=[_result(ungrounded=2, grounded=6)],
            mutations=[MutationResult("m", True)],
        ),
    )

    _, problems = await report_module.build_report()

    assert any("hallucination_rate" in problem for problem in problems)


@pytest.mark.asyncio
async def test_a_blind_evaluation_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Perfect scores with a blind check must not pass."""
    _patch_report(
        monkeypatch,
        EvaluationReport(
            results=[_result()],
            mutations=[MutationResult("undetected_defect", caught=False)],
        ),
    )

    _, problems = await report_module.build_report()

    assert any("blind" in problem for problem in problems)
    assert any("undetected_defect" in problem for problem in problems)


def test_the_report_flag_never_masks_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    evaluation = EvaluationReport(
        results=[_result(classification_hit=False)],
        mutations=[MutationResult("m", True)],
    )
    _patch_report(monkeypatch, evaluation)

    assert report_module.main(["--report"]) == 0
    assert report_module.main([]) == 1
