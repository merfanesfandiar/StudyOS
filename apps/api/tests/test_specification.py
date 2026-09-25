"""End-to-end behaviour of the assignment specification engine.

These tests are written against the HTTP contract a user actually touches, and
they double as the executable version of the acceptance scenario: build a
complete specification, see the readiness report, break it, fix it, reload and
confirm the history.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import register_user
from tests.environment import RELIABLE, SKIP_REASON

LONG_DESCRIPTION = (
    "Design and implement shortest-path algorithms and compare their behaviour on "
    "generated graphs. The submission must include the source code, a written report "
    "explaining the correctness argument for each algorithm, and a benchmark section "
    "with measured runtime and memory usage for at least three graph sizes."
)


async def create_course(client: AsyncClient, name: str = "Algorithms") -> dict:
    response = await client.post(
        "/api/v1/courses",
        json={"name": name, "code": "ALG301", "description": "Graph algorithms."},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_assignment(client: AsyncClient, course_id: str) -> dict:
    response = await client.post(
        "/api/v1/assignments",
        json={
            "course_id": course_id,
            "title": "Graph Algorithms Project",
            "description": LONG_DESCRIPTION,
            "deadline": (datetime.now(UTC) + timedelta(days=21)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def add_requirement(
    client: AsyncClient, assignment_id: str, title: str, **extra: object
) -> dict:
    response = await client.post(
        f"/api/v1/assignments/{assignment_id}/requirements",
        json={"title": title, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def add_criterion(client: AsyncClient, assignment_id: str, title: str, weight: str) -> dict:
    response = await client.post(
        f"/api/v1/assignments/{assignment_id}/criteria",
        json={"title": title, "weight": weight},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def build_acceptance_scenario(client: AsyncClient) -> tuple[dict, dict]:
    """Create the Graph Algorithms Project used throughout this module."""
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    modelling = await add_requirement(
        client,
        assignment_id,
        "Model graphs as adjacency lists",
        description="Represent vertices and edges so traversals are O(V+E).",
        priority="HIGH",
        type="DESIGN",
    )
    dijkstra = await add_requirement(
        client, assignment_id, "Implement Dijkstra", priority="CRITICAL", type="FUNCTIONAL"
    )
    bellman = await add_requirement(
        client, assignment_id, "Implement Bellman-Ford", priority="HIGH", type="PERFORMANCE"
    )
    await add_requirement(
        client,
        assignment_id,
        "Write the comparison report",
        priority="MEDIUM",
        type="FUNCTIONAL",
    )

    # Dijkstra needs the graph model; the report needs both algorithms.
    for requirement, depends_on in ((dijkstra, modelling), (bellman, modelling)):
        response = await client.post(
            f"/api/v1/assignments/{assignment_id}/requirements/{requirement['id']}/dependencies",
            json={"depends_on_id": depends_on["id"]},
        )
        assert response.status_code == 201, response.text

    response = await client.post(
        f"/api/v1/assignments/{assignment_id}/requirements/{modelling['id']}/dependencies",
        json={"depends_on_id": dijkstra["id"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DEPENDENCY_CYCLE"

    await client.post(
        f"/api/v1/assignments/{assignment_id}/constraints",
        json={
            "title": "Time limit",
            "description": "Each run must finish within 2 seconds.",
            "value": "2s",
            "type": "TIME",
            "severity": "CRITICAL",
        },
    )
    await client.post(
        f"/api/v1/assignments/{assignment_id}/constraints",
        json={
            "title": "No external graph libraries",
            "description": "Graph structures must be implemented from scratch.",
            "type": "LIBRARY",
            "severity": "CRITICAL",
        },
    )
    await add_criterion(client, assignment_id, "Correctness", "50.00")
    await add_criterion(client, assignment_id, "Report quality", "25.00")
    await add_criterion(client, assignment_id, "Performance", "25.00")
    await client.post(
        f"/api/v1/assignments/{assignment_id}/deliverables",
        json={"title": "Source archive", "type": "SOURCE_CODE", "is_required": True},
    )
    await client.post(
        f"/api/v1/assignments/{assignment_id}/deliverables",
        json={"title": "Written report", "type": "DOCUMENT"},
    )
    await client.post(
        f"/api/v1/assignments/{assignment_id}/technologies",
        json={"name": "Python", "version": "3.12", "category": "LANGUAGE"},
    )
    await client.post(f"/api/v1/assignments/{assignment_id}/tags", json={"name": "graphs"})
    brief = await client.post(
        f"/api/v1/assignments/{assignment_id}/documents",
        files={"file": ("assignment-brief.pdf", b"%PDF-1.7 brief", "application/pdf")},
    )
    assert brief.status_code == 201, brief.text
    return course, assignment


@pytest.mark.asyncio
async def test_acceptance_scenario_specification_readiness_and_recovery(
    client: AsyncClient,
) -> None:
    await register_user(client)
    course, assignment = await build_acceptance_scenario(client)
    assignment_id = assignment["id"]

    # The readiness report is deterministic and explains itself.
    validated = await client.post(f"/api/v1/assignments/{assignment_id}/validate")
    assert validated.status_code == 200, validated.text
    report = validated.json()
    assert report["is_valid"] is True
    assert report["readiness"]["score"] == 100
    assert report["readiness"]["failing_checks"] == []
    assert report["readiness"]["warning_checks"] == []

    ready = await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-ready")
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "READY_FOR_ANALYSIS"

    # The whole specification is one payload, and the dependency graph is acyclic.
    specification = (await client.get(f"/api/v1/assignments/{assignment_id}/specification")).json()
    assert Decimal(specification["criteria_total"]) == Decimal("100.00")
    assert [item["code"] for item in specification["requirements"]] == [
        "REQ-001",
        "REQ-002",
        "REQ-003",
        "REQ-004",
    ]
    assert len(specification["constraints"]) == 2
    assert len(specification["evaluation_criteria"]) == 3
    assert len(specification["deliverables"]) == 2
    assert specification["technologies"][0]["version"] == "3.12"
    assert specification["tags"][0]["name"] == "graphs"
    assert specification["summary"]["requirements_total"] == 4
    assert specification["summary"]["criteria_balanced"] is True

    graph = (
        await client.get(f"/api/v1/assignments/{assignment_id}/requirements/dependency-graph")
    ).json()
    assert graph["has_cycles"] is False
    assert len(graph["edges"]) == 2
    # Every requirement is listed, and always after the requirements it needs.
    assert sorted(graph["execution_order"]) == [node["code"] for node in graph["nodes"]]
    position = {code: index for index, code in enumerate(graph["execution_order"])}
    for edge in graph["edges"]:
        assert position[edge["depends_on_code"]] < position[edge["requirement_code"]]
    # Ties are broken by the numbering the student sees, not by a random id.
    assert graph["execution_order"][0] == "REQ-001"

    # Dropping a requirement is fine on its own, so the assignment stays ready.
    removed = await client.delete(
        f"/api/v1/assignments/{assignment_id}/requirements/{specification['requirements'][0]['id']}"
    )
    assert removed.status_code == 204
    after_requirement_delete = (await client.get(f"/api/v1/assignments/{assignment_id}")).json()
    assert after_requirement_delete["status"] == "READY_FOR_ANALYSIS"
    assert len(after_requirement_delete["requirements"]) == 3

    # Breaking a blocking check demotes the assignment without anyone asking.
    broken = await client.delete(
        f"/api/v1/assignments/{assignment_id}/criteria/"
        f"{specification['evaluation_criteria'][0]['id']}"
    )
    assert broken.status_code == 204

    after_edit = (await client.get(f"/api/v1/assignments/{assignment_id}")).json()
    assert after_edit["status"] == "INCOMPLETE"
    assert Decimal(after_edit["criteria_total"]) == Decimal("50.00")
    assert after_edit["readiness_score"] < 100
    assert after_edit["ready_for_analysis_at"] is None

    # Fixing it restores the gate without any hidden state.
    await add_criterion(client, assignment_id, "Correctness", "50.00")
    assert (
        await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-ready")
    ).status_code == 200

    # A requirement added after a deletion never takes the freed number.
    restored = await client.post(
        f"/api/v1/assignments/{assignment_id}/requirements",
        json={"title": "Model graphs as adjacency lists", "priority": "HIGH"},
    )
    assert restored.status_code == 201
    assert restored.json()["code"] == "REQ-005"

    reloaded = (await client.get(f"/api/v1/assignments/{assignment_id}/specification")).json()
    assert reloaded["readiness"]["is_ready_for_analysis"] is True
    assert reloaded["assignment"]["status"] == "READY_FOR_ANALYSIS"

    # The change feed and the version history explain what happened.
    activity = (await client.get(f"/api/v1/assignments/{assignment_id}/activity")).json()
    assert any("REQ-001" in (item.get("change_summary") or "") for item in activity["items"]), (
        activity["items"]
    )
    event_types = {item["event_type"] for item in activity["items"]}
    assert "SPECIFICATION_MARKED_READY" in event_types
    assert "REQUIREMENT_DELETED" in event_types
    assert "SPECIFICATION_INVALIDATED" in event_types

    versions = (await client.get(f"/api/v1/assignments/{assignment_id}/versions")).json()
    assert versions["page"]["total"] >= 4
    # Snapshots are immutable, so the oldest version still shows the empty
    # specification while the newest one shows the finished one.
    oldest = versions["items"][-1]
    newest = versions["items"][0]
    assert oldest["version"] < newest["version"]
    assert oldest["change_summary"] and newest["change_summary"]
    oldest_snapshot = (
        await client.get(f"/api/v1/assignments/{assignment_id}/versions/{oldest['version']}")
    ).json()
    newest_snapshot = (
        await client.get(f"/api/v1/assignments/{assignment_id}/versions/{newest['version']}")
    ).json()
    assert Decimal(oldest_snapshot["snapshot"]["criteria_total"]) == Decimal("0.00")
    assert Decimal(newest_snapshot["snapshot"]["criteria_total"]) == Decimal("100.00")
    assert len(newest_snapshot["snapshot"]["requirements"]) == 4


@pytest.mark.asyncio
async def test_requirement_codes_are_stable_and_never_reused(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    first = await add_requirement(client, assignment_id, "First")
    second = await add_requirement(client, assignment_id, "Second")
    assert (first["code"], second["code"]) == ("REQ-001", "REQ-002")

    assert (
        await client.delete(f"/api/v1/assignments/{assignment_id}/requirements/{second['id']}")
    ).status_code == 204
    third = await add_requirement(client, assignment_id, "Third")
    assert third["code"] == "REQ-003"
    assert third["sequence"] == 3

    requirements = (await client.get(f"/api/v1/assignments/{assignment_id}/requirements")).json()
    assert [item["code"] for item in requirements] == ["REQ-001", "REQ-003"]


@pytest.mark.asyncio
async def test_requirement_hierarchy_and_deletion_rules(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    parent = await add_requirement(client, assignment_id, "Parent")
    child = await add_requirement(client, assignment_id, "Child", parent_id=parent["id"])
    assert child["parent_id"] == parent["id"]

    loop = await client.patch(
        f"/api/v1/assignments/{assignment_id}/requirements/{parent['id']}",
        json={"parent_id": child["id"]},
    )
    assert loop.status_code == 422
    assert loop.json()["error"]["code"] == "INVALID_PARENT"

    blocked = await client.delete(
        f"/api/v1/assignments/{assignment_id}/requirements/{parent['id']}"
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "REQUIREMENT_HAS_CHILDREN"

    assert (
        await client.delete(f"/api/v1/assignments/{assignment_id}/requirements/{child['id']}")
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/assignments/{assignment_id}/requirements/{parent['id']}")
    ).status_code == 204


@pytest.mark.asyncio
async def test_dependency_rules(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    first = await add_requirement(client, assignment_id, "First")
    second = await add_requirement(client, assignment_id, "Second")
    path = f"/api/v1/assignments/{assignment_id}/requirements"

    self_link = await client.post(
        f"{path}/{first['id']}/dependencies", json={"depends_on_id": first["id"]}
    )
    assert self_link.status_code == 422
    assert self_link.json()["error"]["code"] == "SELF_DEPENDENCY"

    created = await client.post(
        f"{path}/{second['id']}/dependencies", json={"depends_on_id": first["id"]}
    )
    assert created.status_code == 201
    assert created.json()["depends_on_code"] == "REQ-001"

    duplicate = await client.post(
        f"{path}/{second['id']}/dependencies", json={"depends_on_id": first["id"]}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_DEPENDENCY"

    reverse = await client.post(
        f"{path}/{first['id']}/dependencies", json={"depends_on_id": second["id"]}
    )
    assert reverse.status_code == 422
    assert reverse.json()["error"]["code"] == "DEPENDENCY_CYCLE"

    listed = (await client.get(f"{path}/{second['id']}/dependencies")).json()
    assert [item["depends_on_code"] for item in listed] == ["REQ-001"]
    removed = await client.delete(f"{path}/{second['id']}/dependencies/{created.json()['id']}")
    assert removed.status_code == 204
    assert (await client.get(f"{path}/{second['id']}/dependencies")).json() == []


@pytest.mark.asyncio
async def test_criteria_must_total_one_hundred_and_titles_stay_unique(
    client: AsyncClient,
) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    await add_criterion(client, assignment_id, "Correctness", "60.00")
    await add_criterion(client, assignment_id, "Report", "40.00")

    duplicate = await client.post(
        f"/api/v1/assignments/{assignment_id}/criteria",
        json={"title": "correctness", "weight": "10.00"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_CRITERION_TITLE"

    negative = await client.post(
        f"/api/v1/assignments/{assignment_id}/criteria",
        json={"title": "Negative", "weight": "-5"},
    )
    assert negative.status_code == 422

    too_precise = await client.post(
        f"/api/v1/assignments/{assignment_id}/criteria",
        json={"title": "Too precise", "weight": "10.005"},
    )
    assert too_precise.status_code == 422

    listed = (await client.get(f"/api/v1/assignments/{assignment_id}/criteria")).json()
    assert [Decimal(item["weight"]) for item in listed] == [Decimal("60.00"), Decimal("40.00")]


@pytest.mark.asyncio
async def test_readiness_gate_blocks_on_each_missing_blocking_section(
    client: AsyncClient,
) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    empty = (await client.post(f"/api/v1/assignments/{assignment_id}/validate")).json()
    assert empty["is_valid"] is False
    assert "requirements" in empty["readiness"]["failing_checks"]
    assert "evaluation_criteria" in empty["readiness"]["failing_checks"]
    # Advisory sections are warnings, never blockers.
    assert "constraints" in empty["readiness"]["warning_checks"]
    assert "deliverables" in empty["readiness"]["warning_checks"]

    await add_requirement(client, assignment_id, "Do the thing")
    await add_criterion(client, assignment_id, "Everything", "100.00")
    ready = await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-ready")
    assert ready.status_code == 200, ready.text

    # A past deadline is a warning, not a failure.
    past = await client.patch(
        f"/api/v1/assignments/{assignment_id}",
        json={"deadline": (datetime.now(UTC) - timedelta(days=1)).isoformat()},
    )
    assert past.status_code == 200
    report = (await client.post(f"/api/v1/assignments/{assignment_id}/validate")).json()
    assert "deadline" in report["readiness"]["warning_checks"]
    assert "deadline" not in report["readiness"]["failing_checks"]


@pytest.mark.asyncio
async def test_status_transitions_are_guarded(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    direct = await client.patch(
        f"/api/v1/assignments/{assignment_id}", json={"status": "READY_FOR_ANALYSIS"}
    )
    assert direct.status_code == 422
    assert direct.json()["error"]["code"] == "STATUS_NOT_CLIENT_SETTABLE"

    completed = await client.patch(
        f"/api/v1/assignments/{assignment_id}", json={"status": "COMPLETED"}
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"

    # A finished assignment can be reopened: students do hand work back.
    reopened = await client.patch(
        f"/api/v1/assignments/{assignment_id}", json={"status": "INCOMPLETE"}
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "INCOMPLETE"

    assert (
        await client.patch(f"/api/v1/assignments/{assignment_id}", json={"status": "ARCHIVED"})
    ).status_code == 200
    # An archived assignment only comes back as a draft.
    assert (
        await client.patch(f"/api/v1/assignments/{assignment_id}", json={"status": "COMPLETED"})
    ).status_code == 422
    assert (
        await client.patch(f"/api/v1/assignments/{assignment_id}", json={"status": "DRAFT"})
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-ready")
    ).status_code == 422


@pytest.mark.asyncio
async def test_mark_ready_and_reopen_round_trip(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]
    await add_requirement(client, assignment_id, "Do the thing")
    await add_criterion(client, assignment_id, "Everything", "100.00")

    assert (
        await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-ready")
    ).status_code == 200
    # Re-running the gate is idempotent, not an error: the client is retrying a
    # request that already succeeded.
    again = await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-ready")
    assert again.status_code == 200
    assert again.json()["status"] == "READY_FOR_ANALYSIS"

    reopened = await client.post(f"/api/v1/assignments/{assignment_id}/readiness/mark-incomplete")
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "INCOMPLETE"
    assert reopened.json()["ready_for_analysis_at"] is None


@pytest.mark.asyncio
async def test_technology_and_tag_catalogues_are_workspace_scoped(
    client: AsyncClient,
) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    python = await client.post(
        f"/api/v1/assignments/{assignment_id}/technologies",
        json={"name": " python ", "version": "3.12", "category": "LANGUAGE"},
    )
    assert python.status_code == 201
    again = await client.post(
        f"/api/v1/assignments/{assignment_id}/technologies",
        json={"name": "Python", "version": "3.12", "category": "LANGUAGE"},
    )
    # "Python" and " python " are the same catalogue entry, and an assignment
    # may not link the same technology twice.
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "TECHNOLOGY_ALREADY_LINKED"

    workspace_id = python.json()["workspace_id"]
    catalogue = (await client.get(f"/api/v1/workspaces/{workspace_id}/technologies")).json()
    assert [item["name"] for item in catalogue] == ["python"]
    assert len((await client.get(f"/api/v1/assignments/{assignment_id}/technologies")).json()) == 1

    assert (
        await client.post(f"/api/v1/assignments/{assignment_id}/tags", json={"name": "Graphs"})
    ).status_code == 201
    assert (
        await client.post(f"/api/v1/assignments/{assignment_id}/tags", json={"name": " graphs "})
    ).status_code == 409
    assert len((await client.get(f"/api/v1/workspaces/{workspace_id}/tags")).json()) == 1
    assert len((await client.get(f"/api/v1/workspaces/{workspace_id}/tags")).json()) == 1

    assert (
        await client.delete(
            f"/api/v1/assignments/{assignment_id}/technologies/{python.json()['id']}"
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/assignments/{assignment_id}/technologies/{python.json()['id']}"
        )
    ).status_code == 404
    # The catalogue entry survives for the next assignment.
    assert len((await client.get(f"/api/v1/workspaces/{workspace_id}/technologies")).json()) == 1


@pytest.mark.asyncio
async def test_listing_filters_sorts_searches_and_paginates(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    first = await create_assignment(client, course["id"])
    await client.patch(
        f"/api/v1/assignments/{first['id']}", json={"title": "Graph Algorithms Project"}
    )
    second = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "Sorting Lab",
                "description": "Compare three sorting algorithms.",
                "deadline": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
        )
    ).json()
    await add_requirement(client, second["id"], "Something")
    await add_criterion(client, second["id"], "Everything", "100.00")
    await client.post(f"/api/v1/assignments/{second['id']}/tags", json={"name": "graphs"})
    assert (
        await client.post(f"/api/v1/assignments/{second['id']}/readiness/mark-ready")
    ).status_code == 200

    envelope = (await client.get("/api/v1/assignments")).json()
    assert {item["title"] for item in envelope["items"]} == {
        "Graph Algorithms Project",
        "Sorting Lab",
    }
    assert envelope["page"]["total"] == 2
    assert envelope["page"]["pages"] == 1

    by_course = (await client.get(f"/api/v1/assignments?course_id={course['id']}")).json()
    assert by_course["page"]["total"] == 2

    by_status = (await client.get("/api/v1/assignments?status=DRAFT")).json()
    assert [item["title"] for item in by_status["items"]] == ["Graph Algorithms Project"]

    by_tag = (await client.get("/api/v1/assignments?tag=graphs")).json()
    assert [item["title"] for item in by_tag["items"]] == ["Sorting Lab"]

    by_search = (await client.get("/api/v1/assignments?search=graph")).json()
    assert by_search["page"]["total"] == 2

    # A DRAFT assignment is not ready yet either, so it answers to the
    # INCOMPLETE filter; only the assignment that passed the gate does not.
    by_readiness = (await client.get("/api/v1/assignments?readiness=INCOMPLETE")).json()
    assert [item["title"] for item in by_readiness["items"]] == ["Graph Algorithms Project"]
    ready = (await client.get("/api/v1/assignments?readiness=READY_FOR_ANALYSIS")).json()
    assert [item["title"] for item in ready["items"]] == ["Sorting Lab"]

    sorted_asc = (await client.get("/api/v1/assignments?sort_by=title&sort_direction=asc")).json()
    assert [item["title"] for item in sorted_asc["items"]] == [
        "Graph Algorithms Project",
        "Sorting Lab",
    ]

    window = (await client.get("/api/v1/assignments?page=2&page_size=1")).json()
    assert len(window["items"]) == 1
    assert window["page"] == {"page": 2, "page_size": 1, "total": 2, "pages": 2}


@pytest.mark.asyncio
async def test_summary_and_version_history_endpoints(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]
    await add_requirement(client, assignment_id, "Do the thing", priority="CRITICAL")
    await add_criterion(client, assignment_id, "Everything", "100.00")
    await client.post(f"/api/v1/assignments/{assignment_id}/tags", json={"name": "core"})

    summary = (await client.get(f"/api/v1/assignments/{assignment_id}/summary")).json()
    assert summary["requirements_total"] == 1
    assert summary["critical_requirements"] == 1
    assert summary["tags"] == ["core"]
    assert summary["criteria_balanced"] is True
    assert summary["specification_version"] >= 1

    versions = (await client.get(f"/api/v1/assignments/{assignment_id}/versions")).json()
    assert versions["page"]["total"] >= 3
    assert versions["items"][0]["version"] > versions["items"][-1]["version"]
    assert versions["items"][0]["change_summary"]

    missing = await client.get(f"/api/v1/assignments/{assignment_id}/versions/9999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "VERSION_NOT_FOUND"


@pytest.mark.skipif(not RELIABLE, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_every_enum_value_is_accepted_by_the_api(client: AsyncClient) -> None:
    """The wire vocabulary must be exhaustive and stable.

    Each enum value is sent to the endpoint that owns it, so a renamed or
    dropped member fails here instead of silently in a client.
    """
    from app.models.enums import (
        ConstraintSeverity,
        ConstraintType,
        DeliverableStatus,
        DeliverableType,
        NotificationType,
        RequirementPriority,
        RequirementStatus,
        RequirementType,
        TechnologyCategory,
    )

    await register_user(client)
    course = await create_course(client)
    assignment = await create_assignment(client, course["id"])
    assignment_id = assignment["id"]

    def unique(prefix: str, index: int) -> str:
        return f"{prefix} {index}"

    for index, value in enumerate(RequirementType):
        response = await client.post(
            f"/api/v1/assignments/{assignment_id}/requirements",
            json={"title": unique("Requirement", index), "type": value.value},
        )
        assert response.status_code == 201, (value, response.text)

    for index, value in enumerate(RequirementPriority):
        response = await client.post(
            f"/api/v1/assignments/{assignment_id}/requirements",
            json={"title": unique("Priority", index), "priority": value.value},
        )
        assert response.status_code == 201, (value, response.text)

    for index, value in enumerate(RequirementStatus):
        requirement = (
            await client.get(f"/api/v1/assignments/{assignment_id}/requirements")
        ).json()[index]
        response = await client.patch(
            f"/api/v1/assignments/{assignment_id}/requirements/{requirement['id']}",
            json={"status": value.value},
        )
        assert response.status_code == 200, (value, response.text)

    for index, value in enumerate(ConstraintType):
        response = await client.post(
            f"/api/v1/assignments/{assignment_id}/constraints",
            json={
                "title": unique("Constraint", index),
                "description": "Recorded for coverage.",
                "type": value.value,
            },
        )
        assert response.status_code == 201, (value, response.text)

    for index, value in enumerate(ConstraintSeverity):
        response = await client.post(
            f"/api/v1/assignments/{assignment_id}/constraints",
            json={
                "title": unique("Severity", index),
                "description": "Recorded for coverage.",
                "severity": value.value,
            },
        )
        assert response.status_code == 201, (value, response.text)

    for index, value in enumerate(DeliverableType):
        response = await client.post(
            f"/api/v1/assignments/{assignment_id}/deliverables",
            json={"title": unique("Deliverable", index), "type": value.value},
        )
        assert response.status_code == 201, (value, response.text)

    for index, value in enumerate(DeliverableStatus):
        deliverable = (
            await client.get(f"/api/v1/assignments/{assignment_id}/deliverables")
        ).json()[index]
        response = await client.patch(
            f"/api/v1/assignments/{assignment_id}/deliverables/{deliverable['id']}",
            json={"status": value.value},
        )
        assert response.status_code == 200, (value, response.text)

    for index, value in enumerate(TechnologyCategory):
        response = await client.post(
            f"/api/v1/assignments/{assignment_id}/technologies",
            json={"name": unique("Tech", index), "category": value.value},
        )
        assert response.status_code == 201, (value, response.text)

    assert len(NotificationType) >= 1
