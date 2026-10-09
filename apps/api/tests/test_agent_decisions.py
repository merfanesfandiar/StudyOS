"""The three validation layers that gate a tool call.

``test_agent_runtime.py`` proves a run can call a tool, but the contract itself
-- what makes a tool call legal -- belongs in a pure test. A tool call that the
model formats wrong, names wrong, or asks with permissions it does not hold must
be refused before anything is dispatched, and each refusal must name its layer.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models.enums import AgentRunMode
from app.modules.agent.decisions import (
    DecisionContext,
    DecisionRejected,
    parse_decision,
    validate_permissions,
    validate_semantics,
)
from app.modules.agent.tools import DEFAULT_GRANTED_PERMISSIONS, DEFAULT_TOOLS

GRANTED = DEFAULT_GRANTED_PERMISSIONS


def _ctx(*, granted: frozenset[str] | None = None) -> DecisionContext:
    return DecisionContext(
        run_id=uuid4(),
        mode=AgentRunMode.SUPERVISED,
        available_tools=frozenset(DEFAULT_TOOLS.names()),
        tool_permissions={
            name: DEFAULT_TOOLS.get(name).permissions for name in DEFAULT_TOOLS.names()
        },
        granted_permissions=GRANTED if granted is None else granted,
    )


def test_a_call_must_name_a_tool() -> None:
    """CALL_TOOL with no ``tool`` is a schema failure before anything else."""
    with pytest.raises(DecisionRejected) as caught:
        parse_decision('{"action": "CALL_TOOL", "reason": "r", "confidence": 0.9}')
    assert caught.value.layer == "schema"
    assert caught.value.code == "AGENT_DECISION_INCOMPLETE"
    assert caught.value.errors == [{"loc": ["tool"], "msg": "required for this action"}]


def test_an_unregistered_tool_is_refused_at_the_semantic_layer() -> None:
    decision = parse_decision(
        '{"action": "CALL_TOOL", "reason": "r", "confidence": 0.9, "tool": "not_a_real_tool"}'
    )
    with pytest.raises(DecisionRejected) as caught:
        validate_semantics(decision, _ctx())
    assert caught.value.layer == "semantic"
    assert caught.value.code == "AGENT_TOOL_UNKNOWN"


def test_an_ungranted_permission_is_refused_at_the_permission_layer() -> None:
    decision = parse_decision(
        '{"action": "CALL_TOOL", "reason": "r", "confidence": 0.9, '
        '"tool": "write_artifact", "tool_arguments": {"title": "t", "content": "c"}}'
    )
    # A run granted only READ_CONTEXT cannot draft artifacts, even though the
    # tool exists.
    with pytest.raises(DecisionRejected) as caught:
        validate_permissions(decision, _ctx(granted=frozenset({"READ_CONTEXT"})))
    assert caught.value.layer == "permission"
    assert caught.value.code == "AGENT_TOOL_PERMISSION_DENIED"


def test_a_permitted_call_passes_all_validation_layers() -> None:
    decision = parse_decision(
        '{"action": "CALL_TOOL", "reason": "r", "confidence": 0.9, '
        '"tool": "request_checkpoint", "tool_arguments": {"question": "q"}}'
    )
    ctx = _ctx()
    validate_semantics(decision, ctx)
    validate_permissions(decision, ctx)
    assert decision.tool == "request_checkpoint"


def test_tools_have_no_forbidden_permissions() -> None:
    """No built-in tool may declare a permission the run can never grant."""
    from app.modules.agent.tools import FORBIDDEN_PERMISSIONS

    for name in DEFAULT_TOOLS.names():
        assert not (DEFAULT_TOOLS.get(name).permissions & FORBIDDEN_PERMISSIONS), name