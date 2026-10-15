"""The agent-facing tool for the external coding-agent seam (``§19``).

One tool, ``delegate_to_coding_agent``, hands a task description (and optionally
some text files) to whatever :class:`~app.modules.execution.external_agent.ExternalAgent`
the deployment configured. It is deliberately separate from
:mod:`app.modules.agent.execution_tools`: those tools run a program inside the
sandbox, whereas this one asks a *different process* to do the work. Folding them
together would blur the one distinction the phase exists to keep — where the code
actually runs.

The tool can no more choose its target than a sandbox tool can choose its image:
the agent is fixed in :class:`~app.modules.agent.tools.ToolContext` by the runtime.
With no agent bound, or one that reports itself unavailable (the default), it
answers ``unavailable`` rather than silently falling back to the sandbox.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Final

from app.models.enums import AgentToolCategory, AgentToolRisk
from app.modules.agent.tools import ToolContext, ToolPermission, ToolResult
from app.modules.execution.external_agent import (
    MAX_FILE_CHARS,
    MAX_FILES,
    MAX_TASK_CHARS,
    ExternalAgentRequest,
)


class DelegateToCodingAgentTool:
    """Ask an external coding agent to carry out a described task."""

    name = "delegate_to_coding_agent"
    permissions = frozenset({ToolPermission.DELEGATE_EXTERNAL_AGENT})
    category = AgentToolCategory.CODING
    risk_level = AgentToolRisk.HIGH
    deterministic = False
    side_effect_free = False
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "A clear description of the coding task to delegate.",
            },
            "language": {
                "type": "string",
                "description": "Optional primary language of the task.",
            },
            "files": {
                "type": "object",
                "description": "Optional text files (name -> content) to hand over.",
            },
        },
        "required": ["task"],
    }
    description = (
        "Delegate an open-ended coding task to an external coding agent and return "
        "its result. Use this only when the task cannot be answered by running a "
        "short program in the sandbox."
    )

    async def invoke(
        self, arguments: Mapping[str, Any], context: ToolContext
    ) -> ToolResult:
        agent = context.external_agent
        if agent is None:
            return ToolResult.unavailable(
                "No external coding agent is available in this deployment."
            )
        if not agent.available:
            return ToolResult.unavailable(
                agent.unavailable_reason
                or "The external coding agent is unavailable in this deployment."
            )

        task = str(arguments.get("task", "")).strip()
        if not task:
            return ToolResult.refusal("There is no task to delegate.")
        if len(task) > MAX_TASK_CHARS:
            return ToolResult.refusal(
                f"That task is {len(task)} characters; the limit is {MAX_TASK_CHARS}."
            )

        raw_files = arguments.get("files")
        files: dict[str, str] = {}
        if isinstance(raw_files, Mapping):
            if len(raw_files) > MAX_FILES:
                return ToolResult.refusal(
                    f"That is {len(raw_files)} files; the limit is {MAX_FILES}."
                )
            for name, body in raw_files.items():
                text = str(body)
                if len(text) > MAX_FILE_CHARS:
                    return ToolResult.refusal(
                        f"File {name!r} is {len(text)} characters; the limit is "
                        f"{MAX_FILE_CHARS}."
                    )
                files[str(name)] = text

        request = ExternalAgentRequest(
            task=task,
            files=files,
            language=_optional_str(arguments.get("language")),
        )
        try:
            result = await asyncio.to_thread(agent.run, request)
        except Exception as exc:  # the seam is a boundary; never leak a raw error
            return ToolResult.failure(
                f"The external agent could not be reached ({type(exc).__name__})."
            )

        payload = result.as_payload()
        if result.ok:
            return ToolResult.success(result.summary, payload=payload)
        if result.status == "UNAVAILABLE":
            return ToolResult.unavailable(result.summary)
        return ToolResult.partial(
            result.summary,
            payload=payload,
            warnings=("The external agent did not complete the task.",),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


#: The external-agent tools, kept apart from ``EXECUTION_TOOLS`` so the sandbox's
#: "every execution tool is sandboxed" invariant stays a statement about the
#: sandbox and nothing else.
EXTERNAL_AGENT_TOOLS: Final[tuple[Any, ...]] = (DelegateToCodingAgentTool(),)
