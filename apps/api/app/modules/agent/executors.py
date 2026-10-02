"""Task executors.

One interface, several strategies. A :class:`TaskExecutor` is handed a task and a
context and returns a result; it does not decide *what* to do next. Keeping those
separate is what makes the decision layer testable in isolation and makes adding
a new kind of academic work an executor rather than a change to the runtime.

The built-ins map a generic ``AcademicTaskType`` onto an executor kind. The
mapping is deliberately coarse — ``PROVE``, ``SOLVE`` and ``CALCULATE`` all reach
a calculation or reasoning executor, ``READ``/``UNDERSTAND`` reach reasoning — so
that adding a new task type in a future phase does not require a new executor.

:class:`CodingWorker` is the Phase 6/7 extension point, and it is defined here as
an interface that *cannot* execute code. It receives text and returns text. A
worker that ran what it produced would need shell access, which the runtime does
not have; keeping the interface text-in/text-out makes that structural rather
than a policy that a later contributor could quietly relax.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from uuid import UUID

from app.models.enums import (
    AcademicTaskType,
    AgentArtifactType,
    AgentExecutionStatus,
    AgentExecutorKind,
    AgentFailureCategory,
)

#: Generic task type -> executor kind. Coarse on purpose: an executor says *how*
#: a kind of work is carried out, and the task's own title, description and
#: acceptance criteria say what the work actually is. Anything absent falls back
#: to REASONING, which is the honest default — an unfamiliar task is a reasoning
#: task until someone says otherwise.
TASK_TYPE_TO_EXECUTOR: Final[dict[str, AgentExecutorKind]] = {
    AcademicTaskType.READ.value: AgentExecutorKind.REASONING,
    AcademicTaskType.UNDERSTAND.value: AgentExecutorKind.REASONING,
    AcademicTaskType.RESEARCH.value: AgentExecutorKind.RESEARCH,
    AcademicTaskType.COLLECT_DATA.value: AgentExecutorKind.RESEARCH,
    AcademicTaskType.ANALYZE.value: AgentExecutorKind.ANALYSIS,
    AcademicTaskType.ANALYZE_DATA.value: AgentExecutorKind.ANALYSIS,
    AcademicTaskType.EXPERIMENT.value: AgentExecutorKind.ANALYSIS,
    AcademicTaskType.REVIEW.value: AgentExecutorKind.ANALYSIS,
    AcademicTaskType.VERIFY.value: AgentExecutorKind.ANALYSIS,
    AcademicTaskType.SOLVE.value: AgentExecutorKind.CALCULATION,
    AcademicTaskType.PROVE.value: AgentExecutorKind.CALCULATION,
    AcademicTaskType.WRITE.value: AgentExecutorKind.WRITING,
    AcademicTaskType.REVISE.value: AgentExecutorKind.WRITING,
    AcademicTaskType.PRESENT.value: AgentExecutorKind.WRITING,
    AcademicTaskType.DESIGN.value: AgentExecutorKind.PLANNING,
    AcademicTaskType.SUBMIT.value: AgentExecutorKind.ARTIFACT,
    AcademicTaskType.PRACTICE.value: AgentExecutorKind.REASONING,
    # IMPLEMENT deliberately resolves to REASONING here. A programming task is
    # executed through the CodingWorker extension point when one is registered;
    # until then it is drafted as text by the generic path, which is the same
    # boundary every other non-code task lives inside.
    AcademicTaskType.IMPLEMENT.value: AgentExecutorKind.REASONING,
    AcademicTaskType.OTHER.value: AgentExecutorKind.REASONING,
}


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """What an executor is handed. Data only — no session, no request, no clock."""

    run_id: UUID
    task_id: UUID
    task_key: str
    task_type: str
    task_title: str
    task_description: str
    acceptance_criteria: tuple[str, ...] = ()
    #: The already-assembled, already-bounded context.
    context: str = ""
    #: Free-form structured input the decision layer produced.
    arguments: Mapping[str, Any] = field(default_factory=dict)
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What an executor produced.

    ``output`` is the artefact-producing body. It never contains internal
    reasoning: executors are instructed to produce results, not deliberations,
    and the prompt says so.
    """

    status: AgentExecutionStatus
    #: User-safe summary of what happened, one sentence.
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    #: Set when ``status`` is a failure. Drives the retry policy.
    failure_category: AgentFailureCategory | None = None
    error_code: str | None = None
    #: Optional structured artifact draft. Persisted as a draft for review.
    artifact: ArtifactDraft | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in {
            AgentExecutionStatus.SUCCESS,
            AgentExecutionStatus.PARTIAL_SUCCESS,
        }


@dataclass(frozen=True, slots=True)
class ArtifactDraft:
    """An artifact an executor proposes. Drafted, never published directly."""

    title: str
    artifact_type: AgentArtifactType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    deliverable_key: str | None = None


