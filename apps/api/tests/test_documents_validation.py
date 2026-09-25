from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import register_user


@pytest.mark.asyncio
async def test_document_upload_list_download_and_delete(client: AsyncClient) -> None:
    await register_user(client, "upload@example.com")
    course = (
        await client.post("/api/v1/courses", json={"name": "Documents", "code": "DOC1"})
    ).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={
                "course_id": course["id"],
                "title": "Upload assignment",
                "deadline": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
    ).json()
    response = await client.post(
        f"/api/v1/assignments/{assignment['id']}/documents",
        files={"file": ("../../unsafe.pdf", b"%PDF-1.4 safe", "application/pdf")},
    )
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["filename"] == "unsafe.pdf"
    assert "storage_key" not in document

    listed = await client.get(f"/api/v1/assignments/{assignment['id']}/documents")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    downloaded = await client.get(f"/api/v1/documents/{document['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.4 safe"
    assert "unsafe.pdf" in downloaded.headers["content-disposition"]

    deleted = await client.delete(f"/api/v1/documents/{document['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/documents/{document['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_upload_rejects_wrong_type_and_naive_deadline(client: AsyncClient) -> None:
    await register_user(client, "validation@example.com")
    course = (
        await client.post("/api/v1/courses", json={"name": "Validation", "code": "VAL1"})
    ).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={"course_id": course["id"], "title": "Validation assignment"},
        )
    ).json()
    invalid_file = await client.post(
        f"/api/v1/assignments/{assignment['id']}/documents",
        files={"file": ("payload.exe", b"binary", "application/octet-stream")},
    )
    assert invalid_file.status_code == 415
    naive_deadline = await client.patch(
        f"/api/v1/assignments/{assignment['id']}",
        json={"deadline": "2030-01-01T12:00:00"},
    )
    assert naive_deadline.status_code == 422
    assert naive_deadline.json()["error"]["code"] == "VALIDATION_ERROR"
