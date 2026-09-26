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
async def test_documents_are_specification_changes(client: AsyncClient) -> None:
    """Resources take part in the readiness checklist.

    Uploading and deleting a document has to move the stored readiness score,
    show up in the assignment change feed, and leave no orphaned row behind.
    """
    await register_user(client, "documents-spec@example.com")
    course = (await client.post("/api/v1/courses", json={"name": "Docs", "code": "DOC2"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={"course_id": course["id"], "title": "Resource assignment"},
        )
    ).json()
    assignment_id = assignment["id"]

    async def stored_score() -> str:
        response = await client.get(f"/api/v1/assignments/{assignment_id}")
        return response.json()["readiness_score"]

    empty_score = await stored_score()
    uploaded = await client.post(
        f"/api/v1/assignments/{assignment_id}/documents",
        files={"file": ("brief.pdf", b"%PDF-1.4 brief", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    assert await stored_score() != empty_score

    activity = (await client.get(f"/api/v1/assignments/{assignment_id}/activity")).json()
    summaries = [item["change_summary"] for item in activity["items"]]
    assert "Uploaded brief.pdf" in summaries

    assert (await client.delete(f"/api/v1/documents/{document_id}")).status_code == 204
    assert await stored_score() == empty_score
    listed = await client.get(f"/api/v1/assignments/{assignment_id}/documents")
    assert listed.json() == []

    activity = (await client.get(f"/api/v1/assignments/{assignment_id}/activity")).json()
    summaries = [item["change_summary"] for item in activity["items"]]
    assert "Deleted brief.pdf" in summaries


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


@pytest.mark.asyncio
async def test_every_resource_type_the_analyzer_promises_is_accepted(
    client: AsyncClient,
) -> None:
    """The prompt's minimum resource set must be uploadable, not just parseable.

    CSV, PPTX and XLSX are read by the analysis layer, so refusing them at upload
    would make that extraction code unreachable in production.
    """
    from app.services.file_validation import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES

    accepted = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".png": "image/png",
    }
    assert set(accepted) <= ALLOWED_EXTENSIONS, "every promised type must be uploadable"
    for extension, mime_type in accepted.items():
        assert mime_type in ALLOWED_MIME_TYPES[extension], f"{extension} needs its MIME type"

    await register_user(client, "types@example.com")
    course = (await client.post("/api/v1/courses", json={"name": "Types", "code": "TYP1"})).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={"course_id": course["id"], "title": "Resource types"},
        )
    ).json()

    for index, (extension, mime_type) in enumerate(accepted.items()):
        response = await client.post(
            f"/api/v1/assignments/{assignment['id']}/documents",
            files={"file": (f"resource{index}{extension}", b"content", mime_type)},
        )
        assert response.status_code == 201, f"{extension}: {response.text}"
        assert response.json()["filename"] == f"resource{index}{extension}"


@pytest.mark.asyncio
async def test_a_promised_extension_with_the_wrong_mime_type_is_still_rejected(
    client: AsyncClient,
) -> None:
    """Allowing an extension must not mean trusting the client's content type."""
    await register_user(client, "mismatch@example.com")
    course = (
        await client.post("/api/v1/courses", json={"name": "Mismatch", "code": "MMS1"})
    ).json()
    assignment = (
        await client.post(
            "/api/v1/assignments",
            json={"course_id": course["id"], "title": "Mime mismatch"},
        )
    ).json()

    response = await client.post(
        f"/api/v1/assignments/{assignment['id']}/documents",
        files={"file": ("sheet.xlsx", b"binary", "application/octet-stream")},
    )
    assert response.status_code == 415
