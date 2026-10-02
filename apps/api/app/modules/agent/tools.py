"""Tools the agent runtime may use.

This module is the security boundary, and its most important property is what is
*absent*. There is no shell, no subprocess, no filesystem, no HTTP client, no
browser and no code execution anywhere in the registry, and no configuration
option that would add one. That is not an oversight to be fixed later; it is the
design. A tool registry with a "disabled by default" dangerous entry is a
registry that will eventually have it enabled.

What a tool *is* therefore very narrow: a named, typed, pure-ish function over
data the runtime already has. Three built-ins exist:

* ``read_context`` — read a bounded slice of the assembled context.
* ``write_artifact`` — draft an artifact for a task, persisted and attributed.
* ``request_checkpoint`` — ask the student a question and stop.

Every tool declares its own permissions, and :meth:`ToolRegistry.assert_permitted`
is the only path to invocation. The registry refuses a tool that is not
registered by name rather than falling back to a default, so "the model asked for
a tool that does not exist" is a recorded ``TOOL_BLOCKED`` event instead of a
silent no-op.

Note that ``write_artifact`` drafts text. It does not execute it. A tool may
produce an artifact of type ``CODE`` — see :mod:`app.modules.agent.domain` for
why that is safe.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from uuid import UUID

from app.core.errors import AppError
from app.models.enums import AgentArtifactType, AgentCheckpointType


class ToolPermission:
    """What a tool is allowed to do.

    Named rather than boolean so that adding a capability later is a visible
    vocabulary change, and so a grant reads as a sentence.
    """

    READ_CONTEXT: Final = "READ_CONTEXT"
    WRITE_ARTIFACT: Final = "WRITE_ARTIFACT"
    ASK_USER: Final = "ASK_USER"
    REQUEST_APPROVAL: Final = "REQUEST_APPROVAL"
    #: Present so a future tool that *would* need it has to be named in review
    #: rather than reaching for an existing capability. Never granted today.
    EXECUTE_UNTRUSTED: Final = "EXECUTE_UNTRUSTED"


#: Permissions no tool may hold, regardless of what a tool declares. A tool that
#: asks for one of these is a bug, and failing registration surfaces it.
FORBIDDEN_PERMISSIONS: Final[frozenset[str]] = frozenset({ToolPermission.EXECUTE_UNTRUSTED})


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool produced. Always data, never a side effect the caller cannot name."""

    ok: bool
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Set when the tool refused. ``reason`` is written for a student.
    reason: str | None = None

    @classmethod
    def refusal(cls, reason: str) -> ToolResult:
        return cls(ok=False, summary=reason, reason=reason)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a tool is handed.

    Passed explicitly rather than imported so that the set of things a tool can
    reach is readable in one place. There is no session, no request object and no
    settings object here — a tool cannot reach the database, the clock or the
    network through this argument.
    """

    run_id: UUID
    task_id: UUID | None
    task_key: str
    #: The assembled, already-truncated context text.
    context: str
    #: Bounded slices the model may read.
    context_sections: Mapping[str, str] = field(default_factory=dict)
    #: Artifacts already produced in this run, newest last.
    prior_artifacts: tuple[str, ...] = ()


class AgentTool(Protocol):
    """The interface every tool implements.

    Deliberately narrow: name, permissions, a JSON-schema-ish description and an
    async invoke. There is no ``run_command`` method on this protocol, and adding
    one would change what the runtime *is*.
    """

    name: str
    permissions: frozenset[str]
    description: str

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """Do the tool's one job. Must not raise for expected refusals."""
        ...


class ToolNotRegisteredError(AppError):
    """The runtime was asked for a tool that does not exist."""

    def __init__(self, name: str, available: tuple[str, ...]) -> None:
        super().__init__(
            409,
            "AGENT_TOOL_NOT_REGISTERED",
            f"{name!r} is not an available agent tool.",
            {"requested": name, "available": list(available)},
        )


class ToolPermissionError(AppError):
    """A tool was invoked without a permission it declared it needed."""

    def __init__(self, name: str, missing: str) -> None:
        super().__init__(
            409,
            "AGENT_TOOL_PERMISSION_DENIED",
            f"Tool {name!r} may not be invoked without {missing}.",
            {"tool": name, "required_permission": missing},
        )


class ReadContextTool:
    """Read one named slice of the assembled context.

    Exists to make the "the model can see only what the runtime chose to send"
    property explicit and inspectable. Slices are pre-truncated by the context
    builder, so this cannot be used to pull unbounded text into a prompt.
    """

    name = "read_context"
    permissions = frozenset({ToolPermission.READ_CONTEXT})
    description = "Read one named section of the task context that was assembled for you."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        section = str(arguments.get("section", "")).strip()
        if not section:
            return ToolResult.refusal("A section name is required.")
        if section not in context.context_sections:
            available = sorted(context.context_sections)
            return ToolResult.refusal(
                f"Section {section!r} is not in this context. Available: {', '.join(available)}."
            )
        return ToolResult(
            ok=True,
            summary=f"Read context section {section!r}.",
            payload={"section": section, "text": context.context_sections[section]},
        )


