"""Classification regression tests.

These pin the signal sources the classifier is allowed to use. The bugs fixed
here were silent: the analyzer still returned a schema-valid answer, it just
answered "OTHER" for a Java programming brief.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.ai import heuristics


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "assignment": {
            "id": "00000000-0000-0000-0000-000000000001",
            "title": "Build a Java Strategy Game",
            "description": (
                "Create a small turn-based strategy game in Java with unit tests, a "
                "documented build, and a written design note explaining the module "
                "boundaries you chose."
            ),
            "deadline": "2026-12-01T17:00:00Z",
            "status": "READY_FOR_ANALYSIS",
            "course_name": "Advanced Programming",
            "course_code": "AP140",
        },
        "requirements": [
            {
                "id": "r1",
                "code": "REQ-001",
                "title": "Implement authentication",
                "description": "Users can register and sign in.",
            }
        ],
        "constraints": [],
        "criteria": [],
        "deliverables": [],
        "resources": [],
        "technologies": [{"name": "Java", "category": "LANGUAGE", "version": "17"}],
    }
    base.update(overrides)
    return base


def types_of(result: dict[str, Any] | Any) -> list[str]:
    data = result if isinstance(result, dict) else result.model_dump()
    return [item["type"] for item in data["assignment_types"]]


def domains_of(result: dict[str, Any] | Any) -> list[str]:
    data = result if isinstance(result, dict) else result.model_dump()
    return [item["domain"] for item in data["academic_domains"]]


def test_keyword_matching_ignores_capitals() -> None:
    """Briefs capitalise proper nouns; matching must be case-insensitive."""
    assert heuristics._count("Written in Java", "java") == 1
    assert heuristics._count("Written in JAVA", "java") == 1
    assert heuristics._count("Written in java", "java") == 1


def test_phrase_matching_tolerates_a_plural() -> None:
    """A brief says "unit tests" where the keyword list says "unit test"."""
    assert heuristics._count("passing unit tests", "unit test") == 1
    assert heuristics._count("one unit test", "unit test") == 1


def test_phrase_matching_respects_word_boundaries() -> None:
    """The plural allowance must not turn "java" into a match for "javascript"."""
    assert heuristics._count("plain javascript only", "java") == 0
    assert heuristics._count("unit tested", "unit test") == 0


def test_course_name_inside_the_assignment_counts_as_evidence() -> None:
    """The course name is nested in the assignment object, not at the top level."""
    haystack = heuristics._haystack(payload())
    assert "advanced programming" in haystack


def test_technologies_and_tags_are_evidence() -> None:
    haystack = heuristics._haystack(payload())
    assert "java" in haystack
    tagged = heuristics._haystack(
        payload(technologies=[], tags=[{"name": "game-dev"}, "sorting-algorithms"])
    )
    assert "game-dev" in tagged
    assert "sorting-algorithms" in tagged


def test_java_game_brief_is_classified_as_programming() -> None:
    result = heuristics.analyze(payload())
    assert "PROGRAMMING" in types_of(result)
    assert "OTHER" not in types_of(result)


def test_one_incidental_keyword_is_not_enough_for_a_type() -> None:
    """A brief with a single weak signal stays OTHER rather than guessing.

    The threshold is deliberate: one incidental match should not decide the
    type of an assignment. "Advanced Programming" is not itself a keyword, so a
    terse brief in a programming course is honestly reported as OTHER.
    """
    terse = payload(
        assignment={
            "title": "Week 3 submission",
            "description": "Submit the written answer for the questions in the sheet.",
            "course_name": "Advanced Programming",
        },
        requirements=[],
        technologies=[],
    )
    assert types_of(heuristics.analyze(terse)) == ["OTHER"]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            "Prove that every convergent series is Cauchy, using the lemma above.",
            "MATHEMATICAL_PROOF",
        ),
        (
            "Write a 3000 word essay with a thesis statement and one paragraph per "
            "source, respecting the word limit.",
            "ESSAY",
        ),
        (
            "Run the experiment with the apparatus, record every measurement, then write "
            "the lab report.",
            "LAB_REPORT",
        ),
        (
            "Prepare a slide deck and give a short oral presentation to the audience.",
            "PRESENTATION",
        ),
    ],
)
def test_unrelated_briefs_keep_their_own_type(description: str, expected: str) -> None:
    """Case-insensitive matching must not make every brief look like programming."""
    result = heuristics.analyze(
        payload(assignment={"title": "Assignment 1", "description": description}, technologies=[])
    )
    assert expected in types_of(result)
