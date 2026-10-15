"""The decision prompt names only the active worker's tools.

The worker boundary has two enforcement points: the semantic layer refuses a
``CALL_TOOL`` outside ``available_tools``, and the prompt never even hands the
model the names of tools outside its worker's set. The second is this file's
subject. ``build_decision_request`` is the *only* place the decision prompt is
built, so pinning it here pins the boundary that reaches the model.
"""

from __future__ import annotations

from uuid import uuid4

from app.ai.prompts.agent import build_decision_request
from app.models.enums import AgentWorkerKind
from app.modules.agent.context import AgentContext
from app.modules.agent.tools import DEFAULT_TOOLS
from app.modules.agent.workers import DEFAULT_WORKER_REGISTRY


def _context(task_key: str) -> AgentContext:
    return AgentContext(
        run_id=uuid4(),
        task_key=task_key,
        text="Work through the task.",
        sections={"task": "Work through the task."},
    )


def test_the_decision_prompt_names_only_the_workers_tools() -> None:
    """A mathematics step must not be told the writing or code words exist."""
    mathematics = DEFAULT_WORKER_REGISTRY.get(AgentWorkerKind.MATHEMATICS)
    request = build_decision_request(
        _context("T1"),
        registry=DEFAULT_TOOLS,
        tool_ids=frozenset(mathematics.tool_ids),
    )
    system = request.messages[0].content

    assert "calculate:" in system, "the mathematics worker's own tools are listed"
    assert "count_words:" not in system, "another worker's tools are not even named"
    assert "top_keywords:" not in system
    assert "count_code_lines:" not in system


def test_the_unbounded_view_remains_the_closed_catalogue() -> None:
    """Without a boundary (the capabilities view) every registered tool is named."""
    request = build_decision_request(_context("T1"), registry=DEFAULT_TOOLS)
    system = request.messages[0].content

    assert "calculate:" in system
    assert "count_words:" in system
    assert "count_code_lines:" in system