class TaskExecutor(Protocol):
    """The strategy interface.

    Implementations must be side-effect-free with respect to the database: they
    return a draft and the runtime decides whether to persist it. That is what
    keeps "the agent produced something" and "the student's record gained
    something" as two separate, auditable events.
    """

    kind: AgentExecutorKind

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Carry out the task. Raise only for unexpected faults; report the rest."""
        ...


class CodingWorker(Protocol):
    """Phase 6/7 extension point for implementation tasks.

    Text in, text out. There is no ``execute``, no ``run_tests`` and no
    ``shell`` member, and adding one would require a capability the runtime does
    not have. A worker may draft code and explain it; it may not run it. If a
    future phase genuinely needs execution, that is a separate, explicitly
    authorised subsystem — not an extension of this protocol.
    """

    name: str

    async def draft(self, specification: str, context: str) -> tuple[str, str]:
        """Return ``(code, explanation)`` for the given specification.

        The contract is that the returned code is a *draft for a human*, which is
        why ``explanation`` is not optional: a student is expected to read it.
        """
        ...


class DeterministicExecutor:
    """The offline executor used by tests, CI and the mock provider.

    Produces a structured, inspectable result from the request alone, with no
    provider call. This is what makes the whole runtime — selection, context,
    decision validation, persistence, retry, recovery — testable without network
    access or credentials, and it is what the mock provider's agent branch drives
    for end-to-end coverage.
    """

    kind: AgentExecutorKind = AgentExecutorKind.MOCK_TOOL

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        body = (
            f"# {request.task_title}\n\n"
            f"Task {request.task_key} ({request.task_type}).\n\n"
            f"{request.task_description.strip()}\n"
        )
        if request.acceptance_criteria:
            body += "\nAcceptance criteria:\n"
            body += "\n".join(f"- {c}" for c in request.acceptance_criteria) + "\n"
        return ExecutionResult(
            status=AgentExecutionStatus.SUCCESS,
            summary=f"Produced a draft for {request.task_key}.",
            output={"task_key": request.task_key, "attempt": request.attempt},
            artifact=ArtifactDraft(
                title=request.task_title,
                artifact_type=artifact_type_for_task(request.task_type),
                content=body,
            ),
        )


def artifact_type_for_task(task_type: str) -> AgentArtifactType:
    """Public alias: which artifact shape a generic task type implies.

    Exposed because the runtime needs the same mapping when a provider produces
    the body, and two copies of this mapping would eventually disagree.
    """
    """Pick an artifact shape from the generic task type.

    A coarse mapping on purpose. The title and description carry the specifics;
    the type only tells the UI how to present the draft.
    """
    if task_type in {AcademicTaskType.PROVE.value}:
        return AgentArtifactType.PROOF_DRAFT
    if task_type in {
        AcademicTaskType.SOLVE.value,
        AcademicTaskType.ANALYZE.value,
        AcademicTaskType.ANALYZE_DATA.value,
    }:
        return AgentArtifactType.SOLUTION
    if task_type in {AcademicTaskType.RESEARCH.value, AcademicTaskType.COLLECT_DATA.value}:
        return AgentArtifactType.RESEARCH_NOTES
    if task_type in {AcademicTaskType.WRITE.value, AcademicTaskType.REVISE.value}:
        return AgentArtifactType.MARKDOWN
    if task_type in {AcademicTaskType.PRESENT.value}:
        return AgentArtifactType.PRESENTATION
    if task_type in {AcademicTaskType.DESIGN.value}:
        return AgentArtifactType.OUTLINE
    if task_type in {AcademicTaskType.IMPLEMENT.value}:
        return AgentArtifactType.CODE
    if task_type in {AcademicTaskType.SUBMIT.value}:
        return AgentArtifactType.DOCUMENT
    return AgentArtifactType.TEXT


class ExecutorRegistry:
    """Resolves an executor kind to a strategy.

    Closed by default. :meth:`register` is the single extension point, and a
    later phase that adds a real research or writing worker registers it here
    without the runtime knowing the difference.
    """

    def __init__(self, executors: Mapping[AgentExecutorKind, TaskExecutor] | None = None) -> None:
        self._executors: dict[AgentExecutorKind, TaskExecutor] = dict(executors or {})
        self._executors.setdefault(AgentExecutorKind.MOCK_TOOL, DeterministicExecutor())

    def register(self, kind: AgentExecutorKind, executor: TaskExecutor) -> None:
        self._executors[kind] = executor

    def get(self, kind: AgentExecutorKind) -> TaskExecutor:
        executor = self._executors.get(kind)
        if executor is None:
            # Falling back is deliberate and recorded: an unknown kind is a plan or
            # configuration problem, and refusing would fail the whole run when the
            # honest answer is "we do not have a specialist, so do it generically".
            executor = DeterministicExecutor()
            self._executors[kind] = executor
        return executor

    def executor_for_task(self, task_type: str) -> AgentExecutorKind:
        return TASK_TYPE_TO_EXECUTOR.get(task_type, AgentExecutorKind.REASONING)

    def kinds(self) -> tuple[AgentExecutorKind, ...]:
        return tuple(sorted(self._executors))


DEFAULT_EXECUTORS: Final = ExecutorRegistry()


def parse_execution_output(raw: str) -> dict[str, Any]:
    """Parse a provider's execution body.

    Providers return text, so this is the seam. A provider that returns prose
    instead of JSON yields an empty result rather than a crash: the caller
    decides whether an empty result is a failure or a legitimate no-op.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
