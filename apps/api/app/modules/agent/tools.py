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
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

from app.core.errors import AppError
from app.models.enums import (
    AgentArtifactType,
    AgentCheckpointType,
    AgentToolAvailability,
    AgentToolCategory,
    AgentToolRisk,
    AgentToolStatus,
)

if TYPE_CHECKING:
    from app.modules.execution.external_agent import ExternalAgent
    from app.modules.execution.gateway import ExecutionGatewayProtocol

#: The highest risk the runtime will dispatch. Tools at this level or below are
#: invocable; anything above is refused by the registry regardless of the
#: permissions it holds. Phase 6 was capped at ``MEDIUM``; Phase 7 raises the
#: ceiling to ``HIGH`` because a sandbox now exists to run untrusted code in. The
#: ceiling is still below ``CRITICAL`` (host filesystem), and raising it was a
#: reviewed change in the phase that shipped the sandbox rather than a grant any
#: tool could obtain by declaring a permission.
MAX_TOOL_RISK: Final = AgentToolRisk.HIGH

#: Ordinal so "at or below the ceiling" is a comparison rather than a set of
#: hard-coded allow-lists that can drift.
_RISK_ORDER: Final[dict[str, int]] = {
    AgentToolRisk.LOW.value: 0,
    AgentToolRisk.MEDIUM.value: 1,
    AgentToolRisk.HIGH.value: 2,
    AgentToolRisk.CRITICAL.value: 3,
}

#: Version reported for a tool that does not declare one. Tools are independently
#: versioned so a behaviour change is visible in review and in the catalogue.
DEFAULT_TOOL_VERSION: Final = "1.0.0"

#: Cap on a tool summary once it reaches the event stream and the UI.
_MAX_SUMMARY_CHARS: Final = 600

