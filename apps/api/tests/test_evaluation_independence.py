"""The golden evaluation must not grade the heuristic engine with itself.

Two separate concerns live here:

* the evaluation code must not reach into the engine it is scoring, and
* every recorded transcript must actually be usable, so a drift between the
  dataset and the transcripts fails loudly instead of quietly lowering a score.

The mutation suite in :mod:`app.ai.evaluation.metrics` covers detection; this
module covers provenance and completeness.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from app.ai.evaluation import runner as runner_module
from app.ai.evaluation.metrics import discrimination
from app.ai.evaluation.provider import (
    RecordedTranscriptProvider,
    TranscriptNotRecorded,
    recorded_payload,
)
from app.ai.evaluation.runner import allowed_sources
from app.ai.evaluation.transcripts import INFERRED_TRANSCRIPTS, transcript_for
from app.ai.golden import golden_fixtures
from app.ai.parsing import parse_analyzer_output
from app.ai.provider import LLMRequest
from app.ai.validation import validate_analysis

EVALUATION_DIR = Path(runner_module.__file__).parent


def _evaluation_modules() -> list[Path]:
    return sorted(EVALUATION_DIR.glob("*.py"))


def test_evaluation_never_imports_the_heuristic_engine() -> None:
    """No module under evaluation may import or reference ``app.ai.heuristics``.

    This is the assertion that keeps the fix from silently regressing. A string
    search would be enough to catch the import, but parsing the AST means a
    mention inside a docstring or comment cannot mask a real import.
    """
    offenders: list[str] = []
    for path in _evaluation_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("app.ai.heuristics"):
                    offenders.append(f"{path.name}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.ai.heuristics"):
                        offenders.append(f"{path.name}: import {alias.name}")
    assert offenders == []


def test_evaluation_does_not_use_the_mock_provider() -> None:
    """The runner must not route the golden dataset through MockLLMProvider."""
    source = (EVALUATION_DIR / "runner.py").read_text(encoding="utf-8")
    assert "MockLLMProvider" not in source.replace(
        "# Recorded transcripts, not MockLLMProvider.", ""
    )


def test_every_fixture_has_a_recorded_transcript() -> None:
    names = [fixture.name for fixture in golden_fixtures()]
    assert names, "the golden dataset is empty"
    for name in names:
        assert transcript_for(name) is not None, f"no transcript recorded for {name}"


def test_no_transcript_is_recorded_for_an_unknown_fixture() -> None:
    assert transcript_for("not_a_real_fixture") is None


def test_provider_raises_instead_of_falling_back() -> None:
    """A missing transcript is an error, never a silent heuristic fallback.

    Falling back would restore the circularity this provider exists to remove,
    and it would do so invisibly: the gate would still report a clean run.
    """
    provider = RecordedTranscriptProvider()
    request = LLMRequest(
        messages=[{"role": "user", "content": "analyse this"}],
        response_schema={"type": "object"},
        prompt_version="test",
        metadata={"fixture_name": "not_a_real_fixture"},
    )
    with pytest.raises(TranscriptNotRecorded):
        import asyncio

        asyncio.run(provider.complete(request))


def test_provider_replays_the_recorded_transcript_verbatim() -> None:
    """The bytes the provider returns must be the recorded transcript.

    Without this the provider could quietly transform the answer, which would
    reintroduce a dependency on whatever did the transforming.
    """
    name = golden_fixtures()[0].name
    provider = RecordedTranscriptProvider()
    request = LLMRequest(
        messages=[{"role": "user", "content": "analyse this"}],
        response_schema={"type": "object"},
        prompt_version="test",
        metadata={"fixture_name": name, "analyzer_input": {"brief": "x"}},
    )
    import asyncio

    response = asyncio.run(provider.complete(request))
    assert json.loads(response.content) == recorded_payload(name)
    assert response.provider == "recorded"
    assert response.usage.total_tokens > 0


def test_every_recorded_transcript_parses_and_validates() -> None:
    """Completeness: each transcript must survive parsing and semantic checks.

    A transcript that fails here would be silently excluded from the gate, so
    this is asserted directly rather than inferred from the score.
    """
    for fixture in golden_fixtures():
        payload = recorded_payload(fixture.name)
        output = parse_analyzer_output(json.dumps(payload, ensure_ascii=False))
        validate_analysis(output, runner_module._context(fixture.payload, "golden"))


def test_every_recorded_transcript_is_grounded() -> None:
    """No transcript may ship an ungrounded assertion.

    The gate requires zero hallucinations, so a transcript that quietly contains
    one would be a recorded defect rather than a recorded defect the evaluation
    is meant to notice.
    """
    from app.ai.evaluation.metrics import tally_grounding

    for fixture in golden_fixtures():
        output = parse_analyzer_output(
            json.dumps(recorded_payload(fixture.name), ensure_ascii=False)
        )
        context = runner_module._context(fixture.payload, "golden")
        tally = tally_grounding(output, allowed_sources(context))
        assert tally.ungrounded == 0, f"{fixture.name}: {tally.offenders}"


def test_inferred_transcripts_mark_inference_honestly() -> None:
    """A transcript that adds something must label it as an inference.

    These are the fixtures where the writer went beyond the brief. Presenting
    that as an explicit requirement is the hallucination the honesty check
    exists to catch, so the label is what the test pins down.
    """
    for name in INFERRED_TRANSCRIPTS:
        payload = recorded_payload(name)
        marks = [
            item.get("source") or item.get("uncertainty")
            for item in payload["normalized_requirements"] + payload["deliverables"]
        ]
        assert "AI_INFERENCE" in marks, f"{name} adds content without marking it inferred"


def test_every_fixture_still_has_detectable_defects() -> None:
    """Discrimination must hold for each fixture, not just on average.

    Averaging hides a fixture whose transcript is too small to mutate
    meaningfully, so this asserts per fixture.
    """
    for fixture in golden_fixtures():
        output = parse_analyzer_output(
            json.dumps(recorded_payload(fixture.name), ensure_ascii=False)
        )
        context = runner_module._context(fixture.payload, "golden")
        results = discrimination(output, allowed_sources(context))
        blind = [result.name for result in results if not result.caught]
        assert blind == [], f"{fixture.name}: evaluation is blind to {blind}"
