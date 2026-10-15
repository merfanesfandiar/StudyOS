"""The external coding-agent seam (``§19``): the seam is honest by default.

The whole point of this seam is that it does not pretend. With no integration
bundled, every real target reports ``unavailable``; only the explicit ``mock`` a
test opts into returns a result. These tests pin that, so a future change cannot
make "disabled" quietly mean "runs anyway".
"""

from __future__ import annotations

from uuid import uuid4

from app.core.config import get_settings
from app.modules.agent.external_agent_tools import (
    EXTERNAL_AGENT_TOOLS,
    DelegateToCodingAgentTool,
)
from app.modules.agent.tools import ToolContext
from app.modules.execution.external_agent import (
    DisabledExternalAgent,
    ExternalAgentRequest,
    MockExternalAgent,
    OpenCodeExternalAgent,
    build_external_agent,
)


def _context(agent=None) -> ToolContext:
    return ToolContext(
        run_id=uuid4(),
        task_id=None,
        task_key="T1",
        context="",
        external_agent=agent,
    )


# ---------------------------------------------------------------------------
# The seam itself
# ---------------------------------------------------------------------------


def test_the_default_seam_is_unavailable_and_runs_nothing() -> None:
    agent = build_external_agent(get_settings())
    assert isinstance(agent, DisabledExternalAgent)
    assert agent.available is False
    result = agent.run(ExternalAgentRequest(task="do a thing"))
    assert result.status == "UNAVAILABLE"
    assert result.ok is False


def test_naming_opencode_without_a_client_is_still_unavailable() -> None:
    settings = get_settings().model_copy(update={"execution_external_agent": "opencode"})
    agent = build_external_agent(settings)
    assert isinstance(agent, OpenCodeExternalAgent)
    assert agent.available is False
    assert "no client is bundled" in (agent.unavailable_reason or "")


def test_the_mock_is_available_and_scripts_its_outcome() -> None:
    assert build_external_agent(
        get_settings().model_copy(update={"execution_external_agent": "mock"})
    ).available
    agent = MockExternalAgent()
    completed = agent.run(ExternalAgentRequest(task="# @agent:summary=done\n"))
    assert completed.status == "COMPLETED"
    assert completed.summary == "done"
    failed = agent.run(ExternalAgentRequest(task="# @agent:fail\n"))
    assert failed.status == "FAILED"


# ---------------------------------------------------------------------------
# The agent tool
# ---------------------------------------------------------------------------


def test_only_the_delegate_tool_holds_the_delegation_permission() -> None:
    assert EXTERNAL_AGENT_TOOLS == (EXTERNAL_AGENT_TOOLS[0],)
    assert type(EXTERNAL_AGENT_TOOLS[0]) is DelegateToCodingAgentTool
    assert "DELEGATE_EXTERNAL_AGENT" in DelegateToCodingAgentTool.permissions
    assert "EXECUTE_SANDBOXED" not in DelegateToCodingAgentTool.permissions


async def test_delegation_is_unavailable_without_an_agent() -> None:
    result = await DelegateToCodingAgentTool().invoke({"task": "x"}, _context())
    assert result.structured_status.value == "UNAVAILABLE"


async def test_delegation_is_unavailable_when_the_agent_is_disabled() -> None:
    result = await DelegateToCodingAgentTool().invoke(
        {"task": "x"}, _context(DisabledExternalAgent())
    )
    assert result.structured_status.value == "UNAVAILABLE"


async def test_delegation_refuses_an_empty_task() -> None:
    result = await DelegateToCodingAgentTool().invoke(
        {"task": "   "}, _context(MockExternalAgent())
    )
    assert result.structured_status.value == "BLOCKED"


async def test_delegation_returns_the_mock_result() -> None:
    result = await DelegateToCodingAgentTool().invoke(
        {"task": "# @agent:summary=did it\n", "files": {"a.py": "print(1)"}},
        _context(MockExternalAgent()),
    )
    assert result.structured_status.value == "SUCCESS"
    assert result.payload["status"] == "COMPLETED"
    assert result.payload["summary"] == "did it"


async def test_delegation_reports_a_failed_agent_as_partial() -> None:
    result = await DelegateToCodingAgentTool().invoke(
        {"task": "# @agent:fail\n"}, _context(MockExternalAgent())
    )
    assert result.structured_status.value == "PARTIAL_SUCCESS"
    assert result.warnings


async def test_delegation_refuses_an_oversized_task() -> None:
    from app.modules.execution.external_agent import MAX_TASK_CHARS

    result = await DelegateToCodingAgentTool().invoke(
        {"task": "x" * (MAX_TASK_CHARS + 1)}, _context(MockExternalAgent())
    )
    assert result.structured_status.value == "BLOCKED"
