"""Tools that submit work to the Phase 7 sandbox.

These are the only tools in the registry that can cause code to run, and they are
written so that even they cannot choose *where* it runs. Each one names a runtime
and supplies text; the :class:`~app.modules.execution.gateway.ExecutionGateway` it
is handed fixes the workspace, the backend, the image and the resource profile. A
tool that returned an execution type the sandbox does not offer gets a refusal, not
a fallback to something weaker.

Two boundaries are worth stating plainly:

* **A failed program is not a failed tool.** ``exit_code != 0`` comes back as a
  usable result carrying the exit code and the bounded stderr, because a compiler
  error is exactly the signal the agent asked for. Only a job the *sandbox* could
  not run — disabled, unavailable, or failed for an infrastructure reason — is a
  tool failure.
* **No host vocabulary.** The arguments are a runtime name, source text and
  optional stdin. There is no field for a command, an image, an environment
  variable or a path, because the schema is the contract.

When execution is disabled the gateway is absent, and every tool here answers
``unavailable`` rather than pretending it ran something.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from app.models.enums import (
    AgentToolCategory,
    AgentToolRisk,
    ExecutionJobStatus,
    ExecutionType,
)
from app.modules.agent.tools import ToolContext, ToolPermission, ToolResult

#: Runtime-name argument mapped to the sandbox execution type it selects.
_LANGUAGES: Final[dict[str, ExecutionType]] = {
    "python": ExecutionType.PYTHON,
    "java": ExecutionType.JAVA,
    "cpp": ExecutionType.CPP,
    "c++": ExecutionType.CPP,
}

#: Bound on a model-supplied program. Larger than a typical assignment solution
#: and small enough that a prompt cannot be turned into a bulk upload.
_MAX_SOURCE_CHARS: Final = 100_000
_MAX_STDIN_CHARS: Final = 65_536


async def _submit(
    context: ToolContext,
    *,
    execution_type: ExecutionType,
    code: str,
    stdin: str | None,
    entrypoint: str | None = None,
) -> ToolResult:
    """Shared submission path: validate, hand to the gateway, interpret the outcome."""
    if context.execution is None:
        return ToolResult.unavailable(
            "Code execution is not enabled in this deployment, so nothing was run."
        )
    if not code.strip():
        return ToolResult.refusal("There is no code to run.")
    if len(code) > _MAX_SOURCE_CHARS:
        return ToolResult.refusal(
            f"That program is {len(code)} characters; the limit is {_MAX_SOURCE_CHARS}."
        )
    if stdin is not None and len(stdin) > _MAX_STDIN_CHARS:
        return ToolResult.refusal(
            f"That input is {len(stdin)} characters; the limit is {_MAX_STDIN_CHARS}."
        )

    try:
        outcome = await context.execution.run(
            execution_type=execution_type.value,
            code=code,
            entrypoint=entrypoint,
            stdin=stdin,
        )
    except Exception as exc:  # the gateway is a boundary; never leak a raw error
        return ToolResult.failure(f"The execution could not be started ({type(exc).__name__}).")

    if outcome.status == ExecutionJobStatus.REJECTED.value:
        return ToolResult.refusal(
            "The sandbox refused this request under its policy, so nothing was run."
        )
    if outcome.status not in {
        ExecutionJobStatus.SUCCEEDED.value,
        ExecutionJobStatus.FAILED.value,
        ExecutionJobStatus.TIMED_OUT.value,
        ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED.value,
    }:
        return ToolResult.failure(
            f"The execution ended in an unexpected state ({outcome.status})."
        )

    ran_clean = outcome.succeeded
    summary = (
        f"Ran the {execution_type.value.lower()} program; it exited 0 in "
        f"{outcome.duration_ms} ms."
        if ran_clean
        else f"Ran the {execution_type.value.lower()} program; it exited "
        f"{outcome.exit_code} in {outcome.duration_ms} ms."
    )
    payload = outcome.as_payload()
    payload["execution_type"] = execution_type.value
    # A non-zero exit is the program's answer, not the tool's failure: hand it
    # back as a usable-but-caveated result so the model reacts to the compiler or
    # runtime error instead of the runtime treating the step as a dead end.
    if ran_clean:
        return ToolResult.success(
            summary, payload=payload, metadata={"truncated": outcome.truncated}
        )
    return ToolResult.partial(
        summary,
        payload=payload,
        warnings=("The program did not exit successfully.",),
        metadata={"failure_class": outcome.failure_class, "truncated": outcome.truncated},
    )


class ExecuteCodeTool:
    """Run a short program in a named language inside the sandbox."""

    name = "execute_code"
    permissions = frozenset({ToolPermission.EXECUTE_SANDBOXED})
    category = AgentToolCategory.CODING
    risk_level = AgentToolRisk.HIGH
    #: The sandbox gives the same program the same answer, but "same answer" is
    #: the sandbox's guarantee, not this tool's: declared non-deterministic so the
    #: runtime never answers a repeated call from a cache that would hide a rerun.
    deterministic = False
    side_effect_free = False
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "description": "One of: python, java, cpp.",
            },
            "code": {"type": "string", "description": "The complete program source."},
            "stdin": {"type": "string", "description": "Optional standard input."},
        },
        "required": ["language", "code"],
    }
    description = (
        "Run a short program in an isolated sandbox and return its exit code, output "
        "and errors. Use this to check that code you drafted actually works."
    )

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw = str(arguments.get("language", "")).strip().lower()
        execution_type = _LANGUAGES.get(raw)
        if execution_type is None:
            return ToolResult.refusal(
                f"{raw!r} is not a runnable language here. Known: python, java, cpp."
            )
        return await _submit(
            context,
            execution_type=execution_type,
            code=str(arguments.get("code", "")),
            stdin=_optional_str(arguments.get("stdin")),
        )


class RunDataAnalysisTool:
    """Run a Python analysis over supplied input inside the sandbox."""

    name = "run_data_analysis"
    permissions = frozenset({ToolPermission.EXECUTE_SANDBOXED})
    category = AgentToolCategory.DATA
    risk_level = AgentToolRisk.HIGH
    deterministic = False
    side_effect_free = False
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The Python analysis to run."},
            "stdin": {"type": "string", "description": "Optional data piped to standard input."},
        },
        "required": ["code"],
    }
    description = (
        "Run a Python data-analysis script in the sandbox, optionally over data passed "
        "on standard input, and return its output. Use this for computation a written "
        "answer cannot verify."
    )

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        return await _submit(
            context,
            execution_type=ExecutionType.DATA_ANALYSIS,
            code=str(arguments.get("code", "")),
            stdin=_optional_str(arguments.get("stdin")),
        )


class RunTestsTool:
    """Run a test program inside the sandbox and return its result."""

    name = "run_tests"
    permissions = frozenset({ToolPermission.EXECUTE_SANDBOXED})
    category = AgentToolCategory.CODING
    risk_level = AgentToolRisk.HIGH
    deterministic = False
    side_effect_free = False
    arguments_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The test program source."},
            "stdin": {"type": "string", "description": "Optional standard input."},
        },
        "required": ["code"],
    }
    description = (
        "Run a test program in the sandbox and return whether it passed and what it "
        "reported. Use this to verify a solution against the task's requirements."
    )

    async def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        return await _submit(
            context,
            execution_type=ExecutionType.TEST_EXECUTION,
            code=str(arguments.get("code", "")),
            stdin=_optional_str(arguments.get("stdin")),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


#: The execution tools, bound to workers in ``workers.py``.
EXECUTION_TOOLS: Final[tuple[Any, ...]] = (
    ExecuteCodeTool(),
    RunDataAnalysisTool(),
    RunTestsTool(),
)
