from datetime import UTC, datetime, timedelta

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

    finalized = await client.post(f"/api/v1/assignments/{assignment['id']}/finalize")
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "ACTIVE"
    assert finalized.json()["criteria_total"] == 100

    detail = await client.get(f"/api/v1/assignments/{assignment['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["requirements"]) == 1
    assert len(detail.json()["constraints"]) == 1
    assert len(detail.json()["criteria"]) == 2

    deleted = await client.delete(f"/api/v1/assignments/{assignment['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/assignments/{assignment['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_criteria_total_is_checked_at_finalization(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "Draft assignment",
                "deadline": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
    ).json()
    await client.post(
        f"/api/v1/assignments/{assignment['id']}/criteria",
        json={"title": "Partial", "weight": "50"},
    )
    response = await client.post(f"/api/v1/assignments/{assignment['id']}/finalize")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CRITERIA_TOTAL_INVALID"
