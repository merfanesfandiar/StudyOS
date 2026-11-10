"""The execution HTTP contract, against the real router.

These drive the endpoints a client actually calls, with the deterministic mock
backend so the suite is reproducible. What is checked is mostly what a student or
the UI can get *wrong*: submitting an execution for an assignment they do not own,
naming a path outside the workspace, or reading a job that a different workspace
created. The capabilities endpoint is checked because the UI depends on it to hide
what this deployment cannot run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_user

BASE = "/api/v1"


async def _assignment(client: AsyncClient) -> dict:
    course = (
        await client.post("/api/v1/courses", json={"name": "Computing", "code": "CS101"})
    ).json()
    assignment = await client.post(
        "/api/v1/assignments",
        json={
            "course_id": course["id"],
            "title": "Implement a parser",
            "description": "Write and test a small recursive-descent parser.",
            "deadline": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
    )
    assert assignment.status_code == 201, assignment.text
    return assignment.json()


async def test_submitting_a_sync_execution_runs_and_returns_the_result(
    client: AsyncClient, mock_execution
) -> None:
    await register_user(client)
    assignment = await _assignment(client)

    response = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={
            "execution_type": "PYTHON",
            "files": {"main.py": "# @mock:stdout=hello from the sandbox\n"},
            "mode": "sync",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["exit_code"] == 0
    assert "hello from the sandbox" in (body["result_excerpt"] or "")

    detail = await client.get(
        f"{BASE}/assignments/{assignment['id']}/executions/{body['id']}"
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["job"]["id"] == body["id"]
    assert len(payload["attempts"]) == 1
    assert {a["kind"] for a in payload["artifacts"]} >= {"SOURCE"}
    assert payload["events"], "an execution always records events"


async def test_queue_mode_leaves_the_job_queued(client: AsyncClient, mock_execution) -> None:
    await register_user(client)
    assignment = await _assignment(client)
    response = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={"execution_type": "PYTHON", "files": {"main.py": "print(1)\n"}, "mode": "queue"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "QUEUED"


async def test_listing_is_assignment_scoped(client: AsyncClient, mock_execution) -> None:
    await register_user(client)
    assignment = await _assignment(client)
    await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={"execution_type": "PYTHON", "files": {"main.py": "print(1)\n"}},
    )
    listed = await client.get(f"{BASE}/assignments/{assignment['id']}/executions")
    assert listed.status_code == 200
    assert listed.json()["page"]["total"] == 1


async def test_a_path_outside_the_workspace_is_refused_with_422(
    client: AsyncClient, mock_execution
) -> None:
    await register_user(client)
    assignment = await _assignment(client)
    response = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={
            "execution_type": "PYTHON",
            "entrypoint": "../escape.py",
            "files": {"../escape.py": "print(1)"},
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "EXECUTION_REQUEST_REJECTED"


async def test_an_unknown_option_is_refused(client: AsyncClient, mock_execution) -> None:
    await register_user(client)
    assignment = await _assignment(client)
    response = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={
            "execution_type": "PYTHON",
            "files": {"main.py": "print(1)"},
            "options": {"shell": True},
        },
    )
    assert response.status_code == 422


async def test_a_finished_job_cannot_be_cancelled(client: AsyncClient, mock_execution) -> None:
    await register_user(client)
    assignment = await _assignment(client)
    created = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={"execution_type": "PYTHON", "files": {"main.py": "print(1)"}, "mode": "sync"},
    )
    job_id = created.json()["id"]
    cancelled = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions/{job_id}/cancel", json={}
    )
    assert cancelled.status_code == 409


async def test_an_idempotency_key_returns_the_same_job(
    client: AsyncClient, mock_execution
) -> None:
    await register_user(client)
    assignment = await _assignment(client)
    body = {
        "execution_type": "PYTHON",
        "files": {"main.py": "print(1)"},
        "idempotency_key": "once",
    }
    first = await client.post(f"{BASE}/assignments/{assignment['id']}/executions", json=body)
    second = await client.post(f"{BASE}/assignments/{assignment['id']}/executions", json=body)
    assert first.json()["id"] == second.json()["id"]


async def test_someone_elses_idempotency_key_never_leaks_a_job(
    client: AsyncClient, mock_execution
) -> None:
    """A client-chosen key is scoped to its creator: guessing it is not access.

    The key is low-entropy by design (a retry badge), so a global lookup would
    let one student present "run1" and read what another student executed.
    """
    await register_user(client, "owner@example.com")
    assignment = await _assignment(client)
    owner_body = {
        "execution_type": "PYTHON",
        "files": {"main.py": "print('secret')"},
        "idempotency_key": "low-entropy-key",
    }
    created = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions", json=owner_body
    )
    assert created.status_code == 201, created.text

    await client.post("/api/v1/auth/logout")
    await register_user(client, "intruder@example.com")
    replay = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={
            "execution_type": "PYTHON",
            "files": {"main.py": "print(1)"},
            "idempotency_key": "low-entropy-key",
        },
    )
    assert replay.status_code == 404, (
        f"the intruder has no owned assignment, so the request must not resolve: {replay.text}"
    )
    assert replay.json().get("id") != created.json()["id"]


async def test_another_student_cannot_read_the_job(client: AsyncClient, mock_execution) -> None:
    await register_user(client, "owner@example.com")
    assignment = await _assignment(client)
    created = await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={"execution_type": "PYTHON", "files": {"main.py": "print(1)"}},
    )
    job_id = created.json()["id"]

    await client.post("/api/v1/auth/logout")
    await register_user(client, "intruder@example.com")
    stolen = await client.get(
        f"{BASE}/assignments/{assignment['id']}/executions/{job_id}"
    )
    # 404 rather than 403: the assignment itself is not visible to the intruder.
    assert stolen.status_code == 404


async def test_capabilities_describe_the_deployment(client: AsyncClient, mock_execution) -> None:
    await register_user(client)
    response = await client.get(f"{BASE}/executions/capabilities")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert body["backend"] == "MOCK"
    assert body["available"] is True
    assert "PYTHON" in body["execution_types"]
    assert body["limits"]["max_timeout_seconds"] >= 1
    assert body["limits"]["max_active_jobs_per_workspace"] >= 1
    assert body["limits"]["max_jobs_per_user_per_day"] >= 1
    # The external coding-agent seam is reported as unavailable rather than omitted.
    assert body["external_agent"]["kind"] == "disabled"
    assert body["external_agent"]["available"] is False
    assert body["external_agent"]["reason"]
    assert "external_coding_agent" in body["absent_capabilities"]


async def test_the_metrics_endpoint_returns_prometheus_text(
    client: AsyncClient, mock_execution
) -> None:
    from app.modules.execution import metrics

    metrics.reset()
    await register_user(client)
    assignment = await _assignment(client)
    await client.post(
        f"{BASE}/assignments/{assignment['id']}/executions",
        json={
            "execution_type": "PYTHON",
            "files": {"main.py": "# @mock:stdout=counted\n"},
            "mode": "sync",
        },
    )
    response = await client.get(f"{BASE}/executions/metrics")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE execution_jobs_total counter" in response.text
    assert 'execution_jobs_total{status="SUCCEEDED"} 1' in response.text
    metrics.reset()


async def test_metrics_can_be_disabled(
    client: AsyncClient, mock_execution, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.execution import router as execution_router

    monkeypatch.setattr(
        execution_router,
        "settings",
        mock_execution.model_copy(update={"execution_metrics_enabled": False}),
    )
    await register_user(client)
    response = await client.get(f"{BASE}/executions/metrics")
    assert response.status_code == 404


async def test_deleting_an_assignment_removes_execution_artifact_bytes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Deleting an assignment must remove the files its executions produced.

    ``ExecutionJob.assignment_id`` is ``SET NULL`` so the record that untrusted
    code ran survives deletion. Relying on the row cascade therefore removed the
    metadata and left the bytes in storage — a leak with an audit trail. The
    delete path has to remove each object and null the key itself.
    """
    import importlib

    from app.models import Assignment as AssignmentModel
    from app.models import ExecutionArtifact, ExecutionJob

    # ``app.modules.assignments.router`` the attribute is the APIRouter, not the
    # module, so resolve the module the same way the fixtures do.
    assignments_router = importlib.import_module("app.modules.assignments.router")

    await register_user(client)
    assignment = await _assignment(client)
    row = await db_session.get(AssignmentModel, UUID(assignment["id"]))
    assert row is not None

    storage = assignments_router.get_storage()
    key = "executions/job-1/out.txt"
    storage.save(key, BytesIO(b"artifact bytes"), max_bytes=1_024)
    assert storage.exists(key)

    job = ExecutionJob(
        workspace_id=row.workspace_id,
        assignment_id=row.id,
        execution_type="PYTHON",
    )
    db_session.add(job)
    await db_session.flush()
    artifact = ExecutionArtifact(
        job_id=job.id,
        workspace_id=row.workspace_id,
        filename="out.txt",
        storage_key=key,
        kind="OUTPUT",
    )
    db_session.add(artifact)
    await db_session.flush()

    deleted = await client.delete(f"{BASE}/assignments/{row.id}")
    assert deleted.status_code == 204, deleted.text

    assert not storage.exists(key), "the artifact bytes must be deleted with the assignment"
    await db_session.refresh(artifact)
    assert artifact.storage_key is None
    assert await db_session.get(ExecutionJob, job.id) is not None, (
        "the execution record is evidence and must survive the assignment"
    )
