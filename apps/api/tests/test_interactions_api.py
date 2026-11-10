"""Phase 8 HTTP contract: durable HITL interactions.

These tests exercise the endpoints a student's browser actually calls: creating
an interaction on an owned run, answering it, rejecting it, cancelling it, and
- because an approval is authorisation to do one specific thing - watching an
expired request fail closed rather than silently authorise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import register_user

BASE = "/api/v1/assignments"


async def _seed_run(client: AsyncClient) -> dict[str, Any]:
    """Drive the real API to an approved plan plus a created (not started) run."""
    from tests.test_agent_api import _seeded_assignment

    await register_user(client)
    seeded = await _seeded_assignment(client, keys=("T1",))
    assignment_id = seeded["assignment"]["id"]
    approved = await client.post(
        f"{BASE}/{assignment_id}/plans/{seeded['plan']['id']}/approve", json={}
    )
    assert approved.status_code in (200, 201), approved.text
    created = await client.post(f"{BASE}/{assignment_id}/agent/runs", json={})
    assert created.status_code == 201, created.text
    return {
        "assignment_id": assignment_id,
        "run_id": created.json()["id"],
    }


def _interaction_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "interaction_type": "CLARIFICATION",
        "risk": "MEDIUM",
        "priority": "NORMAL",
        "title": "Which proof strategy?",
        "prompt": "Direct construction or monotone subsequence?",
        "options": [
            {"value": "direct", "label": "Direct"},
            {"value": "subsequence", "label": "Subsequence"},
        ],
        "operation_binding": {"operation": "proof_strategy", "target": "T1"},
        "ui": {},
        "metadata_json": {},
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_and_read_back_an_interaction(client: AsyncClient) -> None:
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"

    created = await client.post(url, json=_interaction_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "PENDING"
    assert body["interaction_type"] == "CLARIFICATION"
    assert body["operation_binding"]["operation"] == "proof_strategy"
    assert body["responses"] == []
    assert body["version"] == 1

    listed = await client.get(url)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]

    # A status filter that matches nothing lists nothing rather than failing.
    empty = await client.get(f"{url}?status=REJECTED")
    assert empty.status_code == 200
    assert empty.json() == []


@pytest.mark.asyncio
async def test_accept_resolves_and_reject_does_not_resume(client: AsyncClient) -> None:
    """A rejection is recorded and consumed; only approval authorises."""
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"

    rejected = await client.post(f"{url}", json=_interaction_payload())
    interaction_id = rejected.json()["id"]

    answered = await client.post(
        f"{url}/{interaction_id}/respond",
        json={"action": "reject", "payload": {}, "rationale": "Wrong approach."},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "REJECTED"

    # The decision history is immutable: rejecting again is a conflict.
    replay = await client.post(
        f"{url}/{interaction_id}/respond",
        json={"action": "approve", "payload": {}},
    )
    assert replay.status_code == 409, replay.text
    assert replay.json()["error"]["code"] == "AGENT_INTERACTION_ALREADY_RESOLVED"

    history = await client.get(f"{url}/{interaction_id}/history")
    assert history.status_code == 200, history.text
    entries = history.json()
    assert len(entries) == 1
    assert entries[0]["status"] == "REJECTED"
    assert entries[0]["response_type"] == "reject"
    assert entries[0]["operation_binding_snapshot"]["operation"] == "proof_strategy"


@pytest.mark.asyncio
async def test_an_expired_interaction_cannot_authorise(client: AsyncClient) -> None:
    """Expiring must refuse the answer and mark the interaction EXPIRED."""
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"

    created = await client.post(
        url,
        json=_interaction_payload(
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        ),
    )
    interaction_id = created.json()["id"]

    answered = await client.post(
        f"{url}/{interaction_id}/respond",
        json={"action": "approve", "payload": {}},
    )
    assert answered.status_code == 409, answered.text
    assert answered.json()["error"]["code"] == "AGENT_INTERACTION_EXPIRED"

    detail = await client.get(f"{url}/{interaction_id}")
    assert detail.json()["status"] == "EXPIRED"


@pytest.mark.asyncio
async def test_cancel_prevents_a_later_approval(client: AsyncClient) -> None:
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"

    created = await client.post(url, json=_interaction_payload())
    interaction_id = created.json()["id"]

    cancelled = await client.post(
        f"{url}/{interaction_id}/cancel", json={"reason": "Changed my mind."}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"

    answered = await client.post(
        f"{url}/{interaction_id}/respond", json={"action": "approve", "payload": {}}
    )
    assert answered.status_code == 409, answered.text


@pytest.mark.asyncio
async def test_an_unknown_action_is_refused(client: AsyncClient) -> None:
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"

    created = await client.post(url, json=_interaction_payload())
    interaction_id = created.json()["id"]

    answered = await client.post(
        f"{url}/{interaction_id}/respond", json={"action": "grant_total_access"}
    )
    assert answered.status_code == 422, answered.text


@pytest.mark.asyncio
async def test_another_student_cannot_touch_your_interaction(client: AsyncClient) -> None:
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"
    created = await client.post(url, json=_interaction_payload())
    interaction_id = created.json()["id"]

    # Sign in as someone else: the run (and therefore the interaction) is not
    # discoverable at all - 404, never 403 with details.
    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "intruder@example.com", "password": "StrongPass123"},
    )
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"name": "Intruder", "email": "intruder@example.com", "password": "StrongPass123"},
        )
    ).status_code == 201
    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "intruder@example.com", "password": "StrongPass123"},
    )

    listed = await client.get(url)
    assert listed.status_code == 404, "another student's run must not be discoverable"
    answered = await client.post(
        f"{url}/{interaction_id}/respond", json={"action": "approve", "payload": {}}
    )
    assert answered.status_code == 404, answered.text


@pytest.mark.asyncio
async def test_an_expired_interaction_is_marked_expired_on_listing(
    client: AsyncClient,
) -> None:
    """The sweep gives staleness a visible status; it never grants consent.

    The security property is enforced at respond time (an expired interaction
    raises AGENT_INTERACTION_EXPIRED and fails closed); this test checks that
    the *visible* status also converges instead of reading PENDING forever.
    """
    from datetime import UTC, datetime, timedelta

    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"
    created = await client.post(
        url,
        json=_interaction_payload(
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        ),
    )
    interaction_id = created.json()["id"]

    listed = await client.get(url)
    assert listed.status_code == 200
    by_id = {item["id"]: item for item in listed.json()}
    assert by_id[interaction_id]["status"] == "EXPIRED"


@pytest.mark.asyncio
async def test_an_invalid_status_filter_is_refused(client: AsyncClient) -> None:
    """A query the endpoint cannot honour is a 422, not silently-empty 200."""
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"
    response = await client.get(url, params={"status": "NOT_A_STATUS"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_responding_records_a_run_event(client: AsyncClient) -> None:
    """The lifecycle is observable in the run's own activity stream."""
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions"

    created = await client.post(url, json=_interaction_payload())
    interaction_id = created.json()["id"]

    events_url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/events"
    requested = await client.get(events_url)
    assert requested.status_code == 200, requested.text
    types = {item["event_type"] for item in requested.json()["items"]}
    assert "INTERACTION_REQUESTED" in types

    await client.post(f"{url}/{interaction_id}/respond", json={"action": "approve", "payload": {}})
    after = (await client.get(events_url)).json()
    kinds = {item["event_type"] for item in after["items"]}
    assert "INTERACTION_RESPONDED" in kinds
