from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import register_user


async def create_course(
    client: AsyncClient,
    name: str = "Advanced Programming",
    code: str = "AP140",
) -> dict:
    response = await client.post(
        "/api/v1/courses",
        json={"name": name, "code": code, "description": "Software engineering fundamentals."},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_course_crud(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assert course["code"] == "AP140"
    assert course["assignment_count"] == 0

    listed = await client.get("/api/v1/courses")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = await client.patch(
        f"/api/v1/courses/{course['id']}",
        json={"name": "Advanced Programming II"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Advanced Programming II"

    deleted = await client.delete(f"/api/v1/courses/{course['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/courses/{course['id']}")).status_code == 404


LONG_DESCRIPTION = (
    "Design and implement a small turn-based strategy game in Java. The game must support "
    "unit movement, resource gathering and a simple combat loop, and it must be delivered "
    "as a runnable project together with a written report explaining your design decisions."
)


async def build_ready_specification(
    client: AsyncClient, course_id: str, title: str = "Notified assignment"
) -> dict:
    """Create an assignment whose blocking checks all pass."""
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course_id,
                "title": title,
                "description": LONG_DESCRIPTION,
                "deadline": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            },
        )
    ).json()
    await client.post(
        f"/api/v1/assignments/{assignment['id']}/requirements",
        json={"title": "Implement authentication", "priority": "HIGH", "type": "FUNCTIONAL"},
    )
    return assignment


@pytest.mark.asyncio
async def test_assignment_crud_and_nested_specification(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    deadline = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    created = await client.post(
        "/api/v1/assignments",
        json={
            "course_id": course["id"],
            "title": "Build a Java Strategy Game",
            "description": "Create a small strategy game.",
            "deadline": deadline,
        },
    )
    assert created.status_code == 201, created.text
    assignment = created.json()
    assert assignment["status"] == "DRAFT"

    requirement = await client.post(
        f"/api/v1/assignments/{assignment['id']}/requirements",
        json={
            "title": "Implement authentication",
            "description": "Users can register and log in.",
            "priority": "HIGH",
            "type": "FUNCTIONAL",
        },
    )
    assert requirement.status_code == 201
    assert requirement.json()["code"] == "REQ-001"
    constraint = await client.post(
        f"/api/v1/assignments/{assignment['id']}/constraints",
        json={"title": "Java version", "description": "Use Java 17 only.", "value": "17"},
    )
    assert constraint.status_code == 201
    first_criterion = await client.post(
        f"/api/v1/assignments/{assignment['id']}/criteria",
        json={"title": "Functionality", "weight": "60.00"},
    )
    second_criterion = await client.post(
        f"/api/v1/assignments/{assignment['id']}/criteria",
        json={"title": "Code quality", "weight": "40.00"},
    )
    assert first_criterion.status_code == 201
    assert second_criterion.status_code == 201

    ready = await client.post(f"/api/v1/assignments/{assignment['id']}/readiness/mark-ready")
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "READY_FOR_ANALYSIS"
    assert Decimal(ready.json()["criteria_total"]) == Decimal("100.00")
    assert ready.json()["ready_for_analysis_at"] is not None

    detail = await client.get(f"/api/v1/assignments/{assignment['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["requirements"]) == 1
    assert len(detail.json()["constraints"]) == 1
    assert len(detail.json()["criteria"]) == 2

    deleted = await client.delete(f"/api/v1/assignments/{assignment['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/assignments/{assignment['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_criteria_total_blocks_the_readiness_gate(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await build_ready_specification(client, course["id"], title="Draft assignment")
    await client.post(
        f"/api/v1/assignments/{assignment['id']}/criteria",
        json={"title": "Partial", "weight": "50"},
    )
    response = await client.post(f"/api/v1/assignments/{assignment['id']}/readiness/mark-ready")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "ASSIGNMENT_NOT_READY"
    assert "evaluation_criteria" in body["error"]["details"]["failing_checks"]


@pytest.mark.asyncio
async def test_marking_ready_creates_a_notification(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await build_ready_specification(client, course["id"])
    await client.post(
        f"/api/v1/assignments/{assignment['id']}/criteria",
        json={"title": "Everything", "weight": "100"},
    )
    ready = await client.post(f"/api/v1/assignments/{assignment['id']}/readiness/mark-ready")
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "READY_FOR_ANALYSIS"

    notifications = (await client.get("/api/v1/notifications")).json()
    titles = [item["title"] for item in notifications]
    assert "Assignment ready for analysis" in titles

    notification = next(
        item for item in notifications if item["title"] == "Assignment ready for analysis"
    )
    assert notification["read_at"] is None
    assert "Notified assignment" in notification["message"]

    read = await client.post(f"/api/v1/notifications/{notification['id']}/read")
    assert read.status_code == 200
    assert read.json()["read_at"] is not None


@pytest.mark.asyncio
async def test_status_can_be_marked_complete(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={"course_id": course["id"], "title": "Finished assignment"},
        )
    ).json()
    updated = await client.patch(
        f"/api/v1/assignments/{assignment['id']}", json={"status": "COMPLETED"}
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "COMPLETED"

    dashboard = (await client.get("/api/v1/dashboard")).json()
    assert dashboard["completed_assignments_count"] == 1
    assert dashboard["completion_percentage"] == 100
    assert dashboard["upcoming_assignments"] == []