#: Gross type checks for the built-in input validator. The validator is shallow on
#: purpose: it catches a malformed request before ``invoke`` and leaves the tool to
#: refuse anything subtler with a message a student can read.
_SCHEMA_TYPE_CHECKS: Final[dict[str, type | tuple[type, ...]]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def tool_version(tool: AgentTool) -> str:
    """The tool's declared version, or the default for a tool that omits one."""
    value = getattr(tool, "version", None)
    return str(value) if value else DEFAULT_TOOL_VERSION


def tool_availability(tool: AgentTool) -> AgentToolAvailability:
    """The tool's declared availability, defaulting to ``AVAILABLE``."""
    value = getattr(tool, "availability", AgentToolAvailability.AVAILABLE)
    return value if isinstance(value, AgentToolAvailability) else AgentToolAvailability.AVAILABLE


def tool_output_schema(tool: AgentTool) -> dict[str, Any] | None:
    schema = getattr(tool, "output_schema", None)
    return schema if isinstance(schema, dict) and schema else None


def validate_arguments(tool: AgentTool, arguments: Mapping[str, Any]) -> list[str]:
    """Check ``arguments`` against the tool's declared input schema.

    Runs *before* ``invoke`` so a malformed request is a bounded refusal rather
    than a crash inside a tool. Required keys must be present and non-empty, and
    declared types must match at the gross level. Anything subtler is the tool's
    own business and is reported with the tool's own words.
    """
    schema = getattr(tool, "arguments_schema", None)
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties") or {}
    problems: list[str] = []
    for name in schema.get("required") or []:
        if name not in arguments or arguments[name] in (None, ""):
            problems.append(f"{name} is required")
    for name, spec in properties.items():
        if name not in arguments or not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        checker = _SCHEMA_TYPE_CHECKS.get(expected) if isinstance(expected, str) else None
        if checker is None:
            continue
        value = arguments[name]
        # bool is an int subclass; an integer/number field must not accept True.
        if expected in {"integer", "number"} and isinstance(value, bool):
            problems.append(f"{name} must be a {expected}")
        elif not isinstance(value, checker):
            problems.append(f"{name} must be a {expected}")
    return problems


def validate_output(tool: AgentTool, result: ToolResult) -> ToolResult:
    """Check a usable result against the tool's output schema, when it declares one.

    A tool that promised a shape and returned a different one is a defect, and it
    is reported as ``FAILED`` with a reason rather than passed downstream where a
    missing key would become a crash somewhere less obvious.
    """
    schema = tool_output_schema(tool)
    if schema is None or not result.structured_status.is_ok:
        return result
    missing = [name for name in schema.get("required") or [] if name not in result.payload]
    if missing:
        return ToolResult.failure(
            f"{tool.name} returned a result missing {', '.join(missing)}."
        )
    return result


def sanitize_result(result: ToolResult) -> ToolResult:
    """Strip control characters and cap the summary before it becomes an event.

    A tool summary becomes a user-facing activity line and a bounded event field.
    Sanitising here means no tool can smuggle a control sequence or an unbounded
    string into either, whatever it returns.
    """
    summary = "".join(ch for ch in result.summary if ch == "\n" or ch >= " ")
    summary = summary.strip()
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[:_MAX_SUMMARY_CHARS].rstrip() + "..."
    if summary == result.summary:
        return result
    return replace(result, summary=summary)


class ToolPermission:
    """What a tool is allowed to do.

    Named rather than boolean so that adding a capability later is a visible
    vocabulary change, and so a grant reads as a sentence.

    Phase 6 adds the four read-only vocabulary entries (``COMPUTE``,
    ``ANALYZE_TEXT``, ``ANALYZE_CODE``, ``EXTRACT_REFERENCES``). They name *what
    kind of deterministic work* a tool does — none of them opens a channel to
    anything outside the run. A tool in the ``CODE`` category still only reads
    text; ``ANALYZE_CODE`` does not mean "run code".
    """

    READ_CONTEXT: Final = "READ_CONTEXT"
    WRITE_ARTIFACT: Final = "WRITE_ARTIFACT"
    ASK_USER: Final = "ASK_USER"
    REQUEST_APPROVAL: Final = "REQUEST_APPROVAL"
    #: Bounded, deterministic computation over data the runtime already holds
    #: (arithmetic, solvers, statistics, number theory).
    COMPUTE: Final = "COMPUTE"
    #: Read-only analysis of text (word counts, readability, structure, keywords).
    ANALYZE_TEXT: Final = "ANALYZE_TEXT"
    #: Read-only, static analysis of code text. Never execution.
    ANALYZE_CODE: Final = "ANALYZE_CODE"
    #: Pattern extraction of citations/references from text.
    EXTRACT_REFERENCES: Final = "EXTRACT_REFERENCES"
    #: Run code, but only inside the Phase 7 isolation plane. Distinct from
    #: ``EXECUTE_UNTRUSTED`` on purpose: this permission means "submit to the
    #: sandbox", which is bounded, observable and revocable, whereas
    #: ``EXECUTE_UNTRUSTED`` would mean "run this on the host" and stays forbidden.
    #: A tool holding this still cannot choose an image, a path or a limit — the
    #: gateway it is handed decides all of that.
    EXECUTE_SANDBOXED: Final = "EXECUTE_SANDBOXED"
    #: Present so a future tool that *would* need it has to be named in review
    #: rather than reaching for an existing capability. Never granted today: it is
    #: the host-execution capability the sandbox exists to make unnecessary.
    EXECUTE_UNTRUSTED: Final = "EXECUTE_UNTRUSTED"
    #: Hand a task to an external coding agent (the ``§19`` seam). Distinct from
    #: ``EXECUTE_SANDBOXED`` because the work leaves this process entirely; it is
    #: granted only so the tool can report "unavailable" cleanly, and the seam it
    #: uses is not available in this build.
    DELEGATE_EXTERNAL_AGENT: Final = "DELEGATE_EXTERNAL_AGENT"


#: Permissions no tool may hold, regardless of what a tool declares. A tool that
#: asks for one of these is a bug, and failing registration surfaces it.
FORBIDDEN_PERMISSIONS: Final[frozenset[str]] = frozenset({ToolPermission.EXECUTE_UNTRUSTED})


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool produced. Always data, never a side effect the caller cannot name.

    The structured ``status`` is the honest answer to "what happened", and it is
    richer than a boolean because the runtime acts differently on each value:
    ``PARTIAL_SUCCESS`` advances with a warning, ``NEEDS_USER_INPUT`` is a request
    for a human rather than a failure, and ``RATE_LIMITED``/``UNAVAILABLE`` are
    retry-later conditions the retry policy can back off from. ``ok`` is kept for
    the common two-way case and is derived from the status so the two cannot
    silently disagree.

    ``artifacts`` names draft payloads the tool produced for the runtime to
    persist; a tool still never writes to the store itself. ``metadata`` is
    user-safe structured detail (sizes, counts, versions) and never raw reasoning.
    """

    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Set when the tool refused or failed. ``reason`` is written for a student.
    reason: str | None = None
    status: AgentToolStatus | None = None
    #: Non-fatal problems that came with an otherwise usable result.
    warnings: tuple[str, ...] = ()
    #: Drafts the runtime should persist, as ``{"title", "artifact_type", "content"}``.
    artifacts: tuple[dict[str, Any], ...] = ()
    #: User-safe structured detail. Never raw model reasoning.
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Deprecated positional-compatible alias; derived from ``status`` when omitted.
    ok: bool = True

    def __post_init__(self) -> None:
        if self.status is None:
            object.__setattr__(
                self, "status", AgentToolStatus.SUCCESS if self.ok else AgentToolStatus.BLOCKED
            )
        else:
            object.__setattr__(self, "ok", self.status.is_ok)

    @property
    def structured_status(self) -> AgentToolStatus:
        assert self.status is not None  # guaranteed by __post_init__
        return self.status

    @classmethod
    def success(
        cls,
        summary: str,
        payload: dict[str, Any] | None = None,
        *,
        warnings: tuple[str, ...] = (),
        artifacts: tuple[dict[str, Any], ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        return cls(
            summary=summary,
            payload=payload or {},
            status=AgentToolStatus.SUCCESS,
            warnings=warnings,
            artifacts=artifacts,
            metadata=metadata or {},
        )

    @classmethod
    def partial(
        cls,
        summary: str,
        payload: dict[str, Any] | None = None,
        *,
        warnings: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """A usable result that came with a caveat the caller must not ignore."""
        return cls(
            summary=summary,
            payload=payload or {},
            status=AgentToolStatus.PARTIAL_SUCCESS,
            warnings=warnings,
            metadata=metadata or {},
        )

    @classmethod
    def refusal(cls, reason: str) -> ToolResult:
        """A safe, user-readable refusal of the arguments. Never a crash."""
        return cls(summary=reason, reason=reason, status=AgentToolStatus.BLOCKED)

    @classmethod
    def failure(
        cls,
        reason: str,
        *,
        status: AgentToolStatus = AgentToolStatus.FAILED,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """A tool-level failure. ``status`` stays within the non-ok vocabulary."""
        if status.is_ok:
            raise ValueError("failure() is for non-success statuses")
        return cls(summary=reason, reason=reason, status=status, metadata=metadata or {})

    @classmethod
    def needs_user_input(cls, reason: str) -> ToolResult:
        return cls(summary=reason, reason=reason, status=AgentToolStatus.NEEDS_USER_INPUT)

    @classmethod
    def rate_limited(cls, reason: str) -> ToolResult:
        return cls(summary=reason, reason=reason, status=AgentToolStatus.RATE_LIMITED)

    @classmethod
    def unavailable(cls, reason: str) -> ToolResult:
        return cls(summary=reason, reason=reason, status=AgentToolStatus.UNAVAILABLE)


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
    #: Bounded bodies of this run's artifacts, keyed by title. The runtime decides
    #: what is here: a tool can read a draft the student already has, and nothing
    #: outside the run — there is no path from a tool to the filesystem.
    artifact_texts: Mapping[str, str] = field(default_factory=dict)
    #: The Phase 7 sandbox gateway, present only when execution is enabled for
    #: this run. It is not a channel to the host: the one method on it submits a
    #: bounded job to an isolated backend. ``None`` means execution tools answer
    #: ``unavailable`` rather than that some other path exists.
    execution: ExecutionGatewayProtocol | None = None
    #: The Phase 7 external coding-agent seam. Present but *unavailable* by default
    #: (no real client is bundled); the delegation tool answers ``unavailable``
    #: unless a deployment has bound an agent that reports ``available``. It cannot
    #: name a host path or a command either — only a bounded task description.
    external_agent: ExternalAgent | None = None


class AgentTool(Protocol):
    """The interface every tool implements.

    Deliberately narrow: name, description, permissions, a JSON-schema-ish
    description and an async invoke. There is no ``run_command`` method on this
    protocol, and adding one would change what the runtime *is*.

    The metadata attributes (``category``, ``deterministic``,
    ``side_effect_free``, ``arguments_schema``) are what the catalogue API and
    the UI render, and what a security review reads first. ``deterministic``
    and ``side_effect_free`` are **declared, not derived**: a tool that mutates
    or reads the outside world has to say so, which forces a review to see it.
    """

    name: str
    description: str
    permissions: frozenset[str]
    category: AgentToolCategory
    #: How dangerous this tool would be with hostile inputs. Enforced by the
    #: registry against :data:`MAX_TOOL_RISK`, not merely reported.
    risk_level: AgentToolRisk
    #: ``True`` when the same arguments always produce the same result.
    deterministic: bool
    #: ``True`` when the tool leaves no trace on anything but its own result.
    side_effect_free: bool
    #: Draft JSON Schema for ``invoke``'s ``arguments``, so the catalogue is
    #: machine-readable without importing the tool.
    arguments_schema: dict[str, Any]

    # ``version``, ``output_schema`` and ``availability`` are part of the
    # abstraction but *optional* on a tool: the registry reads them with
    # ``getattr`` (see :func:`tool_version`, :func:`tool_output_schema`,
    # :func:`tool_availability`) and supplies a safe default. They are deliberately
    # not required attributes here so a simple tool stays terse while a tool that
    # changes behaviour, promises a shape, or is switched off can declare so.

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


class ToolRiskError(AppError):
    """A tool was invoked whose risk exceeds what this runtime will dispatch."""

    def __init__(self, name: str, risk: AgentToolRisk, ceiling: AgentToolRisk) -> None:
        super().__init__(
            409,
            "AGENT_TOOL_RISK_EXCEEDED",
            f"Tool {name!r} is {risk.value} risk; this runtime dispatches at most {ceiling.value}.",
            {"tool": name, "risk": risk.value, "max_risk": ceiling.value},
        )


class ListArtifactsTool:
    """List the artifacts this run has produced so far.

    The read-side counterpart to ``write_artifact`` and the *only* directory a
    tool can list: it is scoped to the current run's artifacts, which the runtime
    already holds. There is no tool that lists a directory, a bucket or a
    database, because no tool is handed anything but this context.
    """

    name = "list_artifacts"
    permissions = frozenset({ToolPermission.READ_CONTEXT})
    category = AgentToolCategory.CORE
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {"type": "object", "properties": {}}
    description = "List the artifacts this run has produced, so you can avoid duplicating one."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        titles = list(context.prior_artifacts)
        return ToolResult(
            ok=True,
            summary=f"This run has {len(titles)} artifact(s).",
            payload={"count": len(titles), "titles": titles},
        )


class ReadArtifactTool:
    """Read the bounded body of an artifact this run already produced.

    Scoped to ``ToolContext.artifact_texts``: the runtime decides which bodies a
    tool can see, and they are capped before they arrive. This can re-read the
    run's own drafts; it cannot reach a student upload that the runtime chose not
    to include, and it cannot read anything else.
    """

    name = "read_artifact"
    permissions = frozenset({ToolPermission.READ_CONTEXT})
    category = AgentToolCategory.CORE
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The exact title of an artifact listed by list_artifacts.",
            }
        },
        "required": ["title"],
    }
    description = "Read the body of an artifact this run already produced, by its title."

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        title = str(arguments.get("title", "")).strip()
        if not title:
            return ToolResult.refusal("An artifact title is required.")
        if title not in context.artifact_texts:
            available = sorted(context.artifact_texts)
            return ToolResult.refusal(
                f"No artifact titled {title!r} in this run. "
                f"Available: {', '.join(available) if available else '(none)'}."
            )
        return ToolResult(
            ok=True,
            summary=f"Read artifact {title!r}.",
            payload={"title": title, "text": context.artifact_texts[title]},
        )


class ReadContextTool:
    """Read one named slice of the assembled context.

    Exists to make the "the model can see only what the runtime chose to send"
    property explicit and inspectable. Slices are pre-truncated by the context
    builder, so this cannot be used to pull unbounded text into a prompt.
    """

    name = "read_context"
    permissions = frozenset({ToolPermission.READ_CONTEXT})
    category = AgentToolCategory.CORE
    risk_level = AgentToolRisk.LOW
    deterministic = True
    side_effect_free = True
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": "The name of a context section assembled for this step.",
            }
        },
        "required": ["section"],
    }
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
    category = AgentToolCategory.CORE
    risk_level = AgentToolRisk.LOW
    deterministic = True
    #: Persists a draft through the runtime, so it is *not* side-effect free for
    #: the student's record. Declared false on purpose: the catalogue should show
    #: which of the tools change the world.
    side_effect_free = False
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short human title for the draft."},
            "content": {"type": "string", "description": "The draft body."},
            "artifact_type": {
                "type": "string",
                "description": "One of the known artifact types, e.g. TEXT, SOLUTION, CODE.",
            },
        },
        "required": ["title", "content"],
    }
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
    category = AgentToolCategory.CORE
    risk_level = AgentToolRisk.LOW
    deterministic = False
    #: Stops the run and opens a checkpoint the student must answer — a genuine
    #: change in the world, not a pure read.
    side_effect_free = False
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The specific question the student must answer.",
            },
            "checkpoint_type": {
                "type": "string",
                "description": "One of CLARIFICATION, APPROVAL, REVIEW, DECISION, "
                "MISSING_INFORMATION, PERMISSION.",
            },
            "context": {"type": "string", "description": "Optional context to help the student."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "At most 8 offered answers.",
            },
        },
        "required": ["question"],
    }
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


def _builtin_tools() -> tuple[AgentTool, ...]:
    """The core tools plus the Phase 6 scientific/domain toolkit.

    Imported lazily so ``domain_tools`` (which imports ``ToolPermission`` and
    ``ToolResult`` from this module) cannot create an import cycle.
    """
    from app.modules.agent.domain_tools import ACADEMIC_TOOLS
    from app.modules.agent.execution_tools import EXECUTION_TOOLS
    from app.modules.agent.external_agent_tools import EXTERNAL_AGENT_TOOLS

    return (
        *ACADEMIC_TOOLS,
        *EXECUTION_TOOLS,
        *EXTERNAL_AGENT_TOOLS,
        ReadContextTool(),
        ListArtifactsTool(),
        ReadArtifactTool(),
        WriteArtifactTool(),
        RequestCheckpointTool(),
    )


class ToolRegistry:
    """The complete set of capabilities the runtime has.

    Deliberately a closed registry with no registration API beyond
    :meth:`register`, which refuses forbidden permissions. A future phase that
    genuinely needs a new capability adds it here, in review, rather than
    discovering that it can already be plugged in.
    """

    def __init__(self, tools: tuple[AgentTool, ...] | None = None) -> None:
        builtins = _builtin_tools()
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

    def require_granted(
        self,
        name: str,
        granted: frozenset[str],
        *,
        max_risk: AgentToolRisk = MAX_TOOL_RISK,
    ) -> AgentTool:
        """Resolve a tool only if it is permitted *and* within the risk ceiling.

        The stronger form of :meth:`assert_permitted` for call sites that grant a
        whole permission set at once (the runtime's default for a run). A tool
        that needs ASK_USER cannot sneak in under a grant that only covers
        READ_CONTEXT: every declared permission must be present.

        The risk ceiling is a second, independent gate. A tool can hold every
        permission it declares and still be refused for being too dangerous: the
        two axes answer different questions ("was this allowed?" and "should this
        exist at all in this phase?"), and enforcing both means a future dangerous
        tool needs a deliberate phase change, not just a permission grant.
        """
        tool = self.get(name)
        missing = tuple(sorted(tool.permissions - granted))
        if missing:
            raise ToolPermissionError(name, ", ".join(missing))
        if _RISK_ORDER[tool.risk_level.value] > _RISK_ORDER[max_risk.value]:
            raise ToolRiskError(name, tool.risk_level, max_risk)
        return tool

    def find_tools(
        self,
        *,
        granted: frozenset[str] | None = None,
        max_risk: AgentToolRisk = MAX_TOOL_RISK,
        categories: frozenset[AgentToolCategory] | None = None,
        tool_ids: frozenset[str] | None = None,
        available_only: bool = True,
    ) -> list[AgentTool]:
        """Discover the tools usable for a task, without executing anything.

        This is the read side of the boundary :func:`invoke_tool` enforces on the
        write side, and the two must agree: a tool returned here is one the same
        runtime would not refuse. Filtering is by permission grant, risk ceiling,
        category and the caller's allow-list (a worker's tool set), and — unless
        ``available_only`` is cleared for an operator view — by deployment
        availability. Nothing here can widen what a tool is permitted to do; it can
        only narrow the visible set.
        """
        granted_set = DEFAULT_GRANTED_PERMISSIONS if granted is None else granted
        found: list[AgentTool] = []
        for tool in self._tools.values():
            if tool_ids is not None and tool.name not in tool_ids:
                continue
            if categories is not None and tool.category not in categories:
                continue
            if available_only and tool_availability(tool) is not AgentToolAvailability.AVAILABLE:
                continue
            if tool.permissions - granted_set:
                continue
            if _RISK_ORDER[tool.risk_level.value] > _RISK_ORDER[max_risk.value]:
                continue
            found.append(tool)
        return sorted(found, key=lambda t: t.name)

    def describe(self, tool_ids: frozenset[str] | None = None) -> list[dict[str, Any]]:
        """Machine-readable catalogue for the prompt.

        The model is told what it *can* do, which is a closed list. A prompt that
        describes only available tools is one fewer way for it to invent one.

        ``tool_ids`` narrows the catalogue to the active worker's tool set, so a
        ``MATHEMATICS`` worker never sees the code-analysis tools in its prompt.
        """
        tools = list(self._tools.values())
        if tool_ids is not None:
            tools = [t for t in tools if t.name in tool_ids]
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permissions": sorted(tool.permissions),
            }
            for tool in sorted(tools, key=lambda t: t.name)
        ]

    def schema(self, name: str) -> dict[str, Any]:
        """Full catalogue entry for one tool (metadata + argument schema)."""
        tool = self.get(name)
        return {
            "id": tool.name,
            "name": tool.name,
            "version": tool_version(tool),
            "category": tool.category.value,
            "description": tool.description,
            "permissions": sorted(tool.permissions),
            "risk_level": tool.risk_level.value,
            "availability": tool_availability(tool).value,
            "deterministic": tool.deterministic,
            "side_effect_free": tool.side_effect_free,
            "arguments_schema": tool.arguments_schema,
            "output_schema": tool_output_schema(tool),
        }

    def describe_schema(self, tool_ids: frozenset[str] | None = None) -> list[dict[str, Any]]:
        """Full catalogue for the API: every weapon in the arsenal, with schemas.

        Unlike :meth:`describe` (the prompt list), this is the whole closed set
        and is served to the UI and the security documentation, so the boundary
        has one published shape.
        """
        tools = list(self._tools.values())
        if tool_ids is not None:
            tools = [t for t in tools if t.name in tool_ids]
        return [self.schema(tool.name) for tool in sorted(tools, key=lambda t: t.name)]


#: The process-wide registry, built once on first use.
#:
#: Built lazily rather than at import time because it is composed from the domain
#: tools, and ``domain_tools`` imports this module. Building it here eagerly would
#: make correctness depend on which module happened to be imported first (import
#: ``domain_tools`` directly and the cycle fails); deferring it to first access
#: means both import orders work. The registry is still write-once in practice:
#: ``_default_tools`` caches the one instance and nothing mutates it.
_DEFAULT_TOOLS: ToolRegistry | None = None


def default_tools() -> ToolRegistry:
    """The process-wide tool registry, constructed on first call."""
    global _DEFAULT_TOOLS
    if _DEFAULT_TOOLS is None:
        _DEFAULT_TOOLS = ToolRegistry()
    return _DEFAULT_TOOLS


def __getattr__(name: str) -> Any:
    """Resolve ``DEFAULT_TOOLS`` lazily so importing this module cannot cycle."""
    if name == "DEFAULT_TOOLS":
        return default_tools()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover - declared for type checkers only
    DEFAULT_TOOLS: ToolRegistry


#: Permissions a fresh run is granted by default. Deliberately excludes
#: ``EXECUTE_UNTRUSTED``, which no run ever receives: a run granting a capability
#: the tool registry itself labels forbidden would make the registry a decoration.
#:
#: The Phase 6 read-only analysis permissions are granted by default because the
#: tools behind them are all deterministic and bounded over data the runtime
#: already holds. They cannot be widened by configuration.
DEFAULT_GRANTED_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        ToolPermission.READ_CONTEXT,
        ToolPermission.WRITE_ARTIFACT,
        ToolPermission.ASK_USER,
        ToolPermission.REQUEST_APPROVAL,
        ToolPermission.COMPUTE,
        ToolPermission.ANALYZE_TEXT,
        ToolPermission.ANALYZE_CODE,
        ToolPermission.EXTRACT_REFERENCES,
        #: Submitting to the sandbox is granted by default *when a gateway is
        #: present*; the tool checks for the gateway and answers ``unavailable``
        #: if execution is off. The grant is the capability, not the channel: it
        #: still cannot name a host path or a resource beyond its profile.
        ToolPermission.EXECUTE_SANDBOXED,
        #: Delegating to an external coding agent is granted for the same reason:
        #: the seam is absent unless a deployment binds one, and the tool answers
        #: ``unavailable`` rather than reaching for a transport.
        ToolPermission.DELEGATE_EXTERNAL_AGENT,
    }
)


async def invoke_tool(
    name: str,
    arguments: Mapping[str, Any],
    context: ToolContext,
    *,
    registry: ToolRegistry | None = None,
    granted: frozenset[str] | None = None,
    max_risk: AgentToolRisk = MAX_TOOL_RISK,
) -> ToolResult:
    """Authorise and run a tool.

    The single entry point. Nothing else calls ``tool.invoke`` directly, so this
    is the one place where "was this permitted, and did we record it" is decided.
    When ``granted`` is supplied, the tool must not declare a single permission
    the caller does not hold — this is how the runtime turns its granted
    permission set into an executable capability boundary. ``max_risk`` is the
    second gate: a tool above it is refused even if fully permitted.
    """
    reg = registry or default_tools()
    granted_set = DEFAULT_GRANTED_PERMISSIONS if granted is None else granted
    tool = reg.require_granted(name, granted_set, max_risk=max_risk)
    if tool_availability(tool) is not AgentToolAvailability.AVAILABLE:
        return ToolResult.unavailable(
            f"{name!r} is not available in this deployment "
            f"({tool_availability(tool).value.lower().replace('_', ' ')})."
        )
    problems = validate_arguments(tool, arguments)
    if problems:
        return ToolResult.refusal("Invalid arguments: " + "; ".join(problems) + ".")
    result = await tool.invoke(arguments, context)
    return sanitize_result(validate_output(tool, result))


#: Tool argument validation is intentionally shallow: the tools themselves return
#: a refusal for bad arguments rather than raising, because a refusal is a
#: user-safe explanation while an exception is a crash. This alias documents that
#: choice at the call site.
ToolHandler = Callable[[Mapping[str, Any], ToolContext], Awaitable[ToolResult]]
