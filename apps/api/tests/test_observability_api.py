"""Phase 9 HTTP contract: observability and audit.

Covers structured event retrieval with authorization, the timeline, usage and
cost summaries, artifact provenance, redaction of sensitive metadata, failure
classification, and cost estimation — the whole path from record to authorized
read.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage
from app.modules.observability.service import (
    CostCalculator,
    FailureClassifier,
    redact_dict,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_user

BASE = "/api/v1/assignments"


class _DeterministicProvider(LLMProvider):
    """The neighbourhood model double the agent suite uses.

    Draft then complete per task, so a run started under this provider reliably
    produces artifacts whose provenance can then be read back.
    """

    name = "deterministic"
    model = "deterministic-agent-v1"

    def __init__(self) -> None:
        self.seen: list[str | None] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        metadata = request.metadata or {}
        usage = LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        if "agent_execution_input" in metadata:
            key = metadata["agent_execution_input"]["task_key"]
            return LLMResponse(
                content=json.dumps(
                    {
                        "summary": f"Worked on {key}.",
                        "content": f"# Draft for {key}\n\nThe work product.",
                    }
                ),
                provider=self.name,
                model=self.model,
                usage=usage,
                estimated_cost=0.0005,
            )
        key = metadata.get("agent_input", {}).get("task_key")
        self.seen.append(key)
        action = "CREATE_ARTIFACT" if len(self.seen) % 2 == 1 else "COMPLETE_TASK"
        payload: dict[str, Any] = {"action": action, "reason": "Proceeding.", "confidence": 0.9}
        if action == "CREATE_ARTIFACT":
            payload["artifact_type"] = "SOLUTION"
            payload["artifact_title"] = f"{key} draft"
        else:
            payload["task_key"] = key
        return LLMResponse(
            content=json.dumps(payload),
            provider=self.name,
            model=self.model,
            usage=usage,
            estimated_cost=0.0005,
        )


@pytest.fixture
def provider() -> _DeterministicProvider:
    return _DeterministicProvider()


@pytest.fixture(autouse=True)
def use_provider(monkeypatch: pytest.MonkeyPatch, provider: _DeterministicProvider) -> None:
    """Force every agent endpoint onto the deterministic provider."""
    from app.modules.agent import router as agent_router

    monkeypatch.setattr(agent_router, "build_llm_provider", lambda settings: provider)


async def _seed_run(client: AsyncClient) -> dict[str, Any]:
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


@pytest.mark.asyncio
async def test_run_events_are_readable_by_the_owner(client: AsyncClient) -> None:
    seeded = await _seed_run(client)
    response = await client.get(
        f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/events"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == seeded["run_id"]
    assert body["items"], "run creation and the routing decision are recorded"

    created = [e for e in body["items"] if e["event_type"] == "RUN_CREATED"]
    assert created, "the lifecycle starts with run creation"
    assert created[0]["schema_version"] >= 1

    # Sequence is strictly increasing and unique per run.
    sequences = [e["sequence"] for e in body["items"]]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


@pytest.mark.asyncio
async def test_events_cursor_paging_advances_without_repeating(client: AsyncClient) -> None:
    seeded = await _seed_run(client)
    # A just-created run has a single event; a pending interaction adds a second
    # (INTERACTION_REQUESTED), which is what gives the cursor something to do.
    created = await client.post(
        f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/interactions",
        json={
            "interaction_type": "CLARIFICATION",
            "risk": "MEDIUM",
            "priority": "NORMAL",
            "title": "Which proof strategy?",
            "prompt": "Direct construction or monotone subsequence?",
            "options": [],
            "operation_binding": {},
            "ui": {},
            "metadata_json": {},
        },
    )
    assert created.status_code == 201, created.text
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/events"

    first = (await client.get(url, params={"limit": 1})).json()
    assert len(first["items"]) == 1
    assert first["next_cursor"] is not None

    second = (await client.get(url, params={"limit": 1, "cursor": first["next_cursor"]})).json()
    assert second["items"]
    assert second["items"][0]["sequence"] > first["items"][0]["sequence"]

    # A limit above the event count yields no cursor: nothing left to read.
    whole = (await client.get(url, params={"limit": 500})).json()
    assert whole["next_cursor"] is None
    assert len(whole["items"]) >= 2


@pytest.mark.asyncio
async def test_timeline_and_usage_are_owner_only(client: AsyncClient) -> None:
    seeded = await _seed_run(client)
    base = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}"
    assert (await client.get(f"{base}/timeline")).status_code == 200
    usage = await client.get(f"{base}/usage")
    assert usage.status_code == 200
    body = usage.json()
    assert body["pricing_version"], "cost output names the pricing version applied"
    assert body["cost_source"] in {"provider_estimate", "unavailable"}

    # A stranger gets the same answer a missing run would give: nothing.
    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "StrongPass123"},
    )
    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": "StrongPass123"},
    )
    assert (await client.get(f"{base}/events")).status_code == 404
    assert (await client.get(f"{base}/timeline")).status_code == 404
    assert (await client.get(f"{base}/usage")).status_code == 404


@pytest.mark.asyncio
async def test_artifact_provenance_and_unknown_artifact(
    client: AsyncClient, provider: _DeterministicProvider
) -> None:
    seeded = await _seed_run(client)
    # Artifacts only exist after the run has actually executed.
    started = await client.post(
        f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/start", json={}
    )
    assert started.status_code in (200, 201, 202), started.text
    detail = await client.get(
        f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["artifacts"], "the deterministic run produced a draft"
    artifact_id = detail.json()["artifacts"][0]["id"]

    provenance = await client.get(
        f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}"
        f"/artifacts/{artifact_id}/provenance"
    )
    assert provenance.status_code == 200, provenance.text
    body = provenance.json()
    assert body["artifact_id"] == artifact_id
    assert body["revision"] >= 1
    assert body["events"], "provenance links the artifact to its producing events"

    unknown = await client.get(
        f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}"
        f"/artifacts/{uuid4()}/provenance"
    )
    assert unknown.status_code == 404


# ---------------------------------------------------------------------------
# Operational signals: stalled runs, owner gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signals_report_a_stalled_running_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A RUNNING run whose newest event predates the threshold is flagged."""
    from datetime import UTC, datetime, timedelta

    from app.models import AgentEvent, AgentRun
    from sqlalchemy import update

    seeded = await _seed_run(client)
    assignment_id, run_id = seeded["assignment_id"], seeded["run_id"]

    # Start the run so it is RUNNING, then age every event past the threshold.
    started = await client.post(f"{BASE}/{assignment_id}/agent/runs/{run_id}/start", json={})
    assert started.status_code in (200, 201, 202), started.text

    stale = datetime.now(UTC) - timedelta(minutes=30)
    await db_session.execute(update(AgentEvent).values(created_at=stale.replace(tzinfo=None)))
    await db_session.execute(
        update(AgentRun).values(status="RUNNING", created_at=stale.replace(tzinfo=None))
    )
    await db_session.commit()

    response = await client.get(f"{BASE}/{assignment_id}/agent/runs/{run_id}/signals")
    assert response.status_code == 200, response.text
    body = response.json()
    stalled_ids = {item["run_id"] for item in body["stalled_runs"]}
    assert run_id in stalled_ids, "an aged RUNNING run must be reported as stalled"
    assert all("stalled_minutes" in item for item in body["stalled_runs"])


