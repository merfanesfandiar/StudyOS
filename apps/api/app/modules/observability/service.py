"""Observability service: event recording, correlation, redaction, timelines."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentEvent, AgentRun, Assignment, AuditLog
from app.models.enums import AuditEventType

#: Substring rules, matched case-insensitively against a metadata key.
SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "secret",
    "api_key",
    "private_key",
    "authorization",
)
REDACTED = "[REDACTED]"


def _is_sensitive_key(key: Any) -> bool:
    """Is this metadata key something whose value must never be stored?

    Substring-matching deliberately beats an allowlist here — key names are
    written by many modules and drift. The rule is kept conservative: a bare
    ``token`` matcher would also swallow ``token_usage``, the cost observability
    field, so a key is sensitive when it contains a credential word, is exactly
    ``token``, or ends in ``_token`` (``access_token``, ``refresh_token``).
    """
    lowered = str(key).lower()
    if lowered == "token" or lowered.endswith("_token"):
        return True
    return any(word in lowered for word in SENSITIVE_KEY_SUBSTRINGS)


def redact_dict(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    out: dict[str, Any] = {}
    for k, v in data.items():
        if _is_sensitive_key(k):
            out[k] = REDACTED
            continue
        if isinstance(v, dict):
            out[k] = redact_dict(v)
        elif isinstance(v, str) and len(v) > 8000:
            out[k] = v[:8000] + "...[truncated]"
        else:
            out[k] = v
    return out


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


async def record_event(
    db: AsyncSession,
    run: AgentRun,
    event_type: str,
    summary: str,
    *,
    task_id: UUID | None = None,
    execution_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    trace_id: str | None = None,
    severity: str = "INFO",
    source_component: str = "agent.runtime",
    outcome: str | None = None,
    duration_ms: int | None = None,
) -> AgentEvent:
    workspace_id = None
    try:
        ws = await db.scalar(
            select(Assignment.workspace_id).where(Assignment.id == run.assignment_id)
        )
        workspace_id = ws
    except Exception:
        pass

    run.lock_version = (run.lock_version or 0) + 1
    ev = AgentEvent(
        run_id=run.id,
        sequence=run.lock_version,
        event_type=event_type,
        summary=summary[:500],
        metadata_json=redact_dict(metadata or {}),
        task_id=task_id,
        execution_id=execution_id,
        workspace_id=workspace_id,
        assignment_id=run.assignment_id,
        user_id=None,
        correlation_id=correlation_id or new_correlation_id(),
        causation_id=causation_id,
        trace_id=trace_id or new_trace_id(),
        span_id=new_span_id(),
        severity=severity,
        source_component=source_component,
        outcome=outcome,
        duration_ms=duration_ms,
        schema_version=1,
    )
    db.add(ev)
    await db.flush()
    return ev


async def record_audit_event(
    db: AsyncSession,
    *,
    user_id: UUID | None,
    workspace_id: UUID | None,
    assignment_id: UUID | None,
    agent_run_id: UUID | None,
    event_type: AuditEventType,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    actor_type: str = "user",
    outcome: str | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
    policy_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Insert one security-audit row with all fields set in a single INSERT.

    This never reads back or mutates an existing row: old audit records are
    append-only, and grabbing "the latest row" to update it would race with any
    concurrent writer and corrupt someone else's record.
    """
    log = AuditLog(
        user_id=user_id,
        workspace_id=workspace_id,
        assignment_id=assignment_id,
        agent_run_id=agent_run_id,
        event_type=event_type.value,
        entity_type=entity_type,
        entity_id=entity_id,
        action=(action[:80] if action else None),
        target_type=(target_type[:80] if target_type else None),
        target_id=target_id,
        actor_type=actor_type[:20],
        outcome=(outcome[:30] if outcome else None),
        reason=(reason[:200] if reason else None),
        correlation_id=(correlation_id[:64] if correlation_id else None),
        policy_code=(policy_code[:80] if policy_code else None),
        metadata_json=redact_dict(metadata or {}),
    )
    db.add(log)
    await db.flush()
    return log


class FailureClassifier:
    @staticmethod
    def classify(error: Exception | str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        msg = str(error).lower()
        if "timeout" in msg:
            return {"category": "TIMEOUT", "retryable": True, "code": "TIMEOUT"}
        if "rate" in msg and "limit" in msg:
            return {"category": "RATE_LIMITED", "retryable": True, "code": "RATE_LIMITED"}
        if "permission" in msg or "unauthor" in msg:
            return {
                "category": "PERMISSION_DENIED",
                "retryable": False,
                "code": "PERMISSION_DENIED",
            }
        if "cancel" in msg:
            return {"category": "CANCELLED", "retryable": False, "code": "CANCELLED"}
        if "validat" in msg:
            return {"category": "VALIDATION_ERROR", "retryable": False, "code": "VALIDATION_ERROR"}
        if "budget" in msg or "limit" in msg:
            return {"category": "RESOURCE_LIMIT", "retryable": False, "code": "RESOURCE_LIMIT"}
        if "network" in msg or "connect" in msg or "transient" in msg:
            return {"category": "TRANSIENT", "retryable": True, "code": "TRANSIENT"}
        return {"category": "SYSTEM_ERROR", "retryable": False, "code": "SYSTEM_ERROR"}


class CostCalculator:
    PRICING = {
        "gpt-4o": {"input": 0.000005, "output": 0.000015},
        "gpt-4o-mini": {"input": 0.00000015, "output": 0.0000006},
        "claude-3-5-sonnet": {"input": 0.000003, "output": 0.000015},
        "default": {"input": 0.000001, "output": 0.000002},
    }

    @classmethod
    def estimate(
        cls,
        model: str | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> dict[str, Any]:
        p = cls.PRICING.get(model or "", cls.PRICING["default"])
        pt = prompt_tokens or 0
        ct = completion_tokens or 0
        est = pt * p["input"] + ct * p["output"]
        return {
            "estimated_cost": round(est, 8),
            "pricing_version": "2026-10",
            "model": model,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "source": "estimated",
        }
