from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import register_user


async def setup_assignment(client: AsyncClient, email: str) -> tuple[dict, dict]:
    await register_user(client, email)
    course = (
        await client.post(
            "/api/v1/courses",
            json={"name": "Private course", "code": f"CODE-{email[:2].upper()}"},
        )
    ).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "Private assignment",
                "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()
    return course, assignment


@pytest.mark.asyncio
async def test_user_cannot_access_another_users_resources(client: AsyncClient) -> None:
    _, assignment = await setup_assignment(client, "owner@example.com")
    await client.post("/api/v1/auth/logout")
    await register_user(client, "other@example.com")

    assert (await client.get(f"/api/v1/assignments/{assignment['id']}")).status_code == 404
    course_id = assignment["course_id"]
    updated = await client.patch(f"/api/v1/courses/{course_id}", json={"name": "Stolen"})
    assert updated.status_code == 404
    assert (await client.delete(f"/api/v1/assignments/{assignment['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_delete_another_users_document(client: AsyncClient) -> None:
    _, assignment = await setup_assignment(client, "owner2@example.com")
    upload = await client.post(
        f"/api/v1/assignments/{assignment['id']}/documents",
        files={"file": ("brief.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    await client.post("/api/v1/auth/logout")
    await register_user(client, "other2@example.com")
    response = await client.delete(f"/api/v1/documents/{document_id}")
    assert response.status_code == 404
    assert (await client.get(f"/api/v1/documents/{document_id}/download")).status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_requests_cannot_reach_private_endpoints(client: AsyncClient) -> None:
    _, assignment = await setup_assignment(client, "owner3@example.com")
    await client.post("/api/v1/auth/logout")

    for method, path in [
        ("get", "/api/v1/auth/me"),
        ("get", "/api/v1/courses"),
        ("post", "/api/v1/courses"),
        ("get", "/api/v1/assignments"),
        ("get", f"/api/v1/assignments/{assignment['id']}"),
        ("delete", f"/api/v1/assignments/{assignment['id']}"),
        ("get", f"/api/v1/assignments/{assignment['id']}/requirements"),
        ("get", f"/api/v1/assignments/{assignment['id']}/documents"),
        ("get", "/api/v1/dashboard"),
        ("get", "/api/v1/notifications"),
    ]:
        response = await getattr(client, method)(path)
        assert response.status_code == 401, f"{method.upper()} {path} -> {response.status_code}"