@pytest.mark.asyncio
async def test_signals_are_workspace_scoped_for_outsiders(client: AsyncClient) -> None:
    """An outsider gets 404 (no details leak), matching every other owned path."""
    seeded = await _seed_run(client)
    url = f"{BASE}/{seeded['assignment_id']}/agent/runs/{seeded['run_id']}/signals"

    await client.post("/api/v1/auth/logout")
    outsider_credentials = {
        "name": "Other",
        "email": "signals-o@example.com",
        "password": "StrongPass123",
    }
    await client.post("/api/v1/auth/register", json=outsider_credentials)
    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/login",
        json={"email": outsider_credentials["email"], "password": outsider_credentials["password"]},
    )
    outsider = await client.get(url)
    assert outsider.status_code == 404, outsider.text


# ---------------------------------------------------------------------------
# Unit-level: redaction, classification, cost estimation
# ---------------------------------------------------------------------------

def test_redaction_removes_secrets_from_nested_metadata() -> None:
    cleaned = redact_dict(
        {
            "operation": "read_context",
            "credentials": {"api_key": "sk-live-123", "token": "tok"},
            "password": "hunter2",
            "note": "safe value",
        }
    )
    assert cleaned["credentials"]["api_key"] == "[REDACTED]"
    assert cleaned["credentials"]["token"] == "[REDACTED]"
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["note"] == "safe value"


def test_redaction_keeps_observability_fields_like_token_usage() -> None:
    """Substring redaction must not eat the cost ledger.

    ``token_usage`` contains "token", so a naive substring rule destroyed the
    one metadata field that says what a provider call cost. Credential words
    still redact everywhere they appear; only bare/``*_token`` names are
    blanket-sensitive.
    """
    cleaned = redact_dict(
        {
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "gpt-5",
            "estimated_cost": 0.0001,
        }
    )
    assert cleaned["token_usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert cleaned["model"] == "gpt-5"

    still_hidden = redact_dict(
        {
            "access_token": "a.b.c",
            "refresh_token": "r",
            "client_secret": "s",
            "Authorization": "Bearer x",
        }
    )
    assert all(
        v == "[REDACTED]" for v in still_hidden.values()
    ), still_hidden


def test_redaction_bounds_oversized_strings() -> None:
    cleaned = redact_dict({"blob": "x" * 50_000})
    assert len(cleaned["blob"]) < 50_000
    assert cleaned["blob"].endswith("...[truncated]")


def test_failure_classification_maps_messages_to_categories() -> None:
    timeout = FailureClassifier.classify("upstream timeout after 30s")
    assert timeout["category"] == "TIMEOUT"
    assert timeout["retryable"] is True

    denied = FailureClassifier.classify("permission denied for tool write_file")
    assert denied["category"] == "PERMISSION_DENIED"
    assert denied["retryable"] is False

    rate = FailureClassifier.classify("rate limit reached for provider")
    assert rate["category"] == "RATE_LIMITED"

    unknown = FailureClassifier.classify("boom")
    assert unknown["category"] == "SYSTEM_ERROR"


def test_cost_estimation_scales_with_tokens_and_names_pricing() -> None:
    pricing = CostCalculator.estimate("gpt-4o", 1_000, 500)
    assert pricing["prompt_tokens"] == 1_000
    assert pricing["completion_tokens"] == 500
    expected = 1_000 * 0.000005 + 500 * 0.000015
    assert abs(pricing["estimated_cost"] - expected) < 1e-9
    assert pricing["pricing_version"] == "2026-10"
    assert pricing["source"] == "estimated"

    # Missing usage must not silently bill zero.
    missing = CostCalculator.estimate("gpt-4o", None, None)
    assert missing["prompt_tokens"] == 0 and missing["completion_tokens"] == 0
