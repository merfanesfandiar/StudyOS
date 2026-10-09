"""Every list endpoint that can grow without bound is paginated.

Assignments, specification versions, activity and analysis runs were already
paginated. Courses, notifications and assignment documents were not: a long
career produces a long list of courses and notifications, and uploads accumulate
without an obvious ceiling, so each now answers a ``PageResponse`` with the same
``page``/``page_size`` contract as the rest of the API.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import register_user
from tests.test_courses_assignments import build_ready_specification, create_course


async def _ready_assignment(client: AsyncClient, course_id: str, title: str) -> dict:
    assignment = await build_ready_specification(client, course_id, title=title)
    criterion = await client.post(
        f"/api/v1/assignments/{assignment['id']}/criteria",
        json={"title": "Everything", "weight": "100"},
    )
    assert criterion.status_code == 201, criterion.text
    ready = await client.post(f"/api/v1/assignments/{assignment['id']}/readiness/mark-ready")
    assert ready.status_code == 200, ready.text
    return assignment


@pytest.mark.asyncio
async def test_courses_list_is_paginated(client: AsyncClient) -> None:
    await register_user(client)
    for code in ("CSE1", "CSE2", "CSE3"):
        created = await client.post("/api/v1/courses", json={"name": "Course", "code": code})
        assert created.status_code == 201, created.text

    first = (await client.get("/api/v1/courses?page=1&page_size=2")).json()
    assert [course["code"] for course in first["items"]] == ["CSE1", "CSE2"]
    assert first["page"] == {"page": 1, "page_size": 2, "total": 3, "pages": 2}

    second = (await client.get("/api/v1/courses?page=2&page_size=2")).json()
    assert [course["code"] for course in second["items"]] == ["CSE3"]
    assert second["page"]["page"] == 2

    empty = (await client.get("/api/v1/courses?page=99&page_size=2")).json()
    assert empty["items"] == []
    assert empty["page"]["pages"] == 2


@pytest.mark.asyncio
async def test_notifications_list_is_paginated_and_ordered(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    for title in ("First readiness", "Second readiness"):
        await _ready_assignment(client, course["id"], title=title)

    listed = (await client.get("/api/v1/notifications?page=1&page_size=1")).json()
    assert len(listed["items"]) == 1
    assert listed["page"]["total"] == 2
    assert listed["page"]["pages"] == 2
    assert listed["items"][0]["title"] == "Assignment ready for analysis"

    second = (await client.get("/api/v1/notifications?page=2&page_size=1")).json()
    assert len(second["items"]) == 1


@pytest.mark.asyncio
async def test_documents_list_is_paginated(client: AsyncClient) -> None:
    await register_user(client)
    course = await create_course(client)
    assignment = await _ready_assignment(client, course["id"], title="Paginated documents")
    for name in ("first.pdf", "second.pdf"):
        response = await client.post(
            f"/api/v1/assignments/{assignment['id']}/documents",
            files={"file": (name, b"%PDF-1.4 data", "application/pdf")},
        )
        assert response.status_code == 201, response.text

    listed = (
        await client.get(f"/api/v1/assignments/{assignment['id']}/documents?page_size=1")
    ).json()
    assert len(listed["items"]) == 1
    assert listed["page"]["total"] == 2
    assert listed["page"]["pages"] == 2
    assert listed["items"][0]["filename"] == "first.pdf"


@pytest.mark.asyncio
async def test_page_size_is_capped(client: AsyncClient) -> None:
    await register_user(client)
    response = await client.get("/api/v1/courses?page_size=501")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"