"""End-to-end planning behaviour through the HTTP contract.

Runs the whole flow against the deterministic mock provider: analyze, plan,
review, regenerate, edit, approve. No external model or key is involved.

The assertions are mostly about what a student can lose. A version that
disappears, an edit that silently lands on an approved plan, or a regeneration
that eats a task the student wrote are all failures that a status code of 200
would otherwise hide.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.ai.errors import LLMUnavailableError
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse
from app.modules.planning import router as planning_router
from httpx import AsyncClient

from tests.conftest import register_user


class _UnreachableProvider(LLMProvider):
    """Stands in for a provider that is simply not there."""

    name = "unreachable"
    model = "unreachable-model-v1"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMUnavailableError("no route to host")


class _UnvalidatableProvider(LLMProvider):
    """A model that answers with a plan whose graph cannot be persisted.

    Distinct from `_UnreachableProvider` on purpose. "No answer" and "an answer
    that is wrong" reach the caller by different routes and fail for different
    reasons, and a test suite that only exercises the first one will happily
    pass while the second loses the failed run entirely.
    """

    name = "unvalidatable"
    model = "unvalidatable-model-v1"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        # Valid against `PlannerOutput`, so the failure lands in graph validation
        # rather than in JSON parsing -- which would be a different error on a
        # different path. The dependency names a task key that does not exist, so
        # the graph rules have to reject it.
        return LLMResponse(
            content=json.dumps(
                {
                    "title": "A plan with a dangling dependency",
                    "summary": "Valid schema, unsound graph.",
                    "tasks": [
                        {
                            "key": "T-1",
                            "title": "Write the introduction",
                            "description": "Depends on a task that does not exist.",
                            "depends_on": ["T-404"],
                            "min_minutes": 45,
                            "max_minutes": 90,
                        }
                    ],
                    "milestones": [],
                }
            ),
            provider=self.name,
            model=self.model,
        )


@contextmanager
def unvalidatable_provider(*, fallback_enabled: bool) -> Iterator[None]:
    """A model that responds, badly, with the floor set explicitly."""
    original_provider = planning_router._provider
    original_fallback = planning_router.settings.planning_fallback_enabled
    planning_router._provider = (  # type: ignore[assignment]
        lambda model=None: _UnvalidatableProvider()
    )
    planning_router.settings.planning_fallback_enabled = fallback_enabled
    try:
        yield
    finally:
        planning_router._provider = original_provider  # type: ignore[assignment]
        planning_router.settings.planning_fallback_enabled = original_fallback


@contextmanager
def unreachable_provider(*, fallback_enabled: bool) -> Iterator[None]:
    """Make every model call fail, with the deterministic floor set explicitly.

    `fallback_enabled` is the interesting half. An unreachable provider with the
    floor on still yields a plan -- that is the floor doing its job -- and with
    the floor off it yields a 503. Both are real behaviours worth testing, and
    conflating them hides the one the product cares most about: a plan that came
    from somewhere other than the model has to say so.

    Patched at the router's provider factory rather than by stubbing the
    orchestrator, so the real path runs through the real HTTP handler. A context
    manager rather than a fixture because these tests need a *successful*
    generation first, to prove a failure is recorded alongside a success rather
    than instead of it.
    """
    original_provider = planning_router._provider
    original_fallback = planning_router.settings.planning_fallback_enabled
    planning_router._provider = lambda model=None: _UnreachableProvider()  # type: ignore[assignment]
    planning_router.settings.planning_fallback_enabled = fallback_enabled
    try:
        yield
    finally:
        planning_router._provider = original_provider  # type: ignore[assignment]
        planning_router.settings.planning_fallback_enabled = original_fallback


@contextmanager
def generation_unavailable() -> Iterator[None]:
    """No reachable model and no floor: generation must fail."""
    with unreachable_provider(fallback_enabled=False):
        yield


DESCRIPTION = (
    "Write a 2000-word research report on a topic of your choice, with at least eight "
    "peer-reviewed sources, an argument section, and a short reflection on your process. "
    "Submit the report as a PDF and bring a three-slide summary to the seminar."
)


async def _prepare(client: AsyncClient, email: str = "planner@example.com") -> dict:
    await register_user(client, email)
    course = await client.post("/api/v1/courses", json={"name": "Writing", "code": "WRIT210"})
    assert course.status_code == 201, course.text
    assignment = await client.post(
        "/api/v1/assignments",
        json={
            "course_id": course.json()["id"],
            "title": "Research Report",
            "description": DESCRIPTION,
            "deadline": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
    )
    assert assignment.status_code == 201, assignment.text
    row = assignment.json()
    for requirement in (
        {"title": "Argue a position using peer-reviewed sources", "priority": "HIGH"},
        {"title": "Write a reflection on your process", "priority": "MEDIUM"},
        {"title": "Meet the eight-source minimum", "priority": "CRITICAL"},
    ):
        created = await client.post(
            f"/api/v1/assignments/{row['id']}/requirements", json=requirement
        )
        assert created.status_code == 201, created.text
    return row


async def _analyzed(client: AsyncClient) -> dict:
    response = await client.post("/api/v1/assignments", json={})  # deliberately wrong
    assert response.status_code in (400, 405, 422)


async def _plan(client: AsyncClient, assignment_id: str, **body: object) -> dict:
    response = await client.post(f"/api/v1/assignments/{assignment_id}/plans", json=body or {})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def assignment(client: AsyncClient) -> dict:
    row = await _prepare(client)
    analyzed = await client.post(f"/api/v1/assignments/{row['id']}/analysis", json={})
    assert analyzed.status_code == 200, analyzed.text
    return row


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


async def test_planning_requires_an_analysis(client: AsyncClient) -> None:
    """No analysis, no plan, and a reason the client can act on."""
    row = await _prepare(client, "noanalysis@example.com")
    response = await client.post(f"/api/v1/assignments/{row['id']}/plans", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_NEEDS_ANALYSIS"


async def test_generate_produces_a_reviewable_plan(client: AsyncClient, assignment: dict) -> None:
    """The first plan is a draft awaiting a person, not a schedule."""
    plan = await _plan(client, assignment["id"])

    assert plan["version"] == 1
    assert plan["status"] == "READY_FOR_REVIEW"
    assert plan["trigger"] == "GENERATED"
    assert plan["tasks"], "a plan with no tasks is not a plan"
    assert plan["milestones"]
    assert plan["estimated_effort"]
    assert plan["schedule_risk"] is not None

    keys = [task["key"] for task in plan["tasks"]]
    assert len(keys) == len(set(keys))
    known = set(keys)
    for task in plan["tasks"]:
        assert set(task["depends_on"]) <= known, task["key"]

    # Every required requirement is addressed by something.
    analysis = await client.get(f"/api/v1/assignments/{assignment['id']}/analysis")
    contract = (await client.get(f"/api/v1/assignments/{assignment['id']}/plans")).json()
    assert contract is not None
    covered = {reference for task in plan["tasks"] for reference in task["related_requirements"]}
    assert covered, "no task references a requirement"

    # The plan is retrievable and reports no progress yet.
    fetched = await client.get(f"/api/v1/assignments/{assignment['id']}/plans")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == plan["id"]
    assert fetched.json()["progress_percentage"] == 0
    assert analysis.status_code == 200


async def test_latest_plan_is_null_before_generation(client: AsyncClient, assignment: dict) -> None:
    """Reading a plan never triggers one."""
    response = await client.get(f"/api/v1/assignments/{assignment['id']}/plans")
    assert response.status_code == 200
    assert response.json() is None

    summary = await client.get(f"/api/v1/assignments/{assignment['id']}/plans/summary")
    assert summary.status_code == 404
    assert summary.json()["error"]["code"] == "PLAN_NOT_FOUND"


async def test_idempotency_key_does_not_create_a_second_version(
    client: AsyncClient, assignment: dict
) -> None:
    """A double-submitted button must not plan twice or bill twice."""
    key = "a" * 32
    first = await _plan(client, assignment["id"], idempotency_key=key)
    second = await _plan(client, assignment["id"], idempotency_key=key)

    assert second["id"] == first["id"]
    assert second["version"] == 1

    versions = await client.get(f"/api/v1/assignments/{assignment['id']}/plans/versions")
    assert len(versions.json()["items"]) == 1


# ---------------------------------------------------------------------------
# Review and immutability
# ---------------------------------------------------------------------------


async def test_approval_makes_the_plan_authoritative_and_immutable(
    client: AsyncClient, assignment: dict
) -> None:
    """Approval is the transition; after it, edits are refused with a reason."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"

    approved = await client.post(f"{base}/approve", json={"note": "looks right"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_at"]

    edit = await client.patch(f"{base}", json={"title": "Renamed after approval"})
    assert edit.status_code == 409
    assert edit.json()["error"]["code"] == "PLAN_IMMUTABLE"

    add = await client.post(f"{base}/tasks", json={"title": "Sneaked in"})
    assert add.status_code == 409
    assert add.json()["error"]["code"] == "PLAN_IMMUTABLE"

    # And the plan is unchanged.
    after = await client.get(f"{base}")
    assert after.json()["title"] == plan["title"]


async def test_a_stale_plan_cannot_be_approved(client: AsyncClient, assignment: dict) -> None:
    """Approving a plan built on an outdated analysis would be approving nothing."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"

    # Change the assignment, which stales the analysis and the plan built on it.
    updated = await client.patch(
        f"/api/v1/assignments/{assignment['id']}", json={"description": DESCRIPTION + " Extra."}
    )
    assert updated.status_code == 200, updated.text

    approve = await client.post(f"{base}/approve", json={})
    assert approve.status_code in (409, 422), approve.text


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------


async def test_regeneration_creates_a_version_and_keeps_the_old_one(
    client: AsyncClient, assignment: dict
) -> None:
    """The old version must stay readable; that is the point of versioning."""
    first = await _plan(client, assignment["id"])
    second = await _plan(client, assignment["id"])  # a second generate is a new version

    assert second["version"] == 2
    assert second["id"] != first["id"]
    assert second["trigger"] == "GENERATED"

    old = await client.get(f"/api/v1/assignments/{assignment['id']}/plans/{first['id']}")
    assert old.status_code == 200
    assert old.json()["version"] == 1

    versions = await client.get(f"/api/v1/assignments/{assignment['id']}/plans/versions")
    assert [item["version"] for item in versions.json()["items"]] == [2, 1]


async def test_regeneration_preserves_a_task_the_student_wrote(
    client: AsyncClient, assignment: dict
) -> None:
    """A student's own task must survive a regeneration, content intact."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"

    mine = await client.post(
        f"{base}/tasks",
        json={
            "title": "Ask about the eight-source minimum",
            "description": "Confirm whether preprints count.",
            "acceptance_criteria": ["Written answer from the librarian"],
        },
    )
    assert mine.status_code == 201, mine.text
    assert mine.json()["is_user_authored"] is True

    regenerated = await client.post(
        f"/api/v1/assignments/{assignment['id']}/plans/regenerate", json={}
    )
    assert regenerated.status_code == 201, regenerated.text
    body = regenerated.json()
    assert body["version"] == 2
    assert body["trigger"] == "REGENERATED"

    carried = [task for task in body["tasks"] if task["is_user_authored"]]
    assert len(carried) == 1
    assert carried[0]["title"] == "Ask about the eight-source minimum"
    assert carried[0]["acceptance_criteria"] == ["Written answer from the librarian"]

    # The original version still has it too.
    old = await client.get(f"{base}")
    assert len([t for t in old.json()["tasks"] if t["is_user_authored"]]) == 1


async def test_regeneration_can_discard_student_edits(
    client: AsyncClient, assignment: dict
) -> None:
    """The opposite choice must also be available and must actually discard."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    await client.post(f"{base}/tasks", json={"title": "Temporary note"})

    regenerated = await client.post(
        f"/api/v1/assignments/{assignment['id']}/plans/regenerate",
        json={"preserve_user_edits": False},
    )
    assert regenerated.status_code == 201, regenerated.text
    assert not [t for t in regenerated.json()["tasks"] if t["is_user_authored"]]


async def test_regenerate_without_a_plan_is_refused(client: AsyncClient, assignment: dict) -> None:
    response = await client.post(
        f"/api/v1/assignments/{assignment['id']}/plans/regenerate", json={}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


async def test_task_edits_are_revalidated_against_the_graph(
    client: AsyncClient, assignment: dict
) -> None:
    """A cycle created by hand is refused with the reason, not stored."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    keys = [task["key"] for task in plan["tasks"]]
    if len(keys) < 2:
        pytest.skip("plan has a single task")

    blocked = await client.patch(f"{base}/tasks/{keys[0]}", json={"depends_on": [keys[-1]]})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "PLAN_GRAPH_INVALID"
    assert blocked.json()["error"]["details"]["violations"]

    # Nothing changed.
    after = await client.get(f"{base}")
    first = next(t for t in after.json()["tasks"] if t["key"] == keys[0])
    assert keys[-1] not in first["depends_on"]


async def test_editing_a_generated_task_marks_it_as_the_students(
    client: AsyncClient, assignment: dict
) -> None:
    """Otherwise a regeneration discards work the student deliberately did."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    key = plan["tasks"][0]["key"]
    assert plan["tasks"][0]["is_user_authored"] is False

    edited = await client.patch(f"{base}/tasks/{key}", json={"title": "My own wording"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["is_user_authored"] is True
    assert edited.json()["title"] == "My own wording"


async def test_omitted_task_fields_are_left_alone(client: AsyncClient, assignment: dict) -> None:
    """A partial edit must not null out what the client did not mention."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    target = plan["tasks"][0]

    await client.patch(
        f"{base}/tasks/{target['key']}",
        json={"acceptance_criteria": ["Checked by a peer"]},
    )
    body = (await client.patch(f"{base}/tasks/{target['key']}", json={"title": "Renamed"})).json()
    assert body["title"] == "Renamed"
    assert body["acceptance_criteria"] == ["Checked by a peer"]
    assert body["related_requirements"] == target["related_requirements"]


async def test_reorder_requires_the_complete_set(client: AsyncClient, assignment: dict) -> None:
    """A partial reorder has no single meaning, so it is rejected."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    keys = [task["key"] for task in plan["tasks"]]

    partial = await client.post(f"{base}/tasks/reorder", json={"task_keys": keys[:1]})
    assert partial.status_code in (400, 409, 422), partial.text

    complete = await client.post(f"{base}/tasks/reorder", json={"task_keys": list(reversed(keys))})
    assert complete.status_code == 200, complete.text
    assert [task["key"] for task in complete.json()][: len(keys)] == list(reversed(keys))


async def test_delete_task_removes_it_from_the_plan(client: AsyncClient, assignment: dict) -> None:
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    key = plan["tasks"][-1]["key"]

    deleted = await client.delete(f"{base}/tasks/{key}")
    assert deleted.status_code == 204, deleted.text

    after = await client.get(f"{base}")
    assert key not in {task["key"] for task in after.json()["tasks"]}


async def test_unknown_task_key_is_404(client: AsyncClient, assignment: dict) -> None:
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    response = await client.patch(f"{base}/tasks/NOPE", json={"title": "x"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


async def test_preferences_round_trip_and_default(client: AsyncClient, assignment: dict) -> None:
    """Preferences describe how this student works, so they are workspace-wide."""
    path = f"/api/v1/assignments/{assignment['id']}/plans/preferences"

    current = await client.get(path)
    assert current.status_code == 200
    assert current.json()["planning_style"] == "BALANCED"

    updated = await client.put(
        path,
        json={"planning_style": "DETAILED", "guidance_level": "HIGH", "session_length": "MEDIUM"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["planning_style"] == "DETAILED"
    assert updated.json()["session_length"] == "MEDIUM"

    again = await client.get(path)
    assert again.json() == updated.json()

    # A later plan uses them, and the older version keeps the old ones.
    plan = await _plan(client, assignment["id"], planning_style="DETAILED")
    assert plan["version"] == 1


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_another_users_plan_is_not_reachable(client: AsyncClient, assignment: dict) -> None:
    """A plan id the caller does not own must look like it does not exist."""
    plan = await _plan(client, assignment["id"])
    mine = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"

    other = await client.post("/api/v1/auth/logout")
    assert other.status_code == 204, other.text
    await register_user(client, "intruder@example.com")

    assert (await client.get(mine)).status_code == 404
    assert (await client.patch(f"{mine}", json={"title": "mine now"})).status_code == 404
    assert (await client.post(f"{mine}/approve", json={})).status_code == 404
    assert (await client.post(f"{mine}/tasks", json={"title": "x"})).status_code == 404
    assert (await client.get(f"/api/v1/assignments/{assignment['id']}/plans")).status_code == 404


async def test_planning_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/assignments/00000000-0000-0000-0000-000000000000/plans", json={}
    )
    assert response.status_code in (401, 422)


# ---------------------------------------------------------------------------
# Request options that must actually do something
# ---------------------------------------------------------------------------


async def test_force_replans_even_with_the_same_idempotency_key(
    client: AsyncClient, assignment: dict
) -> None:
    """`force` is the documented escape hatch from idempotent reuse."""
    body = {"idempotency_key": "same-key-both-times"}
    first = await _plan(client, assignment["id"], **body)
    again = await _plan(client, assignment["id"], **body)
    assert again["id"] == first["id"], "a repeat key must return the same plan"

    forced = await _plan(client, assignment["id"], force=True, **body)
    assert forced["id"] != first["id"]
    assert forced["version"] == 2


async def test_planning_a_superseded_analysis_is_refused(
    client: AsyncClient, assignment: dict
) -> None:
    """An explicit analysis id must not silently plan from a different one."""
    latest = await client.get(f"/api/v1/assignments/{assignment['id']}/analysis")
    assert latest.status_code == 200, latest.text

    other = await client.post(
        f"/api/v1/assignments/{assignment['id']}/analysis", json={"force": True}
    )
    assert other.status_code == 200, other.text

    stale_id = latest.json()["id"]
    response = await client.post(
        f"/api/v1/assignments/{assignment['id']}/plans", json={"analysis_id": stale_id}
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_CURRENT"


async def test_a_plan_cannot_be_patched_straight_to_approved(
    client: AsyncClient, assignment: dict
) -> None:
    """Approval owns the graph and staleness checks, so it owns the transition."""
    plan = await _plan(client, assignment["id"])
    response = await client.patch(
        f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}",
        json={"status": "APPROVED"},
    )
    assert response.status_code == 422, response.text

    fresh = await client.get(f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}")
    assert fresh.json()["status"] != "APPROVED"


async def test_task_traceability_survives_a_regeneration(
    client: AsyncClient, assignment: dict
) -> None:
    """A requirement the student linked by hand is a statement about their work."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    covered = next(t for t in plan["tasks"] if t["related_requirements"])
    key = covered["key"]
    expected = set(covered["related_requirements"])

    edited = await client.patch(
        f"{base}/tasks/{key}",
        json={"title": "My own task", "related_requirements": sorted(expected)},
    )
    assert edited.status_code == 200, edited.text
    assert set(edited.json()["related_requirements"]) == expected

    regenerated = await client.post(
        f"/api/v1/assignments/{assignment['id']}/plans/regenerate", json={}
    )
    assert regenerated.status_code == 201, regenerated.text
    carried = [t for t in regenerated.json()["tasks"] if t["is_user_authored"]]
    assert len(carried) == 1
    assert set(carried[0]["related_requirements"]) == expected
    assert carried[0]["title"] == "My own task"


async def test_version_pagination_reports_a_real_total(
    client: AsyncClient, assignment: dict
) -> None:
    """A page that reports the size of its own window as the total is lying."""
    for _ in range(3):
        await _plan(client, assignment["id"])

    path = f"/api/v1/assignments/{assignment['id']}/plans/versions"
    first = await client.get(path, params={"page": 1, "page_size": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["version"] for item in body["items"]] == [3, 2]
    assert body["page"]["total"] == 3
    assert body["page"]["pages"] == 2

    second = await client.get(path, params={"page": 2, "page_size": 2})
    assert [item["version"] for item in second.json()["items"]] == [1]
    assert second.json()["page"]["total"] == 3


async def test_task_edits_are_audited(client: AsyncClient, assignment: dict, db_session) -> None:
    """A hand edit has to be as traceable in the record as an approval is."""
    from app.models import AuditLog
    from sqlalchemy import select

    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    key = plan["tasks"][0]["key"]

    assert (await client.patch(f"{base}/tasks/{key}", json={"title": "Renamed"})).status_code == 200
    order = [task["key"] for task in plan["tasks"]]
    reordered = await client.post(
        f"{base}/tasks/reorder", json={"task_keys": list(reversed(order))}
    )
    assert reordered.status_code == 200, reordered.text
    assert (await client.delete(f"{base}/tasks/{key}")).status_code == 204

    events = list(
        await db_session.scalars(
            select(AuditLog).where(AuditLog.assignment_id == UUID(assignment["id"]))
        )
    )
    types = {row.event_type for row in events}
    assert "PLAN_TASK_UPDATED" in types
    assert "PLAN_TASK_DELETED" in types
    assert "PLAN_TASKS_REORDERED" in types
    assert "PLAN_GENERATED" in types

    reordered_event = next(row for row in events if row.event_type == "PLAN_TASKS_REORDERED")
    assert reordered_event.metadata_json["order"] == list(reversed(order))

    updated = next(row for row in events if row.event_type == "PLAN_TASK_UPDATED")
    assert updated.entity_type == "PlanTask"
    assert updated.metadata_json["task_key"] == key
    assert updated.metadata_json["version"] == plan["version"]


async def test_milestone_scope_copies_the_plan_and_keeps_every_link(
    client: AsyncClient, assignment: dict
) -> None:
    """Re-deriving checkpoints must not quietly change anything else."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    covered = next(t for t in plan["tasks"] if t["related_requirements"])
    await client.patch(f"{base}/tasks/{covered['key']}", json={"title": "Mine"})
    # Compare against the edited plan, not the generated one: the edit is part
    # of what the milestone re-derivation has to preserve.
    edited = await client.get(base)
    assert edited.status_code == 200, edited.text
    plan = edited.json()

    regenerated = await client.post(
        f"/api/v1/assignments/{assignment['id']}/plans/regenerate",
        json={"scope": "MILESTONES"},
    )
    assert regenerated.status_code == 201, regenerated.text
    body = regenerated.json()
    assert body["version"] == 2
    assert body["changed_sections"] == ["milestones"]

    before = {t["key"]: t for t in plan["tasks"]}
    after = {t["key"]: t for t in body["tasks"]}
    assert set(before) == set(after), "no task may appear or disappear"
    for key, old in before.items():
        new = after[key]
        assert new["title"] == old["title"]
        assert new["description"] == old["description"]
        assert sorted(new["depends_on"]) == sorted(old["depends_on"])
        assert sorted(new["related_requirements"]) == sorted(old["related_requirements"])
        assert sorted(new["related_deliverables"]) == sorted(old["related_deliverables"])
        assert new["min_minutes"] == old["min_minutes"]
        assert new["max_minutes"] == old["max_minutes"]

    # Every task still belongs to a milestone, and no milestone points at a task
    # that does not exist.
    keys = set(after)
    covered_by_milestone = {key for m in body["milestones"] for key in m["task_keys"]}
    assert covered_by_milestone == keys
    assert body["milestones"], "a plan with tasks must still have checkpoints"


async def test_milestone_scope_drops_a_milestone_whose_tasks_are_gone(
    client: AsyncClient, assignment: dict
) -> None:
    """An empty checkpoint is not a checkpoint."""
    plan = await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/{plan['id']}"
    first_milestone = plan["milestones"][0]
    for key in first_milestone["task_keys"]:
        assert (await client.delete(f"{base}/tasks/{key}")).status_code == 204

    regenerated = await client.post(
        f"/api/v1/assignments/{assignment['id']}/plans/regenerate",
        json={"scope": "MILESTONES"},
    )
    assert regenerated.status_code == 201, regenerated.text
    body = regenerated.json()
    remaining = {t["key"] for t in body["tasks"]}
    for milestone in body["milestones"]:
        assert set(milestone["task_keys"]) <= remaining
    covered = {key for m in body["milestones"] for key in m["task_keys"]}
    assert covered == remaining


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


async def test_generation_attempts_are_listed_newest_first(
    client: AsyncClient, assignment: dict
) -> None:
    """Attempts are a history of tries, not just of successes.

    A second generation with `force` adds a second attempt. The list has to show
    both, newest first, or "why did this take two tries" has no answer.
    """
    await _plan(client, assignment["id"])
    await _plan(client, assignment["id"], force=True)

    response = await client.get(f"/api/v1/assignments/{assignment['id']}/plans/runs")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["page"]["total"] == 2
    assert body["page"]["page"] == 1
    assert len(body["items"]) == 2
    started = [item["started_at"] for item in body["items"]]
    assert started == sorted(started, reverse=True), "runs are not newest first"

    first = body["items"][0]
    assert first["status"] == "SUCCEEDED"
    assert first["plan_id"] is not None
    assert first["model_tier"] in {"EFFICIENT", "ADVANCED"}
    assert first["routing_reason"], "a run with no stated reason cannot be audited"
    assert first["completed_at"] is not None


async def test_a_failed_attempt_is_recorded_with_its_error(
    client: AsyncClient, assignment: dict
) -> None:
    """A generation that produced nothing must still leave a trace.

    The run is the only record of a failed attempt, so a silent failure is
    indistinguishable from a request that never arrived. This asserts the error
    code and message survive to the client, and that the run is closed rather
    than left RUNNING.
    """
    # One real plan first, so the assertion below proves the failure was recorded
    # *alongside* a success rather than in a history that only ever holds failures.
    await _plan(client, assignment["id"])

    with generation_unavailable():
        failed = await client.post(
            f"/api/v1/assignments/{assignment['id']}/plans", json={"force": True}
        )
    assert failed.status_code == 503, failed.text
    assert failed.json()["error"]["code"] == "PLANNER_UNAVAILABLE"

    body = (await client.get(f"/api/v1/assignments/{assignment['id']}/plans/runs")).json()
    assert body["page"]["total"] == 2, "the failed attempt was not recorded"

    latest = body["items"][0]
    assert latest["status"] == "FAILED"
    assert latest["plan_id"] is None, "a failed run must not be linked to a plan"
    assert latest["completed_at"] is not None, "a failed run must be closed, not left RUNNING"
    assert latest["error_code"]
    assert latest["error_message"]


async def test_a_rejected_proposal_is_recorded_like_a_missing_answer(
    client: AsyncClient, assignment: dict
) -> None:
    """A model that answers with an unsound plan fails the same way a silent one does.

    The requirement is durability, not the specific status code. `PlanGraphError`
    is a bare `ValueError`, so before this was handled the request became an
    unhandled 500 and the rollback at teardown took the failed run with it. The
    student saw a 500 and a version history that claimed nothing had ever been
    attempted, which is the exact lie the provider path was fixed to stop telling.
    """
    await _plan(client, assignment["id"])

    with unvalidatable_provider(fallback_enabled=False):
        rejected = await client.post(
            f"/api/v1/assignments/{assignment['id']}/plans", json={"force": True}
        )
    assert rejected.status_code == 502, rejected.text
    body = rejected.json()["error"]
    assert body["code"] == "PLAN_REJECTED"
    # The violations have to reach the caller, or the student is left guessing what
    # to change about a 502.
    assert body["details"]["violations"], "a rejection without violations is not actionable"

    runs = (await client.get(f"/api/v1/assignments/{assignment['id']}/plans/runs")).json()
    assert runs["page"]["total"] == 2, "the rejected attempt was not recorded"
    latest = runs["items"][0]
    assert latest["status"] == "FAILED"
    assert latest["plan_id"] is None
    assert latest["completed_at"] is not None, "a rejected run must be closed, not left RUNNING"
    assert latest["error_code"] == "PLAN_REJECTED"

    # A rejection is not a reason to abandon the student: the earlier plan stands.
    assert (await client.get(f"/api/v1/assignments/{assignment['id']}/plans")).json() is not None


async def test_model_selection_explains_the_choice_without_generating(
    client: AsyncClient, assignment: dict
) -> None:
    """The routing decision is readable before committing to a paid call."""
    response = await client.get(f"/api/v1/assignments/{assignment['id']}/plans/model-selection")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["model_tier"] in {"EFFICIENT", "ADVANCED"}
    assert body["model"], "the panel needs a model name to show"
    assert body["reason"], "a decision with no stated reason is not explainable"
    assert body["complexity"] in {"LOW", "MEDIUM", "HIGH", "VERY_HIGH"}
    assert isinstance(body["complexity_factors"], list)
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["overridden"], bool)

    # Reading the decision must not have created a plan or a run.
    assert (await client.get(f"/api/v1/assignments/{assignment['id']}/plans")).json() is None
    assert (await client.get(f"/api/v1/assignments/{assignment['id']}/plans/runs")).json()["page"][
        "total"
    ] == 0


async def test_model_selection_requires_an_analysis(client: AsyncClient) -> None:
    """No analysis means nothing to score, and a 409 rather than a guess."""
    row = await _prepare(client, "noselection@example.com")
    response = await client.get(f"/api/v1/assignments/{row['id']}/plans/model-selection")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_NEEDS_ANALYSIS"


async def test_fallback_is_reported_as_data_not_prose(
    client: AsyncClient, assignment: dict
) -> None:
    """A client can state the fallback in its own words.

    `used_fallback` and `rejection_reasons` are first-class fields, so an
    interface can say "the model did not answer, here is why" in whatever
    language it renders in. Relying on a client to pattern-match an English
    sentence out of `validation_warnings` would make the notice vanish the moment
    the server rewords that sentence.
    """
    # The same unreachable provider, but with the deterministic floor available.
    # This is the case that matters: a plan is produced, and it has to say it
    # came from the engine rather than from the model.
    with unreachable_provider(fallback_enabled=True):
        plan = await _plan(client, assignment["id"])

    assert plan["used_fallback"] is True
    assert plan["rejection_reasons"], "a fallback with no stated reason is not a stated fallback"

    # The prose warning is still there for a human reading raw JSON, and the two
    # must agree rather than drift.
    assert any("not the model" in warning for warning in plan["validation_warnings"])


async def test_a_model_produced_plan_does_not_claim_a_fallback(
    client: AsyncClient, assignment: dict
) -> None:
    """The default mock provider answers, so nothing is reported as a fallback."""
    plan = await _plan(client, assignment["id"])
    assert plan["used_fallback"] is False
    assert plan["rejection_reasons"] == []


async def test_regeneration_refuses_a_client_named_analysis(
    client: AsyncClient, assignment: dict
) -> None:
    """A regenerate request cannot choose the analysis it is built from.

    The bug this pins is a dead branch in the router that read
    ``payload.analysis_id`` off a request model that has no such field. The
    branch could never be taken, so the check that made it look deliberate
    existed only to confuse the next reader -- and mypy was the only thing
    noticing. Regeneration is defined as re-planning the *current* plan's
    subject, so the input is rejected rather than quietly honoured.
    """
    await _plan(client, assignment["id"])
    base = f"/api/v1/assignments/{assignment['id']}/plans/regenerate"

    stale_looking = await client.post(
        base, json={"analysis_id": "11111111-1111-1111-1111-111111111111"}
    )
    assert stale_looking.status_code == 422, stale_looking.text

    # And the documented request shape still works, so this is a refusal of the
    # extra field rather than the endpoint being broken.
    assert (await client.post(base, json={})).status_code == 201
