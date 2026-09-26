"""End-to-end analysis behaviour through the HTTP contract.

Builds a real specification, runs the analyzer with the deterministic mock
provider, and asserts persistence, idempotency, staleness, review, authorization
and failure handling. No external model or key is involved.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import register_user

PROGRAMMING_DESCRIPTION = (
    "Implement Dijkstra and Bellman-Ford in Python. The project must include unit tests, "
    "a build script, and a written report comparing runtime behaviour. Each algorithm must "
    "run within two seconds on the provided graphs and the report must explain the design."
)


async def _create_course(client: AsyncClient, code: str = "ALG301") -> dict:
    response = await client.post("/api/v1/courses", json={"name": "Algorithms", "code": code})
    assert response.status_code == 201, response.text
    return response.json()


async def _create_assignment(
    client: AsyncClient,
    course_id: str,
    *,
    title: str = "Graph Algorithms Project",
    description: str | None = PROGRAMMING_DESCRIPTION,
    with_requirements: bool = True,
    with_rubric: bool = True,
) -> dict:
    response = await client.post(
        "/api/v1/assignments",
        json={
            "course_id": course_id,
            "title": title,
            "description": description,
            "deadline": (datetime.now(UTC) + timedelta(days=21)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    assignment = response.json()
    assignment_id = assignment["id"]
    if with_requirements:
        for payload in (
            {"title": "Implement Dijkstra", "priority": "CRITICAL", "type": "FUNCTIONAL"},
            {"title": "Implement Bellman-Ford", "priority": "HIGH", "type": "FUNCTIONAL"},
            {"title": "Write unit tests", "priority": "HIGH", "type": "TESTING"},
            {"title": "Write a comparison report", "priority": "MEDIUM", "type": "DOCUMENTATION"},
        ):
            created = await client.post(
                f"/api/v1/assignments/{assignment_id}/requirements", json=payload
            )
            assert created.status_code == 201, created.text
    if with_rubric:
        for title, weight in (("Correctness", "50"), ("Tests", "30"), ("Report", "20")):
            created = await client.post(
                f"/api/v1/assignments/{assignment_id}/criteria",
                json={"title": title, "weight": weight},
            )
            assert created.status_code == 201, created.text
        created = await client.post(
            f"/api/v1/assignments/{assignment_id}/deliverables",
            json={"title": "Source code", "type": "SOURCE_CODE"},
        )
        assert created.status_code == 201, created.text
    return assignment


async def _analyze(client: AsyncClient, assignment_id: str, **body: object) -> dict:
    response = await client.post(f"/api/v1/assignments/{assignment_id}/analysis", json=body or {})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def prepared(client: AsyncClient) -> dict:
    await register_user(client, "analyst@example.com")
    course = await _create_course(client)
    return await _create_assignment(client, course["id"])


async def test_analysis_persists_and_retrieves(client: AsyncClient, prepared: dict) -> None:
    assignment_id = prepared["id"]
    analysis = await _analyze(client, assignment_id)

    assert analysis["summary"]
    assert analysis["status"] == "PENDING"
    assert analysis["provider"] == "mock"
    assert analysis["prompt_version"] == "assignment_analyzer_v1"
    assert analysis["is_stale"] is False
    assert {item["type"] for item in analysis["assignment_types"]} >= {"PROGRAMMING"}
    assert {item["domain"] for item in analysis["academic_domains"]} >= {"COMPUTER_SCIENCE"}

    requirement = analysis["normalized_requirements"][0]
    assert requirement["source"] == "EXPLICIT"
    assert requirement["source_reference"] == "REQ-001"
    assert requirement["category"] in {"CONTENT", "DELIVERABLE", "QUALITY", "EVALUATION"}

    assert analysis["evaluation"]["rubric_available"] is True
    assert {item["analyzer"] for item in analysis["specialized_analysis"]} >= {"programming"}

    # Persisted and retrievable.
    fetched = await client.get(f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == analysis["id"]

    runs = await client.get(f"/api/v1/assignments/{assignment_id}/analysis/runs")
    assert runs.status_code == 200
    items = runs.json()["items"]
    assert items and items[0]["status"] == "SUCCEEDED"
    assert items[0]["input_hash"] and items[0]["output_hash"]


async def test_planning_contract_is_complete_and_structured(
    client: AsyncClient, prepared: dict
) -> None:
    assignment_id = prepared["id"]
    analysis = await _analyze(client, assignment_id)
    response = await client.get(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}/planning-contract"
    )
    assert response.status_code == 200, response.text
    contract = response.json()
    assert contract["is_stale"] is False
    assert contract["requirements"]
    assert contract["deliverables"]
    assert contract["work_areas"]
    assert contract["verification_strategy"]["items"]
    assert contract["constraints"] is not None
    assert contract["assignment_types"] and contract["academic_domains"]


async def test_repeated_requests_are_idempotent(client: AsyncClient, prepared: dict) -> None:
    assignment_id = prepared["id"]
    first = await _analyze(client, assignment_id)
    second = await _analyze(client, assignment_id)
    assert first["id"] == second["id"]

    forced = await _analyze(client, assignment_id, force=True)
    assert forced["id"] != first["id"]


async def test_editing_the_specification_marks_analysis_stale(
    client: AsyncClient, prepared: dict
) -> None:
    assignment_id = prepared["id"]
    analysis = await _analyze(client, assignment_id)

    updated = await client.patch(
        f"/api/v1/assignments/{assignment_id}",
        json={"description": PROGRAMMING_DESCRIPTION + " Also include a benchmark section."},
    )
    assert updated.status_code == 200, updated.text

    stale = await client.get(f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}")
    assert stale.status_code == 200
    assert stale.json()["is_stale"] is True

    contract = await client.get(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}/planning-contract"
    )
    assert contract.json()["is_stale"] is True

    fresh = await _analyze(client, assignment_id)
    assert fresh["id"] != analysis["id"]
    assert fresh["is_stale"] is False


async def test_review_actions_and_corrections_never_touch_authoritative_data(
    client: AsyncClient, prepared: dict
) -> None:
    assignment_id = prepared["id"]
    ready = await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-ready")
    assert ready.status_code == 200, ready.text
    analysis = await _analyze(client, assignment_id)

    accepted = await client.post(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}/accept",
        json={"note": "Looks right."},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    assert accepted.json()["reviewed_at"] is not None

    corrected = await client.patch(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}",
        json={"types": ["PROBLEM_SET"], "domains": ["MATHEMATICS"]},
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert [item["type"] for item in body["assignment_types"]] == ["PROBLEM_SET"]
    assert all(item["source"] == "USER" for item in body["assignment_types"])
    assert [item["domain"] for item in body["academic_domains"]] == ["MATHEMATICS"]

    dismissed = await client.patch(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}",
        json={"edits": {"ambiguities": []}},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["ambiguities"] == []
    assert dismissed.json()["edited"] is True

    rejected = await client.post(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}/reject",
        json={"note": "Not accurate enough."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"

    # The authoritative specification is unchanged by any of this.
    specification = await client.get(f"/api/v1/assignments/{assignment_id}/specification")
    assert specification.status_code == 200
    specification_body = specification.json()
    assert len(specification_body["requirements"]) == 4
    assert specification_body["requirements"][0]["title"] == "Implement Dijkstra"
    assert specification_body["assignment"]["title"] == "Graph Algorithms Project"

    assignment = await client.get(f"/api/v1/assignments/{assignment_id}")
    assert assignment.json()["status"] == "ANALYZED"


async def test_clarification_question_can_be_answered(client: AsyncClient, prepared: dict) -> None:
    assignment_id = prepared["id"]
    analysis = await _analyze(client, assignment_id)
    questions = analysis["clarification_questions"]
    assert questions, "a question should be generated for an assignment without a format constraint"

    question = questions[0]
    answered = await client.post(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}"
        f"/questions/{question['id']}/answer",
        json={"answer": "APA 7th edition."},
    )
    assert answered.status_code == 200, answered.text
    updated = next(
        item for item in answered.json()["clarification_questions"] if item["id"] == question["id"]
    )
    assert updated["status"] == "ANSWERED"
    assert updated["answer"] == "APA 7th edition."

    second = questions[1] if len(questions) > 1 else questions[0]
    dismissed = await client.post(
        f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}"
        f"/questions/{second['id']}/dismiss",
        json={"reason": "Not important."},
    )
    assert dismissed.status_code == 200


async def test_authorization_and_ownership(client: AsyncClient, prepared: dict) -> None:
    assignment_id = prepared["id"]
    analysis = await _analyze(client, assignment_id)

    # A different user cannot see or analyze another user's assignment.
    await register_user(client, "intruder@example.com")
    assert (
        await client.get(f"/api/v1/assignments/{assignment_id}/analysis/{analysis['id']}")
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/assignments/{assignment_id}/analysis", json={})
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/assignments/{assignment_id}/analysis/runs")
    ).status_code == 404


async def test_unauthenticated_requests_are_rejected(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/v1/assignments/{'0' * 8}-0000-0000-0000-000000000000/analysis", json={}
    )
    assert response.status_code == 401


async def test_analysis_of_an_unknown_assignment_is_not_found(
    client: AsyncClient, prepared: dict
) -> None:
    missing = "11111111-1111-1111-1111-111111111111"
    assert (
        await client.post(f"/api/v1/assignments/{missing}/analysis", json={})
    ).status_code == 404
    assert (await client.get(f"/api/v1/assignments/{missing}/analysis/runs")).status_code == 404


async def test_too_little_information_is_rejected(client: AsyncClient) -> None:
    await register_user(client, "sparse@example.com")
    course = await _create_course(client, code="SPA101")
    assignment = await _create_assignment(
        client, course["id"], description=None, with_requirements=False, with_rubric=False
    )
    response = await client.post(f"/api/v1/assignments/{assignment['id']}/analysis", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ANALYSIS_INPUT_INVALID"


async def test_provider_failure_is_recorded_and_reported(
    client: AsyncClient, prepared: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.modules.analysis.router as router_module
    from app.ai.errors import LLMTimeoutError
    from app.ai.provider import LLMProvider, LLMRequest, LLMResponse

    class FailingProvider(LLMProvider):
        name = "failing"
        model = "failing-model"

        async def complete(self, request: LLMRequest) -> LLMResponse:
            raise LLMTimeoutError("boom")

    monkeypatch.setattr(router_module, "build_llm_provider", lambda *_: FailingProvider())

    assignment_id = prepared["id"]
    response = await client.post(f"/api/v1/assignments/{assignment_id}/analysis", json={})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "LLM_TIMEOUT"

    runs = await client.get(f"/api/v1/assignments/{assignment_id}/analysis/runs")
    failed = runs.json()["items"][0]
    assert failed["status"] == "FAILED"
    assert failed["error_code"] == "LLM_TIMEOUT"


async def test_analysis_of_a_different_type_is_supported(client: AsyncClient) -> None:
    await register_user(client, "proof@example.com")
    course = await _create_course(client, code="MAT201")
    assignment = await _create_assignment(
        client,
        course["id"],
        title="Real Analysis Proof Set",
        description=(
            "Prove that a uniformly convergent sequence of continuous functions has a "
            "continuous limit. State each theorem and provide rigorous proofs."
        ),
        with_requirements=False,
        with_rubric=False,
    )
    response = await client.post(
        f"/api/v1/assignments/{assignment['id']}/requirements",
        json={"title": "Prove Theorem 4.2", "priority": "HIGH"},
    )
    assert response.status_code == 201
    analysis = await _analyze(client, assignment["id"])
    assert {item["type"] for item in analysis["assignment_types"]} >= {"MATHEMATICAL_PROOF"}
    assert {item["domain"] for item in analysis["academic_domains"]} >= {"MATHEMATICS"}
    assert {item["analyzer"] for item in analysis["specialized_analysis"]} >= {"mathematics"}