class WriteArtifactTool:
    """Draft an artifact for the current task.

    Returns the draft; the runtime is what persists it. A tool never writes to
    the database itself, which keeps persistence and attribution in one place and
    makes every artifact traceable to a run, a task and a decision.

    ``CODE`` is a permitted artifact type. It is stored as text and never run —
    see ``docs/architecture/agent-security.md``.
    """

    name = "write_artifact"
    permissions = frozenset({ToolPermission.WRITE_ARTIFACT})
    description = "Draft an artifact for the current task and return it for the student to review."

    _MAX_CHARS: Final = 20_000

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        title = str(arguments.get("title", "")).strip()
        content = str(arguments.get("content", ""))
        if not title:
            return ToolResult.refusal("An artifact needs a title.")
        if not content.strip():
            return ToolResult.refusal("An artifact needs content.")
        if len(content) > self._MAX_CHARS:
            return ToolResult.refusal(
                f"That draft is {len(content)} characters; the limit is {self._MAX_CHARS}."
            )
        raw_type = str(arguments.get("artifact_type", AgentArtifactType.TEXT.value)).strip()
        try:
            artifact_type = AgentArtifactType(raw_type)
        except ValueError:
            known = ", ".join(t.value for t in AgentArtifactType)
            return ToolResult.refusal(f"{raw_type!r} is not an artifact type. Known: {known}.")
        return ToolResult(
            ok=True,
            summary=f"Drafted {artifact_type.value.lower()} {title!r}.",
            payload={
                "title": title,
                "content": content,
                "artifact_type": artifact_type.value,
                "task_id": str(context.task_id) if context.task_id else None,
                "task_key": context.task_key,
            },
        )


class RequestCheckpointTool:
    """Ask the student a question and stop the run until they answer.

    This is the only way an in-flight step can hand control back, and the runtime
    treats calling it as terminal for the step: the run moves to
    ``WAITING_FOR_USER`` and the question is persisted. There is no path where the
    agent answers its own question and continues.
    """

    name = "request_checkpoint"
    permissions = frozenset({ToolPermission.ASK_USER, ToolPermission.REQUEST_APPROVAL})
    description = (
        "Ask the student a specific question because you cannot proceed without "
        "their answer. This stops the run until they respond."
    )

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        question = str(arguments.get("question", "")).strip()
        if not question:
            return ToolResult.refusal("A checkpoint needs a question.")
        raw_type = str(arguments.get("checkpoint_type", AgentCheckpointType.CLARIFICATION.value))
        try:
            checkpoint_type = AgentCheckpointType(raw_type)
        except ValueError:
            known = ", ".join(t.value for t in AgentCheckpointType)
            return ToolResult.refusal(f"{raw_type!r} is not a checkpoint type. Known: {known}.")
        options = arguments.get("options")
        options_list = [str(o) for o in options] if isinstance(options, list) else None
        if options_list is not None and len(options_list) > 8:
            return ToolResult.refusal("A checkpoint may offer at most 8 options.")
        return ToolResult(
            ok=True,
            summary="Asked the student a question and paused for their answer.",
            payload={
                "question": question,
                "checkpoint_type": checkpoint_type.value,
                "context": str(arguments.get("context", "")).strip() or None,
                "options": options_list,
            },
        )


class ToolRegistry:
    """The complete set of capabilities the runtime has.

    Deliberately a closed registry with no registration API beyond
    :meth:`register`, which refuses forbidden permissions. A future phase that
    genuinely needs a new capability adds it here, in review, rather than
    discovering that it can already be plugged in.
    """

    def __init__(self, tools: tuple[AgentTool, ...] | None = None) -> None:
        builtins: tuple[AgentTool, ...] = (
            ReadContextTool(),
            WriteArtifactTool(),
            RequestCheckpointTool(),
        )
        self._tools: dict[str, AgentTool] = {}
        for tool in tools if tools is not None else builtins:
            self.register(tool)

    def register(self, tool: AgentTool) -> None:
        forbidden = FORBIDDEN_PERMISSIONS & tool.permissions
        if forbidden:
            raise ValueError(
                f"Tool {tool.name!r} declares forbidden permissions: {sorted(forbidden)}"
            )
        self._tools[tool.name] = tool

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def get(self, name: str) -> AgentTool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotRegisteredError(name, self.names())
        return tool

    def assert_permitted(self, name: str, required: str) -> AgentTool:
        """Resolve a tool only if it holds ``required``.

        Split from :meth:`get` so that permission checks cannot be forgotten at a
        call site: resolving and authorising are one operation.
        """
        tool = self.get(name)
        if required not in tool.permissions:
            raise ToolPermissionError(name, required)
        return tool

    def describe(self) -> list[dict[str, Any]]:
        """Machine-readable catalogue for the prompt.

        The model is told what it *can* do, which is a closed list. A prompt that
        describes only available tools is one fewer way for it to invent one.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permissions": sorted(tool.permissions),
            }
            for tool in sorted(self._tools.values(), key=lambda t: t.name)
        ]


#: The process-wide registry. Immutable in practice: nothing in the application
#: mutates it after import, and tests build their own instead of patching this.
DEFAULT_TOOLS: Final = ToolRegistry()


async def invoke_tool(
    name: str,
    arguments: Mapping[str, Any],
    context: ToolContext,
    *,
    registry: ToolRegistry | None = None,
) -> ToolResult:
    """Authorise and run a tool.

    The single entry point. Nothing else calls ``tool.invoke`` directly, so this
    is the one place where "was this permitted, and did we record it" is decided.
    """
    reg = registry or DEFAULT_TOOLS
    tool = reg.get(name)
    return await tool.invoke(arguments, context)


#: Tool argument validation is intentionally shallow: the tools themselves return
#: a refusal for bad arguments rather than raising, because a refusal is a
#: user-safe explanation while an exception is a crash. This alias documents that
#: choice at the call site.
ToolHandler = Callable[[Mapping[str, Any], ToolContext], Awaitable[ToolResult]]
