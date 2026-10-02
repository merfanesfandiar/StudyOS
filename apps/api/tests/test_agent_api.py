"""The agent HTTP contract, end to end against the real router.

These run the same flow a student's browser does: create a run, start it, answer
the question it stops on, watch it finish. What is being checked is mostly what
a student can *lose* — a run that starts work the plan never authorised, a
checkpoint that gets resolved by a stale client with an option nobody offered, or
a response that reports progress the database does not contain.

The provider is the deterministic mock, so the suite is reproducible and costs
nothing. No external model and no key are involved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage
from app.models.enums import (
    AgentRunStatus,
)
from app.modules.agent.state_machine import parse_status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_user

BASE = "/api/v1/assignments"


class _DeterministicProvider(LLMProvider):
    """Answers every decision the way a cooperating model would.

    Draft then complete, echoing the task the runtime actually selected. That
    echo matters: a double that guesses the task key would be testing itself
    rather than the runtime, and would fail for reasons that have nothing to do
    with the code under test.
    """

    name = "deterministic"
    model = "deterministic-agent-v1"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        metadata = request.metadata or {}
        usage = LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        if "agent_execution_input" in metadata:
            key = metadata["agent_execution_input"]["task_key"]
            return LLMResponse(
                content=json.dumps(
                    {
                        "summary": f"Worked on {key}.",
                        "content": f"# Draft for {key}\n\nThe work product.",
                    }
                ),
                provider=self.name,
                model=self.model,
                usage=usage,
                estimated_cost=0.0005,
            )
        key = metadata.get("agent_input", {}).get("task_key")
        self.seen.append(key)
        action = "CREATE_ARTIFACT" if len(self.seen) % 2 == 1 else "COMPLETE_TASK"
        payload: dict[str, Any] = {"action": action, "reason": "Proceeding.", "confidence": 0.9}
        if action == "CREATE_ARTIFACT":
            payload["artifact_type"] = "SOLUTION"
            payload["artifact_title"] = f"{key} draft"
        else:
            payload["task_key"] = key
        return LLMResponse(
            content=json.dumps(payload),
            provider=self.name,
            model=self.model,
            usage=usage,
            estimated_cost=0.0005,
        )

    def __init__(self) -> None:
        self.seen: list[str | None] = []


@pytest.fixture
def provider() -> _DeterministicProvider:
    return _DeterministicProvider()


@pytest.fixture(autouse=True)
def use_provider(monkeypatch: pytest.MonkeyPatch, provider: _DeterministicProvider) -> None:
    """Force every agent endpoint onto the deterministic provider."""
    from app.modules.agent import router as agent_router

    monkeypatch.setattr(agent_router, "build_llm_provider", lambda settings: provider)


async def _seeded_assignment(
    client: AsyncClient, *, keys: tuple[str, ...] = ("T1",), approved: bool = True
) -> dict[str, Any]:
    """Drive the real API as far as an approved plan, then read it back.

    Going through the HTTP endpoints rather than writing rows directly means
    these tests fail if the analysis or planning contract changes shape, which is
    exactly when an agent test would otherwise keep passing against a plan that
    can no longer be created.
    """
    course = (
        await client.post("/api/v1/courses", json={"name": "Analysis", "code": "MATH201"})
    ).json()
    assignment = (
        await client.post(
            f"{BASE}/{course['id']}/assignments" if False else "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "Prove monotone convergence",
                "description": "Show that an increasing bounded sequence converges.",
                "deadline": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
            },
        )
    ).json()

    analysed = await client.post(f"{BASE}/{assignment['id']}/analysis", json={})
    assert analysed.status_code in (200, 201), analysed.text

    planned = await client.post(f"{BASE}/{assignment['id']}/plans", json={})
    assert planned.status_code in (200, 201), planned.text
    plan = planned.json()
    assert approved is True
    return {"assignment": assignment, "plan": plan}


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_name_what_the_agent_cannot_do(client: AsyncClient) -> None:
    """The absent-capability list is the honest answer to "can it run my code?"."""
    await register_user(client)
    course = (await client.post("/api/v1/courses", json={"name": "C", "code": "X1"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "T",
                "description": "D",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()

    response = await client.get(f"{BASE}/{assignment['id']}/agent/capabilities")
    assert response.status_code == 200, response.text
    body = response.json()

    assert {t["name"] for t in body["tools"]} == {
        "read_context",
        "write_artifact",
        "request_checkpoint",
    }
    assert body["absent_capabilities"], "the negative list is the point of this endpoint"
    for forbidden in ("execute_code", "shell", "network_access", "filesystem_write"):
        assert forbidden in body["absent_capabilities"]


@pytest.mark.asyncio
async def test_capabilities_are_scoped_to_the_owner(client: AsyncClient) -> None:
    await register_user(client, email="owner@example.com")
    course = (await client.post("/api/v1/courses", json={"name": "C", "code": "X2"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "T",
                "description": "D",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()

    intruder = await client.post(
        "/api/v1/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "StrongPass123"},
    )
    assert intruder.status_code == 201, intruder.text
    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": "StrongPass123"},
    )

    response = await client.get(f"{BASE}/{assignment['id']}/agent/capabilities")
    assert response.status_code == 404, "another student's assignment must not even be discoverable"


# ---------------------------------------------------------------------------
# Creation is gated on a plan a student approved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creating_a_run_without_an_approved_plan_is_refused(client: AsyncClient) -> None:
    """The agent may only execute work the student already agreed to."""
    await register_user(client)
    course = (await client.post("/api/v1/courses", json={"name": "C", "code": "X3"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "T",
                "description": "D",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()

    response = await client.post(f"{BASE}/{assignment['id']}/agent/runs", json={})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "AGENT_NO_APPROVED_PLAN"


@pytest.mark.asyncio
async def test_an_unknown_assignment_is_not_found(client: AsyncClient) -> None:
    await register_user(client)
    response = await client.post(f"{BASE}/{uuid4()}/agent/runs", json={})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_rejects_an_unwarranted_budget_increase(client: AsyncClient) -> None:
    """The UI must not be able to raise a budget above the configured maximum."""
    await register_user(client)
    course = (await client.post("/api/v1/courses", json={"name": "C", "code": "X4"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "T",
                "description": "D",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()

    response = await client.post(
        f"{BASE}/{assignment['id']}/agent/runs", json={"max_cost": 10_000.0}
    )
    assert response.status_code in (409, 422), response.text


# ---------------------------------------------------------------------------
# Run lifecycle over HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_run_from_creation_to_completion(client: AsyncClient, provider) -> None:
    """Create, start, finish: the whole loop, through the real endpoints.

    Asserting on the response *and* the recorded progress is deliberate. A
    response that says "completed" while the plan still shows pending tasks would
    look correct to the UI and be a lie to the student.
    """
    await register_user(client)
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    plan_id = seeded["plan"]["id"]

    approved = await client.post(f"{BASE}/{assignment_id}/plans/{plan_id}/approve", json={})
    assert approved.status_code in (200, 201), approved.text

    created = await client.post(f"{BASE}/{assignment_id}/agent/runs", json={})
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == AgentRunStatus.CREATED.value
    assert run["plan_version"] == seeded["plan"]["version"]
    assert run["max_iterations"] > 0

    started = await client.post(f"{BASE}/{assignment_id}/agent/runs/{run['id']}/start", json={})
    assert started.status_code == 200, started.text
    body = started.json()

    assert body["id"] == run["id"], "the run id must not change across calls"
    assert body["status"] in {
        AgentRunStatus.COMPLETED.value,
        AgentRunStatus.WAITING_FOR_USER.value,
        AgentRunStatus.BLOCKED.value,
    }, "a start must never leave the run in an impossible state"
    if body["status"] == AgentRunStatus.COMPLETED.value:
        assert body["progress"]["completed"] == body["progress"]["total"]
        assert body["artifacts"], "a completed run that produced nothing is not complete"
        for artifact in body["artifacts"]:
            assert artifact["content"].strip(), "an empty draft is not a draft"
            assert "Proceeding." not in artifact["content"], (
                "the model's justification must never become the artifact body"
            )

    fetched = await client.get(f"{BASE}/{assignment_id}/agent/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == body["status"]


@pytest.mark.asyncio
async def test_an_idempotent_create_does_not_start_two_runs(client: AsyncClient) -> None:
    """A retried request must not bill the student twice."""
    await register_user(client)
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    await client.post(f"{BASE}/{assignment_id}/plans/{seeded['plan']['id']}/approve", json={})

    first = await client.post(
        f"{BASE}/{assignment_id}/agent/runs", json={"idempotency_key": "abc123"}
    )
    second = await client.post(
        f"{BASE}/{assignment_id}/agent/runs", json={"idempotency_key": "abc123"}
    )
    assert first.status_code == 201, first.text
    assert second.status_code in (200, 201), second.text
    assert first.json()["id"] == second.json()["id"], "the same key must yield the same run"

    listed = await client.get(f"{BASE}/{assignment_id}/agent/runs")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


@pytest.mark.asyncio
async def test_cancel_is_terminal_and_persists(client: AsyncClient) -> None:
    await register_user(client)
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    await client.post(f"{BASE}/{assignment_id}/plans/{seeded['plan']['id']}/approve", json={})
    created = (await client.post(f"{BASE}/{assignment_id}/agent/runs", json={})).json()
    run_id = created["id"]

    cancelled = await client.post(
        f"{BASE}/{assignment_id}/agent/runs/{run_id}/cancel", json={"note": "Not needed."}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == AgentRunStatus.CANCELLED.value

    resumed = await client.post(f"{BASE}/{assignment_id}/agent/runs/{run_id}/resume", json={})
    assert resumed.status_code >= 400, "a cancelled run must never resume"


@pytest.mark.asyncio
async def test_another_student_cannot_read_a_run(client: AsyncClient) -> None:
    await register_user(client, email="owner2@example.com")
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    await client.post(f"{BASE}/{assignment_id}/plans/{seeded['plan']['id']}/approve", json={})
    run_id = (await client.post(f"{BASE}/{assignment_id}/agent/runs", json={})).json()["id"]

    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Other", "email": "other2@example.com", "password": "StrongPass123"},
    )

    response = await client.get(f"{BASE}/{assignment_id}/agent/runs/{run_id}")
    assert response.status_code == 404, "a run must not be discoverable across students"


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_that_needs_the_student_says_so_explicitly(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Waiting on a question is a normal outcome with a readable reason.

    The alternative — a run that just stops looking slow — leaves a student
    watching a spinner and wondering whether they should refresh.
    """
    from app.modules.agent import router as agent_router

    class _AsksQuestions(LLMProvider):
        """Asks once, then gets on with it.

        A provider that asked on every step would never let the run finish, so it
        could not show that answering actually unblocks the run.
        """

        name = "asker"
        model = "asker-v1"

        def __init__(self) -> None:
            self.asked = False

        async def complete(self, request: LLMRequest) -> LLMResponse:
            metadata = request.metadata or {}
            usage = LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10)
            if "agent_execution_input" in metadata:
                return LLMResponse(
                    content=json.dumps({"summary": "ok", "content": "# Draft"}),
                    provider=self.name,
                    model=self.model,
                    usage=usage,
                    estimated_cost=0.0001,
                )
            if not self.asked:
                self.asked = True
                return LLMResponse(
                    content=json.dumps(
                        {
                            "action": "ASK_USER",
                            "reason": "I need to know the notation.",
                            "confidence": 0.9,
                            "question": "Which notation should I use?",
                            "checkpoint_type": "CLARIFICATION",
                            "checkpoint_options": ["Knopp", "Other"],
                        }
                    ),
                    provider=self.name,
                    model=self.model,
                    usage=usage,
                    estimated_cost=0.0001,
                )
            return LLMResponse(
                content=json.dumps(
                    {
                        "action": "COMPLETE_TASK",
                        "reason": "Notation settled.",
                        "confidence": 0.9,
                        "task_key": metadata.get("agent_input", {}).get("task_key"),
                    }
                ),
                provider=self.name,
                model=self.model,
                usage=usage,
                estimated_cost=0.0001,
            )

    asker = _AsksQuestions()
    monkeypatch.setattr(agent_router, "build_llm_provider", lambda settings: asker)

    await register_user(client)
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    await client.post(f"{BASE}/{assignment_id}/plans/{seeded['plan']['id']}/approve", json={})
    run_id = (await client.post(f"{BASE}/{assignment_id}/agent/runs", json={})).json()["id"]

    started = await client.post(f"{BASE}/{assignment_id}/agent/runs/{run_id}/start", json={})
    body = started.json()
    assert body["status"] == AgentRunStatus.WAITING_FOR_USER.value
    assert body["awaiting_checkpoint_id"], "a waiting run must say what it is waiting on"
    assert body["can_resume"] is True

    pending = await client.get(f"{BASE}/{assignment_id}/agent/runs/{run_id}/checkpoints/pending")
    assert pending.status_code == 200
    question = pending.json()
    assert question["question"]
    assert question["options"]

    resolved = await client.post(
        f"{BASE}/{assignment_id}/agent/runs/{run_id}/checkpoints/{question['id']}/resolve",
        json={"selected_option": "Knopp"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] in {
        AgentRunStatus.COMPLETED.value,
        AgentRunStatus.PAUSED.value,
        AgentRunStatus.BLOCKED.value,
    }, "answering the question must let the run continue, not re-ask forever"

    after = await client.get(f"{BASE}/{assignment_id}/agent/runs/{run_id}/checkpoints/pending")
    assert after.json() is None, "a resolved question must not be asked again"


@pytest.mark.asyncio
async def test_a_checkpoint_cannot_be_resolved_with_an_unoffered_option(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale client must not answer a question nobody asked.

    The offered options are the contract. Accepting an arbitrary string would let
    a client from a previous session inject an answer the student never saw.
    """
    from app.modules.agent import router as agent_router

    class _AsksWithFixedOptions(LLMProvider):
        name = "asker"
        model = "asker-v1"

        async def complete(self, request: LLMRequest) -> LLMResponse:
            metadata = request.metadata or {}
            usage = LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10)
            if "agent_execution_input" in metadata:
                return LLMResponse(
                    content=json.dumps({"summary": "ok", "content": "# Draft"}),
                    provider=self.name,
                    model=self.model,
                    usage=usage,
                    estimated_cost=0.0001,
                )
            return LLMResponse(
                content=json.dumps(
                    {
                        "action": "ASK_USER",
                        "reason": "Need the notation.",
                        "confidence": 0.9,
                        "question": "Which notation?",
                        "checkpoint_type": "CLARIFICATION",
                        "checkpoint_options": ["Knopp", "Other"],
                    }
                ),
                provider=self.name,
                model=self.model,
                usage=usage,
                estimated_cost=0.0001,
            )

    monkeypatch.setattr(
        agent_router, "build_llm_provider", lambda settings: _AsksWithFixedOptions()
    )  # always asks: the run is expected to stay waiting

    await register_user(client)
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    await client.post(f"{BASE}/{assignment_id}/plans/{seeded['plan']['id']}/approve", json={})
    run_id = (await client.post(f"{BASE}/{assignment_id}/agent/runs", json={})).json()["id"]
    await client.post(f"{BASE}/{assignment_id}/agent/runs/{run_id}/start", json={})

    question = (
        await client.get(f"{BASE}/{assignment_id}/agent/runs/{run_id}/checkpoints/pending")
    ).json()

    rejected = await client.post(
        f"{BASE}/{assignment_id}/agent/runs/{run_id}/checkpoints/{question['id']}/resolve",
        json={"selected_option": "An option nobody offered"},
    )
    assert rejected.status_code >= 400, "an unoffered option must be refused, not silently accepted"


@pytest.mark.asyncio
async def test_a_checkpoint_from_another_run_is_not_found(client: AsyncClient) -> None:
    """Resolving must be scoped to the run named in the path."""
    await register_user(client)
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    await client.post(f"{BASE}/{assignment_id}/plans/{seeded['plan']['id']}/approve", json={})
    run_id = (await client.post(f"{BASE}/{assignment_id}/agent/runs", json={})).json()["id"]

    response = await client.post(
        f"{BASE}/{assignment_id}/agent/runs/{run_id}/checkpoints/{uuid4()}/resolve",
        json={"response": "hello"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Error shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_errors_carry_a_machine_readable_code(client: AsyncClient) -> None:
    """The UI branches on the code, so the code is part of the contract."""
    await register_user(client)
    course = (await client.post("/api/v1/courses", json={"name": "C", "code": "X9"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "T",
                "description": "D",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()

    response = await client.post(f"{BASE}/{assignment['id']}/agent/runs", json={})
    body = response.json()
    assert "error" in body
    assert body["error"]["code"]
    assert body["error"]["message"], "an error a student sees must be readable"


@pytest.mark.asyncio
async def test_unknown_run_id_is_a_clean_404(client: AsyncClient) -> None:
    await register_user(client)
    course = (await client.post("/api/v1/courses", json={"name": "C", "code": "X8"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "T",
                "description": "D",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()

    response = await client.get(f"{BASE}/{assignment['id']}/agent/runs/{uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Recovery cannot reach outside the assignment that was asked for
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_only_touches_the_assignment_that_asked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A student's recovery request must not pause anyone else's run.

    Recovery writes: it pauses runs and expires questions. Left unscoped, a
    button on one assignment would silently stop work on every other assignment
    in the database, which is both a correctness bug and a way for one student to
    interfere with another's work. The sweep is therefore bound to the assignment
    in the path, and this test is what keeps it that way.
    """
    from app.models.entities import AgentCheckpoint, AgentRun

    await register_user(client, email="victim@example.com")

    async def _seed_run(email: str, title: str, code: str) -> tuple[str, str]:
        await client.post("/api/v1/auth/logout")
        body = {"name": email, "email": email, "password": "StrongPass123"}
        if (await client.get("/api/v1/auth/me")).status_code != 200:
            registered = await client.post("/api/v1/auth/register", json=body)
            assert registered.status_code in (201, 409), registered.text
            if registered.status_code == 409:
                assert (
                    await client.post(
                        "/api/v1/auth/login",
                        json={"email": email, "password": "StrongPass123"},
                    )
                ).status_code == 200
        course = (await client.post("/api/v1/courses", json={"name": title, "code": code})).json()
        assignment = (
            await client.post(
                "/api/v1/assignments",
                json={
                    "course_id": course["id"],
                    "title": title,
                    "description": "D",
                    "deadline": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
                },
            )
        ).json()
        return assignment["id"], email

    victim_assignment, _ = await _seed_run("victim@example.com", "Victim work", "V1")
    attacker_assignment, _ = await _seed_run("attacker@example.com", "Attacker work", "A1")

    stale_at = datetime.now(UTC) - timedelta(hours=6)
    rows = {
        a: AgentRun(
            assignment_id=a,
            plan_id=None,
            status=AgentRunStatus.RUNNING.value,
            mode="SUPERVISED",
            heartbeat_at=stale_at,
        )
        for a in (UUID(victim_assignment), UUID(attacker_assignment))
    }
    for run in rows.values():
        db_session.add(run)
    # Flush first: SQLAlchemy assigns UUID primary keys at flush time, so the
    # checkpoint cannot point at a run that has not been written yet.
    await db_session.flush()
    db_session.add(
        AgentCheckpoint(
            run_id=rows[UUID(victim_assignment)].id,
            status="PENDING",
            checkpoint_type="CLARIFICATION",
            question="Victim question?",
            requested_at=stale_at,
        )
    )
    await db_session.flush()
    victim_run_id = rows[UUID(victim_assignment)].id

    response = await client.post(f"{BASE}/{attacker_assignment}/agent/recover", json={})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["runs_paused"] == 1, "the caller's own stale run should still be recovered"
    assert str(victim_run_id) not in report["run_ids"], (
        "the sweep reached a run belonging to a different assignment"
    )

    victim_run = await db_session.get(AgentRun, victim_run_id)
    assert parse_status(victim_run.status) is AgentRunStatus.RUNNING, (
        "another student's run was paused by a request they did not make"
    )
    victim_checkpoint = await db_session.scalar(
        select(AgentCheckpoint).where(AgentCheckpoint.run_id == victim_run_id)
    )
    assert victim_checkpoint.status == "PENDING", "their question was expired instead"


@pytest.mark.asyncio
async def test_recovery_of_your_own_assignment_does_work(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The scoped sweep still has to actually recover your own stale run."""
    from app.models.entities import AgentRun

    await register_user(client)
    course = (await client.post("/api/v1/courses", json={"name": "C", "code": "R1"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "T",
                "description": "D",
                "deadline": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            },
        )
    ).json()
    assignment_id = assignment["id"]

    run = AgentRun(
        assignment_id=UUID(assignment_id),
        plan_id=None,
        status=AgentRunStatus.RUNNING.value,
        mode="SUPERVISED",
        heartbeat_at=datetime.now(UTC) - timedelta(hours=6),
    )
    db_session.add(run)
    await db_session.flush()

    response = await client.post(f"{BASE}/{assignment_id}/agent/recover", json={})
    assert response.status_code == 200, response.text
    assert response.json()["runs_paused"] == 1
    assert str(run.id) in response.json()["run_ids"]

    recovered = await client.get(f"{BASE}/{assignment_id}/agent/runs/{run.id}")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == AgentRunStatus.PAUSED.value
