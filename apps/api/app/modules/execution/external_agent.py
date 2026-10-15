"""The external coding-agent seam (``§19``).

Phase 7's sandbox runs *a program the model already wrote*. An external coding
agent is the other shape: the model describes a task and a separate, long-lived
coding assistant works in its own environment and returns a result. That is a
distinct capability from the sandbox, so it gets a distinct seam rather than being
folded into the execution backend.

**The seam is defined here; a real integration is not bundled.** That is the honest
state of things, and the module is written so the honesty is structural rather than
a comment: every implementation must declare ``available`` and, when it is not,
``unavailable_reason``. ``DisabledExternalAgent`` and ``OpenCodeExternalAgent``
both answer ``UNAVAILABLE`` and never run anything. Only ``MockExternalAgent``,
which a test opts into explicitly, ever returns a result.

Two properties match the sandbox:

* **Nothing here can widen itself.** A request carries a task description and
  optional text files, never a command, a path or a URL. The endpoint a real agent
  would be reached at is deployment configuration, not a model argument.
* **A transport is not a trust boundary, and this module does not pretend to be
  one.** If a real client is added, it is a new outbound dependency and must be
  reviewed as such — its own egress policy, credential handling and timeouts. Until
  then, ``available is False`` is the whole of the contract, and the agent tool
  that uses this seam answers "unavailable" rather than reaching for anything.

Nothing in the execution plane depends on this seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from app.core.config import Settings

#: ``COMPLETED``/``FAILED`` are outcomes of an available agent; ``UNAVAILABLE``
#: means no agent answered, which is not a failure of the request.
ExternalAgentStatus = Literal["COMPLETED", "FAILED", "UNAVAILABLE"]

#: Bound on a delegated task description, mirroring the sandbox source bound's
#: intent: large enough for a real brief, small enough that it is not an upload.
MAX_TASK_CHARS = 20_000
MAX_FILE_CHARS = 50_000
MAX_FILES = 20


@dataclass(frozen=True, slots=True)
class ExternalAgentRequest:
    """One task handed to an external coding agent. Text only, bounded."""

    task: str
    files: Mapping[str, str] = field(default_factory=dict)
    language: str | None = None
    timeout_seconds: int = 120


@dataclass(frozen=True, slots=True)
class ExternalAgentResult:
    status: ExternalAgentStatus
    summary: str
    #: A unified diff or replacement text the caller may apply, when the agent
    #: produced one. Never a host path.
    patch: str | None = None
    error_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETED"

    def as_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "patch": self.patch,
            "error_code": self.error_code,
        }


@runtime_checkable
class ExternalAgent(Protocol):
    """The interface every external coding agent implements.

    ``run`` is synchronous, like the sandbox backends: a caller offloads it with
    ``asyncio.to_thread`` so a slow remote never blocks the event loop.
    """

    kind: str

    @property
    def available(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    def run(self, request: ExternalAgentRequest) -> ExternalAgentResult: ...


class DisabledExternalAgent:
    """The default. It is never available and never runs anything."""

    kind = "disabled"

    @property
    def available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return "No external coding agent is configured in this deployment."

    def run(self, request: ExternalAgentRequest) -> ExternalAgentResult:  # noqa: ARG002
        return ExternalAgentResult(
            status="UNAVAILABLE",
            summary=self.unavailable_reason or "No external coding agent is configured.",
            error_code="EXTERNAL_AGENT_DISABLED",
        )


class OpenCodeExternalAgent:
    """A named integration that is not bundled.

    Configuration may name ``opencode`` so the seam is addressable, but without a
    client there is nothing to call, so it reports unavailable rather than
    pretending or silently falling back to the sandbox.
    """

    kind = "opencode"

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    @property
    def available(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return (
            "The OpenCode coding agent is configured but no client is bundled with "
            "this build, so no task can be delegated."
        )

    def run(self, request: ExternalAgentRequest) -> ExternalAgentResult:  # noqa: ARG002
        return ExternalAgentResult(
            status="UNAVAILABLE",
            summary=self.unavailable_reason or "The external coding agent is unavailable.",
            error_code="EXTERNAL_AGENT_UNIMPLEMENTED",
        )


class MockExternalAgent:
    """A deterministic double for tests. Never reaches the network.

    The task text may carry markers to script the outcome, in the same spirit as
    the sandbox mock: ``# @agent:fail`` makes it fail, and ``# @agent:summary=...``
    sets the summary. With no marker it completes with a fixed summary.
    """

    kind = "mock"

    @property
    def available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def run(self, request: ExternalAgentRequest) -> ExternalAgentResult:
        summary = "The external agent completed the delegated task."
        for line in request.task.splitlines():
            stripped = line.strip()
            if stripped.startswith("# @agent:summary="):
                summary = stripped.split("=", 1)[1]
            if stripped == "# @agent:fail":
                return ExternalAgentResult(
                    status="FAILED",
                    summary="The external agent could not complete the task.",
                    error_code="EXTERNAL_AGENT_FAILED",
                )
        return ExternalAgentResult(status="COMPLETED", summary=summary)


def build_external_agent(settings: Settings) -> ExternalAgent:
    """Select the configured external agent. Anything unknown is ``disabled``."""
    kind = settings.execution_external_agent
    if kind == "mock":
        return MockExternalAgent()
    if kind == "opencode":
        return OpenCodeExternalAgent(settings.execution_external_agent_url)
    return DisabledExternalAgent()
