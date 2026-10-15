"""Specialized Academic Workers.

A worker is the *tool boundary* a task runs under. The planner's task vocabulary
is deliberately domain-agnostic (``PROVE``, ``WRITE``, ``ANALYZE_DATA`` are plain
strings), so the runtime needs a second layer that says "a proof task may use the
mathematics toolset and nothing else". That layer is this module.

A :class:`SpecializedAcademicWorker` has three responsibilities:

* **Naming the tool set** it may use. ``tool_ids`` is the full boundary: the
  decision layer narrows ``available_tools`` to these names, and the prompt only
  describes them. A ``MATHEMATICS`` worker cannot call ``count_code_lines``, not
  because the call would fail a check somewhere, but because the name is not in
  its bound set — the model is never even told it exists.
* **Naming the task types** it serves. ``academic_task_types`` maps the plan's
  task vocabulary onto the worker. Anything unmapped falls through to
  ``REASONING``, so an unfamiliar task type is served safely rather than not at
  all.
* **Naming what it may produce.** ``output_artifact_types`` constrains the
  drafts the worker's tasks may claim, so a mathematics worker cannot draft a
  ``PRESENTATION`` artifact by mistake.

Workers choose tools; executors choose strategy. The two registries are separate
on purpose: ``executors.executor_for_task`` says *how* work is carried out (a
reasoning path, a calculation path, the deterministic mock), and this module says
*which tool boundary* serves it. Workers are static code, like tools: there is
no configuration option that creates a worker, and none that widens one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.models.enums import (
    AcademicTaskType,
    AgentArtifactType,
    AgentWorkerKind,
)
from app.modules.agent.tools import ToolRegistry

#: The tools every worker may use regardless of specialisation: read the step's
#: context, list and re-read the run's own artifacts, draft an artifact, and hand
#: control to the student. They are the run-scoped file boundary in full — there
#: is no tool here that reaches outside the run.
CORE_TOOLS: Final[tuple[str, ...]] = (
    "read_context",
    "list_artifacts",
    "read_artifact",
    "write_artifact",
    "request_checkpoint",
)


@dataclass(frozen=True, slots=True)
class SpecializedAcademicWorker:
    """One named tool boundary the runtime can field for a task type."""

    kind: AgentWorkerKind
    description: str
    academic_task_types: tuple[str, ...]
    tool_ids: tuple[str, ...]
    output_artifact_types: tuple[AgentArtifactType, ...]
    #: What the worker is *for*, in words a router can match on: the verbs of the
    #: tasks it serves, independent of the concrete tools it happens to use. Kept
    #: separate from ``tool_ids`` so a capability survives a tool being renamed.
    capabilities: tuple[str, ...] = ()
    #: The academic domains this worker is competent in. Two workers may share a
    #: domain (WRITING and RESEARCH both touch prose); a domain is a hint for
    #: routing and for the UI, never an authorisation. Authorisation is ``tool_ids``.
    supported_domains: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """Lowercase id used in UI copy (``mathematics``), distinct from the kind."""
        return self.kind.value.lower()

    def allows_tool(self, tool_name: str) -> bool:
        return tool_name in self.tool_ids

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.kind.value,
            "name": self.name,
            "description": self.description,
            "academic_task_types": list(self.academic_task_types),
            "tools": list(self.tool_ids),
            "capabilities": list(self.capabilities),
            "supported_domains": list(self.supported_domains),
            "output_artifact_types": [t.value for t in self.output_artifact_types],
        }


def _worker(
    kind: AgentWorkerKind,
    description: str,
    types: tuple[str, ...],
    tools: tuple[str, ...],
    artifacts: tuple[AgentArtifactType, ...],
    capabilities: tuple[str, ...],
    domains: tuple[str, ...],
) -> SpecializedAcademicWorker:
    return SpecializedAcademicWorker(
        kind=kind,
        description=description,
        academic_task_types=types,
        tool_ids=CORE_TOOLS + tools,
        output_artifact_types=artifacts,
        capabilities=capabilities,
        supported_domains=domains,
    )


#: The closed set of workers. Adding one here is the Phase 6 way to extend the
#: runtime; nothing outside this tuple can become a worker.
DEFAULT_WORKERS: Final[tuple[SpecializedAcademicWorker, ...]] = (
    _worker(
        AgentWorkerKind.MATHEMATICS,
        "Proves and solves: exact computation over expressions, systems, primes and divisibility.",
        (AcademicTaskType.PROVE.value, AcademicTaskType.SOLVE.value),
        ("calculate", "solve_linear_system", "prime_factorize", "gcd_lcm"),
        (AgentArtifactType.PROOF_DRAFT, AgentArtifactType.SOLUTION, AgentArtifactType.CALCULATION),
        ("exact_computation", "proof_support", "number_theory"),
        ("mathematics", "number_theory"),
    ),
    _worker(
        AgentWorkerKind.DATA,
        "Analyses data: summary statistics, IQR outliers, regression and dataset profiling.",
        (
            AcademicTaskType.ANALYZE_DATA.value,
            AcademicTaskType.EXPERIMENT.value,
            AcademicTaskType.COLLECT_DATA.value,
        ),
        (
            "compute_statistics",
            "detect_outliers",
            "linear_regression",
            "profile_dataset",
            "detect_missing_values",
            "run_data_analysis",
        ),
        (AgentArtifactType.TEXT, AgentArtifactType.MARKDOWN, AgentArtifactType.OUTLINE),
        ("descriptive_statistics", "outlier_detection", "regression", "dataset_profiling"),
        ("data_analysis", "statistics", "experimental_science"),
    ),
    _worker(
        AgentWorkerKind.WRITING,
        "Drafts prose: length, readability, structure and outline analysis over text.",
        (AcademicTaskType.WRITE.value, AcademicTaskType.REVISE.value),
        (
            "count_words",
            "readability_score",
            "assess_structure",
            "top_keywords",
            "suggest_outline",
        ),
        (AgentArtifactType.TEXT, AgentArtifactType.MARKDOWN, AgentArtifactType.RESEARCH_NOTES),
        ("readability_analysis", "structure_analysis", "keyword_extraction", "outline_generation"),
        ("writing", "composition"),
    ),
    _worker(
        AgentWorkerKind.RESEARCH,
        "Reads and researches: keyword extraction, citations and document analysis.",
        (AcademicTaskType.READ.value, AcademicTaskType.RESEARCH.value),
        (
            "top_keywords",
            "extract_citations",
            "count_words",
            "extract_document_metadata",
            "segment_document",
            "search_document",
            "summarize_document",
            "format_citation",
        ),
        (AgentArtifactType.RESEARCH_NOTES, AgentArtifactType.TEXT, AgentArtifactType.DOCUMENT),
        ("citation_extraction", "document_analysis", "summarization", "information_retrieval"),
        ("research", "literature_review"),
    ),
    _worker(
        AgentWorkerKind.PRESENTATION,
        "Shapes presentations: word counts, structure coverage, keywords and slide outlines.",
        (AcademicTaskType.PRESENT.value,),
        ("count_words", "assess_structure", "top_keywords", "build_slide_outline"),
        (AgentArtifactType.PRESENTATION, AgentArtifactType.OUTLINE),
        ("slide_outlining", "narrative_structure"),
        ("presentation", "communication"),
    ),
    _worker(
        AgentWorkerKind.CODE,
        "Reads code: line counts, identifiers, delimiter balance and complexity signals.",
        (AcademicTaskType.IMPLEMENT.value, AcademicTaskType.VERIFY.value),
        (
            "count_code_lines",
            "extract_code_identifiers",
            "check_syntax_balance",
            "execute_code",
            "run_tests",
            "delegate_to_coding_agent",
        ),
        (AgentArtifactType.CODE,),
        (
            "code_metrics",
            "identifier_extraction",
            "syntax_balance",
            "sandboxed_execution",
            "external_coding_agent",
        ),
        ("programming", "software_engineering"),
    ),
    _worker(
        AgentWorkerKind.REASONING,
        "General academic reasoning, analysis and reflection. The default worker "
        "for any task type without a dedicated specialist.",
        (
            AcademicTaskType.UNDERSTAND.value,
            AcademicTaskType.ANALYZE.value,
            AcademicTaskType.DESIGN.value,
            AcademicTaskType.REVIEW.value,
            AcademicTaskType.PRACTICE.value,
            AcademicTaskType.SUBMIT.value,
            AcademicTaskType.OTHER.value,
        ),
        (),
        (AgentArtifactType.TEXT, AgentArtifactType.MARKDOWN, AgentArtifactType.OUTLINE),
        ("general_analysis", "reflection", "drafting"),
        ("general_academics",),
    ),
)


class WorkerAlreadyRegistered(ValueError):
    pass


class WorkerRegistry:
    """Maps a plan task type onto the worker that serves it.

    Closed by default: with no workers supplied it fields exactly
    :data:`DEFAULT_WORKERS`, and :meth:`register` refuses duplicate kinds. The
    runtime never creates a worker at runtime, matching the tools registry's
    refusal to grow by accident.
    """

    def __init__(self, workers: tuple[SpecializedAcademicWorker, ...] | None = None) -> None:
        self._workers: dict[AgentWorkerKind, SpecializedAcademicWorker] = {}
        for worker in workers if workers is not None else DEFAULT_WORKERS:
            self.register(worker)

    def register(self, worker: SpecializedAcademicWorker) -> None:
        if worker.kind in self._workers:
            raise WorkerAlreadyRegistered(worker.kind)
        self._workers[worker.kind] = worker

    def get(self, kind: AgentWorkerKind) -> SpecializedAcademicWorker:
        return self._workers[kind]

    def all(self) -> tuple[SpecializedAcademicWorker, ...]:
        return tuple(worker for worker in self._workers.values())

    def worker_for_task(self, task_type: str) -> SpecializedAcademicWorker:
        """The worker bound to ``task_type``, or ``REASONING`` as the fallback.

        The fallback is not a surprise toolset: the reasoning worker holds only
        the core tools, so an unmapped task type degrades to the narrowest
        boundary rather than to everything.
        """
        for worker in self._workers.values():
            if task_type in worker.academic_task_types:
                return worker
        return self._workers[AgentWorkerKind.REASONING]

    def describe(self) -> list[dict[str, Any]]:
        return [
            worker.as_dict()
            for worker in sorted(self._workers.values(), key=lambda w: w.kind.value)
        ]

    def validate(self, registry: ToolRegistry) -> list[str]:
        """Structural checks a security review wants as tests, not vibes.

        Returns a list of human-readable problems; an empty list means the
        worker set is coherent. Checks that every worker names registered tools,
        that every registered tool is reachable by at least one worker (a tool
        no worker may call is dead catalogue), and that the individually-listed
        task types are all genuinely assigned to exactly one worker.
        """
        problems: list[str] = []
        available = registry.names()
        for worker in self._workers.values():
            unknown = [tool for tool in worker.tool_ids if tool not in available]
            if unknown:
                problems.append(
                    f"worker {worker.kind.value} names unregistered tools: {sorted(unknown)}"
                )
        reachable = {tool for worker in self._workers.values() for tool in worker.tool_ids}
        unused = [tool for tool in sorted(available) if tool not in reachable]
        if unused:
            problems.append(f"registered tools no worker may call: {unused}")
        assigned: dict[str, str] = {}
        for worker in self._workers.values():
            for task_type in worker.academic_task_types:
                if task_type in assigned:
                    problems.append(f"task type {task_type!r} is bound to two workers")
                assigned[task_type] = worker.kind.value
        return problems


#: The process-wide registry. Immutable in practice: nothing mutates it after
#: import, and tests build their own instead of patching this.
DEFAULT_WORKER_REGISTRY: Final = WorkerRegistry()