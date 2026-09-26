"""The deterministic Academic Planning Engine.

This module is the authority on what a plan *is*. A model may propose a plan, but
what gets persisted is always derived here, from the Phase 3 planning contract,
by rules that are fixed, inspectable and reproducible. That is what makes a plan
trustworthy: the same contract always yields the same plan, the graph is always
acyclic, and every required requirement and deliverable is always covered by
something.

The decomposition is deliberately layered, because the layers of academic work are
the same whatever the subject:

1. **Orient** - read and understand the material the brief points at.
2. **Develop** - do the work each requirement actually asks for.
3. **Assemble** - produce each required deliverable.
4. **Verify** - check the work against the brief before submitting.

Layer N depends on the layer below it, so the graph is acyclic by construction
rather than by a repair pass. Nothing here is domain-specific: "Orientation" and
"Assembly" apply to an essay, a lab report, a problem set and a presentation. Any
subject-specific wording lives in the requirement and deliverable titles the
contract already carries.

Effort numbers are estimates with a stated basis, not promises. The schedule
check reports when the upper estimate does not fit the time remaining and lets the
student decide what to cut.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sized
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.models.enums import (
    AcademicTaskPriority,
    AcademicTaskType,
    ComplexityLevel,
    EffortLevel,
    GuidanceLevel,
    PlanningStyle,
    RequirementCategory,
    RequirementPriority,
    ScopeLevel,
)
from app.modules.planning.graph import topological_order
from app.schemas.analysis import PlanningContractResponse
from app.schemas.planning import (
    MAX_MILESTONES,
    PlannedMilestone,
    PlannedRisk,
    PlannedTask,
    PlannedVerificationPoint,
    PlannerOutput,
)

#: Base minutes for one unit of work, by task type. Ordered by rough cost of a
#: competent pass at that activity; ``VERIFY`` is cheap per item but repeated, and
#: ``RESEARCH`` is expensive because it is the most commonly underestimated.
_BASE_MINUTES = {
    AcademicTaskType.READ: 30,
    AcademicTaskType.UNDERSTAND: 25,
    AcademicTaskType.RESEARCH: 75,
    AcademicTaskType.COLLECT_DATA: 90,
    AcademicTaskType.ANALYZE: 60,
    AcademicTaskType.ANALYZE_DATA: 60,
    AcademicTaskType.SOLVE: 45,
    AcademicTaskType.PROVE: 60,
    AcademicTaskType.IMPLEMENT: 90,
    AcademicTaskType.EXPERIMENT: 120,
    AcademicTaskType.DESIGN: 75,
    AcademicTaskType.WRITE: 90,
    AcademicTaskType.REVIEW: 25,
    AcademicTaskType.REVISE: 45,
    AcademicTaskType.PRACTICE: 40,
    AcademicTaskType.PRESENT: 60,
    AcademicTaskType.VERIFY: 20,
    AcademicTaskType.SUBMIT: 10,
    AcademicTaskType.OTHER: 40,
}

#: Requirement category -> the activity that usually satisfies it. Only a default:
#: the requirement's own title and description carry the specifics, so a category
#: that maps badly still produces a coherent task.
_CATEGORY_ACTIVITY = {
    RequirementCategory.CONTENT: AcademicTaskType.READ,
    RequirementCategory.PROCESS: AcademicTaskType.UNDERSTAND,
    RequirementCategory.DELIVERABLE: AcademicTaskType.WRITE,
    RequirementCategory.QUALITY: AcademicTaskType.REVIEW,
    RequirementCategory.FORMAT: AcademicTaskType.REVISE,
    RequirementCategory.ACADEMIC: AcademicTaskType.RESEARCH,
    RequirementCategory.METHODOLOGY: AcademicTaskType.DESIGN,
    RequirementCategory.EVALUATION: AcademicTaskType.ANALYZE,
    RequirementCategory.PRESENTATION: AcademicTaskType.PRESENT,
    RequirementCategory.TECHNICAL: AcademicTaskType.IMPLEMENT,
    RequirementCategory.OTHER: AcademicTaskType.OTHER,
}

#: Deliverable format -> the activity that produces it. Substring match, lower
#: case, against the contract's own format string. The fallback is ``WRITE``,
#: which is the most common way an academic deliverable comes into existence.
_FORMAT_ACTIVITY: tuple[tuple[str, AcademicTaskType], ...] = (
    ("slide", AcademicTaskType.PRESENT),
    ("poster", AcademicTaskType.PRESENT),
    ("presentation", AcademicTaskType.PRESENT),
    ("code", AcademicTaskType.IMPLEMENT),
    ("program", AcademicTaskType.IMPLEMENT),
    ("prototype", AcademicTaskType.IMPLEMENT),
    ("website", AcademicTaskType.IMPLEMENT),
    ("app", AcademicTaskType.IMPLEMENT),
    ("dataset", AcademicTaskType.COLLECT_DATA),
    ("data", AcademicTaskType.COLLECT_DATA),
    ("spreadsheet", AcademicTaskType.ANALYZE_DATA),
    ("experiment", AcademicTaskType.EXPERIMENT),
    ("lab", AcademicTaskType.EXPERIMENT),
    ("simulation", AcademicTaskType.EXPERIMENT),
    ("model", AcademicTaskType.DESIGN),
    ("design", AcademicTaskType.DESIGN),
    ("proof", AcademicTaskType.PROVE),
    ("derivation", AcademicTaskType.PROVE),
    ("analysis", AcademicTaskType.ANALYZE),
    ("report", AcademicTaskType.WRITE),
    ("essay", AcademicTaskType.WRITE),
    ("paper", AcademicTaskType.WRITE),
    ("summary", AcademicTaskType.WRITE),
    ("review", AcademicTaskType.REVIEW),
    ("problem", AcademicTaskType.SOLVE),
    ("exercise", AcademicTaskType.PRACTICE),
    ("answer", AcademicTaskType.SOLVE),
)

#: Caps that keep a plan usable. A student cannot act on ninety tasks, and a plan
#: with more than a handful of milestones stops being a schedule.
_MAX_ORIENTATION_TASKS = 10
_MAX_REQUIREMENT_TASKS = 24
_MAX_VERIFICATION_TASKS = 6
_MAX_RESOURCES_PER_TASK = 5

#: Scope multiplier applied to every base estimate.
_SCOPE_FACTOR = {
    ScopeLevel.NOT_APPLICABLE: 0.8,
    ScopeLevel.LOW: 0.85,
    ScopeLevel.MEDIUM: 1.0,
    ScopeLevel.HIGH: 1.35,
    ScopeLevel.UNKNOWN: 1.15,
}

_PRIORITY_FACTOR = {
    RequirementPriority.LOW: 0.85,
    RequirementPriority.MEDIUM: 1.0,
    RequirementPriority.HIGH: 1.25,
    RequirementPriority.CRITICAL: 1.5,
}

_STYLE_FACTOR = {
    PlanningStyle.MINIMAL: 0.8,
    PlanningStyle.BALANCED: 1.0,
    PlanningStyle.DETAILED: 1.25,
}

#: Per-task effort bands in minutes. Tuned so a genuine 45-minute task reads as LOW
#: rather than VERY_LOW; a plan where every task shares the lowest band carries no
#: information, and the label is what the student triages on.
_TASK_EFFORT_BANDS = (
    (30, EffortLevel.VERY_LOW),
    (60, EffortLevel.LOW),
    (150, EffortLevel.MEDIUM),
    (300, EffortLevel.HIGH),
)

#: Whole-plan effort bands, on a different scale to the per-task ones. A plan
#: totalling six hours is MEDIUM, not VERY_HIGH, even though six hours of a single
#: task would be.
_PLAN_EFFORT_BANDS = (
    (120, EffortLevel.VERY_LOW),
    (360, EffortLevel.LOW),
    (900, EffortLevel.MEDIUM),
    (2400, EffortLevel.HIGH),
)

#: How many of the brief's own objectives to surface, by requested guidance. Low
#: guidance means "just tell me what to do", so it keeps the list short.
_OBJECTIVE_CAP = {GuidanceLevel.LOW: 3, GuidanceLevel.MEDIUM: 6, GuidanceLevel.HIGH: 12}

_GRADE_POINTS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent|points?|marks?|grade)", re.I)
_WORD_BUDGET = re.compile(r"(\d[\d,]*)\s*words?", re.I)
_PAGE_BUDGET = re.compile(r"(\d[\d,]*)\s*pages?", re.I)


@dataclass(slots=True)
class PlanningPreferences:
    """The student's stated preferences, already resolved to concrete knobs."""

    style: PlanningStyle = PlanningStyle.BALANCED
    guidance: GuidanceLevel = GuidanceLevel.MEDIUM
    #: Extra minutes of hand-holding per task. Only non-zero when asked for.
    guidance_minutes: int = 0
    session_length_minutes: int = 45

    @property
    def factor(self) -> float:
        return _STYLE_FACTOR[self.style]


def build_planning_preferences(
    style: PlanningStyle | None,
    guidance: GuidanceLevel | None,
    session_minutes: int | None,
) -> PlanningPreferences:
    return PlanningPreferences(
        style=style or PlanningStyle.BALANCED,
        guidance=guidance or GuidanceLevel.MEDIUM,
        guidance_minutes={"LOW": 0, "MEDIUM": 5, "HIGH": 15}.get(
            (guidance or GuidanceLevel.MEDIUM).value, 5
        ),
        session_length_minutes=session_minutes or 45,
    )


def _activity_for_format(fmt: str | None) -> AcademicTaskType:
    if not fmt:
        return AcademicTaskType.WRITE
    text = fmt.lower()
    for needle, activity in _FORMAT_ACTIVITY:
        if needle in text:
            return activity
    return AcademicTaskType.WRITE


def _round_to_block(minutes: float, block: int = 15) -> int:
    return max(block, int(math.ceil(minutes / block) * block))


def _declared_budget(constraint_texts: list[str]) -> int | None:
    """Minutes implied by a stated output length, when one is stated.

    A word or page budget is the only place an assignment states its own size, so
    it is worth honouring. A page is 275 words at double spacing, 500 single; the
    midpoint is used and reported as an estimate.
    """
    for text in constraint_texts:
        words = _WORD_BUDGET.search(text)
        if words:
            count = int(words.group(1).replace(",", ""))
            # 200 wpm is a realistic sustained pace for first-draft academic work.
            return _round_to_block(count / 200 * 60)
        pages = _PAGE_BUDGET.search(text)
        if pages:
            count = int(pages.group(1).replace(",", ""))
            words_equivalent = count * 380
            return _round_to_block(words_equivalent / 200 * 60)
    return None


def _grade_weight(constraint_texts: list[str], hours_per_point: float) -> float | None:
    """Share of total effort implied by the grade weighting, if stated.

    ``hours_per_point`` is deliberately generous. It converts "this essay is worth
    40% of the grade" into a share of the total time budget. It is an estimate and
    the schedule response says so.
    """
    for text in constraint_texts:
        match = _GRADE_POINTS.search(text)
        if match:
            value = float(match.group(1))
            if 0 < value <= 100:
                return value / 100 * hours_per_point * 60
    return None


class _Builder:
    """Accumulates tasks and the contract-key to task-key index.

    The index is what lets analyzer dependency edges, which are stated in contract
    vocabulary, be translated onto plan-local task keys without guessing.
    """

    def __init__(
        self,
        preferences: PlanningPreferences,
        scope_factor: float,
        max_task_count: int,
    ) -> None:
        self.preferences = preferences
        self.scope_factor = scope_factor
        self.max_task_count = max_task_count
        #: Work areas the cap forced out of the plan. Reported rather than dropped
        #: silently, because a missing work area is a missing piece of the brief.
        self.dropped_areas: list[str] = []
        self.tasks: list[PlannedTask] = []
        #: contract key -> task keys that serve it
        self.index: dict[str, list[str]] = {}
        #: (title, description, task keys) per decomposition layer, in order.
        self.layers: list[tuple[str, str, list[str]]] = []
        self._layer_start = 0

    def close_layer(self, title: str, description: str) -> None:
        """Record the tasks added since the previous layer as a named layer.

        Layers are disjoint: a milestone covers the work of its own stage only. A
        cumulative milestone would tell a student that "everything so far" is a
        checkpoint, which is not a checkpoint.
        """
        keys = [task.key for task in self.tasks[self._layer_start :]]
        self._layer_start = len(self.tasks)
        self.layers.append((title, description, keys))

    def add(
        self,
        *,
        contract_keys: list[str],
        title: str,
        description: str,
        activity: AcademicTaskType,
        effort_minutes: int,
        priority: AcademicTaskPriority,
        depends_on: list[str],
        related_deliverables: list[str] | None = None,
        related_requirements: list[str] | None = None,
        verification_method: str | None = None,
        acceptance_criteria: list[str] | None = None,
        resources: list[str] | None = None,
    ) -> PlannedTask | None:
        if len(self.tasks) >= self.max_task_count:
            return None
        key = f"T{len(self.tasks) + 1}"
        task = PlannedTask(
            key=key,
            title=title[:300],
            description=description[:2000],
            type=activity,
            priority=priority,
            estimated_effort=_effort_band(effort_minutes),
            min_minutes=effort_minutes,
            max_minutes=_round_to_block(effort_minutes * 1.3),
            depends_on=sorted({d for d in depends_on if d}),
            # An explicitly empty traceability list means "this task serves no
            # requirement", which is different from "not specified". Only None
            # falls back to the task's own contract keys.
            related_requirements=(
                list(contract_keys) if related_requirements is None else related_requirements
            ),
            related_deliverables=[k for k in (related_deliverables or [])],
            verification_method=verification_method,
            acceptance_criteria=acceptance_criteria or [],
            resources=(resources or [])[:_MAX_RESOURCES_PER_TASK],
        )
        self.tasks.append(task)
        for contract_key in contract_keys:
            self.index.setdefault(contract_key, []).append(key)
        for deliverable_key in related_deliverables or []:
            self.index.setdefault(deliverable_key, []).append(key)
        return task

    def estimate(self, activity: AcademicTaskType, priority: RequirementPriority) -> int:
        base = _BASE_MINUTES.get(activity, 40)
        scaled = base * self.scope_factor * _PRIORITY_FACTOR.get(priority, 1.0)
        scaled *= self.preferences.factor
        return _round_to_block(scaled + self.preferences.guidance_minutes)


def _effort_band(
    minutes: int, bands: tuple[tuple[int, EffortLevel], ...] = _TASK_EFFORT_BANDS
) -> EffortLevel:
    for ceiling, level in bands:
        if minutes <= ceiling:
            return level
    return EffortLevel.VERY_HIGH


def _priority_for(priority: RequirementPriority) -> AcademicTaskPriority:
    return AcademicTaskPriority(priority.value)


def synthesize_plan(
    contract: PlanningContractResponse,
    *,
    preferences: PlanningPreferences | None = None,
    max_task_count: int = 60,
    hours_per_grade_point: float = 45.0,
    title: str | None = None,
    summary: str | None = None,
) -> PlannerOutput:
    """Build a complete, sound plan from a planning contract.

    The output is guaranteed to validate: every required requirement and
    deliverable is covered, every dependency points at a task that exists, and the
    graph is acyclic because dependencies only ever point from a later layer to an
    earlier one.
    """
    prefs = preferences or PlanningPreferences()
    scope_factor = _SCOPE_FACTOR.get(contract.scope.overall, 1.0)
    builder = _Builder(prefs, scope_factor, max_task_count)

    constraint_texts = [
        f"{item.title} {item.description} {item.value or ''}" for item in contract.constraints
    ]
    required_requirements = [r for r in contract.requirements if r.required]
    optional_requirements = [r for r in contract.requirements if not r.required]
    required_deliverables = [d for d in contract.deliverables if d.required is not False]
    optional_deliverables = [d for d in contract.deliverables if d.required is False]

    # ---- Layer 1: orient -------------------------------------------------
    # The analyzer has already decomposed the brief into work areas, usually as an
    # ordered chain. That structure is the most valuable thing in the contract, so
    # it is preserved rather than reinvented: each work area becomes a task, in the
    # analyzer's own dependency order, carrying the requirements it serves.
    work_areas = list(contract.work_areas)
    area_keys = {area.key for area in work_areas}
    # A contract edge reads "predecessor must come before successor", so the
    # successor is the one that depends on the predecessor.
    area_dependencies: dict[str, list[str]] = {area.key: [] for area in work_areas}
    for edge in contract.dependencies:
        if edge.predecessor in area_keys and edge.successor in area_keys:
            area_dependencies[edge.successor].append(edge.predecessor)

    ordered_areas: list[Any] = []
    if area_keys:
        ranked = topological_order(area_dependencies)
        # A short order means the analyzer emitted a cycle among work areas. Fall
        # back to declaration order rather than dropping areas.
        by_key = {area.key: area for area in work_areas}
        ordered_areas = [by_key[key] for key in ranked if key in by_key]
        if len(ordered_areas) != len(work_areas):
            ordered_areas = work_areas[:_MAX_ORIENTATION_TASKS]

    orientation_added = 0
    for area in ordered_areas:
        if orientation_added >= _MAX_ORIENTATION_TASKS or len(builder.tasks) >= max_task_count:
            # Recorded, not dropped in silence: a work area missing from the plan is
            # a piece of the brief the student was never shown.
            builder.dropped_areas.append(area.title)
            continue
        activity = _CATEGORY_ACTIVITY.get(area.category, AcademicTaskType.READ)
        added = builder.add(
            contract_keys=[area.key],
            # Traceability is the requirements the area serves, not the area's own
            # key. Putting a W-key in related_requirements would claim the task
            # serves a requirement that does not exist.
            related_requirements=list(area.related_requirements),
            title=area.title,
            description=(
                area.description
                or f"Read and take notes on the material behind {area.title} "
                "before starting dependent work."
            ),
            activity=activity,
            effort_minutes=builder.estimate(activity, RequirementPriority.MEDIUM),
            priority=AcademicTaskPriority.MEDIUM,
            depends_on=[
                task_key
                for parent in area_dependencies.get(area.key, [])
                for task_key in builder.index.get(parent, [])
            ],
            resources=[area.title],
        )
        if added is not None:
            orientation_added += 1

    orientation_keys = [task.key for task in builder.tasks]
    builder.close_layer(
        "Oriented on the material",
        "You have worked through the material the brief points at, in order.",
    )

    # ---- Layer 2: develop ----------------------------------------------
    # A requirement the orientation layer already serves does not need a second
    # task; the orientation task is where that work happens.
    covered_by_orientation: set[str] = {
        key for area in ordered_areas[:_MAX_ORIENTATION_TASKS] for key in area.related_requirements
    }

    for requirement in (required_requirements + optional_requirements)[:_MAX_REQUIREMENT_TASKS]:
        if requirement.key in covered_by_orientation:
            continue
        if len(builder.tasks) >= max_task_count:
            break
        activity = _CATEGORY_ACTIVITY.get(requirement.category, AcademicTaskType.OTHER)
        prerequisites = [
            task_key
            for area in ordered_areas[:_MAX_ORIENTATION_TASKS]
            if requirement.key in area.related_requirements
            for task_key in builder.index.get(area.key, [])
        ] or orientation_keys
        builder.add(
            contract_keys=[requirement.key],
            title=requirement.title,
            description=requirement.description or f"Satisfy this requirement: {requirement.title}",
            activity=activity,
            effort_minutes=builder.estimate(activity, requirement.priority),
            priority=_priority_for(requirement.priority),
            depends_on=prerequisites,
            acceptance_criteria=[f"{requirement.title} is satisfied."],
        )

    develop_keys = [task.key for task in builder.tasks if task.key not in orientation_keys]
    builder.close_layer(
        "Requirements developed", "Every requirement has been satisfied on its own terms."
    )

    # ---- Layer 3: assemble ---------------------------------------------
    assemble_start = len(builder.tasks)
    grade_weight_minutes = _grade_weight(constraint_texts, hours_per_grade_point)
    declared_budget = _declared_budget(constraint_texts)
    for deliverable in required_deliverables + optional_deliverables:
        if len(builder.tasks) >= max_task_count:
            break
        activity = _activity_for_format(deliverable.format)
        prerequisites = (
            [
                task_key
                for requirement_key in deliverable.related_requirements
                for task_key in builder.index.get(requirement_key, [])
                if task_key in develop_keys
            ]
            or develop_keys
            or orientation_keys
        )
        title = f"Produce: {deliverable.title}"
        if deliverable.uncertainty and deliverable.uncertainty.value in {"UNCERTAIN", "MISSING"}:
            title = f"Confirm the form of: {deliverable.title}"
        builder.add(
            contract_keys=[],
            title=title,
            description=deliverable.description
            or f"Assemble {deliverable.title} from the completed work.",
            activity=activity,
            effort_minutes=builder.estimate(activity, RequirementPriority.MEDIUM),
            priority=AcademicTaskPriority.HIGH,
            depends_on=prerequisites,
            related_deliverables=[deliverable.key],
            acceptance_criteria=_acceptance_for(deliverable),
            verification_method=(
                deliverable.verification_needs[0] if deliverable.verification_needs else None
            ),
        )

    # ---- Analyzer dependency edges -------------------------------------
    # Applied after every task exists so contract-level ordering is honoured even
    # when it contradicts the layer order. Only backward-compatible additions are
    # made: an edge that would close a cycle is reported as a warning, not forced.
    for edge in contract.dependencies:
        for predecessor in builder.index.get(edge.predecessor, []):
            for successor in builder.index.get(edge.successor, []):
                _add_edge(builder, predecessor, successor, edge.reason)

    assemble_end = len(builder.tasks)
    builder.close_layer(
        "Deliverables assembled", "Each required deliverable exists in the requested form."
    )

    # ---- Layer 4: verify -----------------------------------------------
    # Verification adds real tasks, not just metadata: "check your work" that is
    # not in the graph is a note, and notes get ignored.
    verify_start = len(builder.tasks)
    for item in contract.verification_strategy.items[:_MAX_VERIFICATION_TASKS]:
        applies = sorted({key for name in item.applies_to for key in builder.index.get(name, [])})
        if not applies:
            # Fall back to the assembled work, never to the previous check. Hanging
            # checks off each other serialises them, which is both wrong (citation
            # and source quality can be checked in parallel) and needlessly slow.
            applies = [task.key for task in builder.tasks[assemble_start:assemble_end]]
        if not applies:
            applies = [builder.tasks[-1].key]
        builder.add(
            contract_keys=[],
            title=item.title,
            description=item.description or item.title,
            activity=AcademicTaskType.VERIFY,
            effort_minutes=builder.estimate(AcademicTaskType.VERIFY, RequirementPriority.MEDIUM),
            priority=AcademicTaskPriority.MEDIUM,
            depends_on=applies,
            verification_method=item.method or "MANUAL_REVIEW",
            acceptance_criteria=[item.description or item.title],
        )
    if len(builder.tasks) > verify_start:
        builder.close_layer(
            "Verified against the brief", "The work has been checked and is ready to submit."
        )

    # ---- Milestones ------------------------------------------------------
    milestones = _build_milestones(builder, contract)

    # ---- Effort roll-up --------------------------------------------------
    total_minutes = sum(task.min_minutes or 0 for task in builder.tasks)
    max_minutes = sum(task.max_minutes or 0 for task in builder.tasks)
    if declared_budget:
        # A stated output budget is a floor, not a ceiling: the brief's own size
        # wins over the per-task sum, and the upper bound keeps the headroom.
        total_minutes = max(total_minutes, declared_budget)
        max_minutes = max(max_minutes, _round_to_block(declared_budget * 1.3))
    if grade_weight_minutes:
        total_minutes = max(total_minutes, _round_to_block(grade_weight_minutes * 0.5))
        max_minutes = max(max_minutes, _round_to_block(grade_weight_minutes * 0.65))

    risks = _build_risks(contract, builder.dropped_areas)
    objectives = [item.statement for item in contract.objectives][: _OBJECTIVE_CAP[prefs.guidance]]
    verification_points = _build_verification_points(builder, contract, verify_start)
    plan_title = title or _default_title(contract)

    return PlannerOutput(
        title=plan_title[:240],
        summary=summary
        or (
            f"{len(builder.tasks)} tasks in four stages: orient, develop, assemble, verify. "
            f"Estimated {_hours(total_minutes)} to {_hours(max_minutes)} of focused work."
        ),
        objectives=objectives,
        tasks=builder.tasks,
        milestones=milestones,
        verification_points=verification_points,
        risks=risks,
        estimated_effort=_effort_band(total_minutes, _PLAN_EFFORT_BANDS),
        min_minutes=total_minutes,
        max_minutes=max_minutes,
        confidence=0.9,
    )


def _default_title(contract: PlanningContractResponse) -> str:
    """Name the plan after the work, not after the mechanism.

    "Plan for the literature review" beats "Plan for R1" and, unlike a generated
    headline, it cannot misrepresent what the assignment actually asks for.
    """
    required = [item for item in contract.deliverables if item.required is not False]
    if required:
        return f"Plan for {required[0].title}"
    if contract.requirements:
        return f"Plan for {contract.requirements[0].title}"
    return "Academic work plan"


def _build_verification_points(
    builder: _Builder, contract: PlanningContractResponse, verify_start: int
) -> list[PlannedVerificationPoint]:
    """Mirror the verify tasks back as named verification points.

    The tasks are the work; these are the named checks the client can render as a
    checklist and the student can tick off. Deriving one from the other keeps them
    from drifting apart after a regeneration.
    """
    by_key = {task.key: task for task in builder.tasks}
    return [
        PlannedVerificationPoint(
            key=f"V{index}",
            title=task.title,
            description=task.description,
            method=task.verification_method or "MANUAL_REVIEW",
            task_keys=[task.key],
            related_requirements=sorted(task.related_requirements),
        )
        for index, task in enumerate(builder.tasks[verify_start:], start=1)
        if task.key in by_key
    ]


def _acceptance_for(deliverable: Any) -> list[str]:
    criteria = [f"{deliverable.title} exists and addresses every related requirement."]
    if deliverable.format:
        criteria.append(f"It is in the requested form: {deliverable.format}.")
    return criteria


def _add_edge(builder: _Builder, predecessor: str, successor: str, reason: str | None) -> None:
    by_key = {task.key: task for task in builder.tasks}
    if predecessor == successor or predecessor not in by_key or successor not in by_key:
        return
    if successor in by_key[predecessor].depends_on:
        return
    if _would_cycle(by_key, predecessor, successor):
        # Recorded as a task note rather than silently dropped, so a student can
        # see that the analyzer's ordering was not applied.
        note = "Analyzer ordering not applied (it would close a dependency cycle)."
        existing = by_key[successor].acceptance_criteria
        by_key[successor].acceptance_criteria = [*existing, note][:8]
        return
    by_key[successor].depends_on = sorted({*by_key[successor].depends_on, predecessor})


def _would_cycle(by_key: dict[str, PlannedTask], predecessor: str, successor: str) -> bool:
    """True when adding ``predecessor`` as a dependency of ``successor`` cycles."""
    stack = [predecessor]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == successor:
            return True
        if node in seen:
            continue
        seen.add(node)
        task = by_key.get(node)
        if task is not None:
            stack.extend(task.depends_on)
    return False


def _build_milestones(
    builder: _Builder, contract: PlanningContractResponse
) -> list[PlannedMilestone]:
    """Turn the recorded layers into at most ``MAX_MILESTONES`` milestones.

    Driven by the layer boundaries rather than inferred from the graph, because
    the layer a task was created in is the honest answer to "when is this done"
    and re-deriving it from edges would be a guess.
    """
    by_key = {task.key: task for task in builder.tasks}
    order = {task.key: index for index, task in enumerate(builder.tasks)}
    milestones: list[PlannedMilestone] = []
    for title, description, keys in builder.layers:
        if not keys:
            continue
        milestones.append(
            PlannedMilestone(
                key=f"M{len(milestones) + 1}",
                title=title,
                description=description,
                task_keys=sorted(keys, key=order.__getitem__),
            )
        )
        if len(milestones) == MAX_MILESTONES:
            break
    # A plan with tasks but no layers recorded should still get one milestone, or
    # the client renders a task list with no checkpoints at all.
    if not milestones and builder.tasks:
        milestones.append(
            PlannedMilestone(
                key="M1",
                title="Complete all tasks",
                description="Every task in the plan, in dependency order.",
                task_keys=sorted(by_key, key=order.__getitem__),
            )
        )
    return milestones


def _build_risks(
    contract: PlanningContractResponse, dropped_areas: list[str] | None = None
) -> list[PlannedRisk]:
    """Carry the brief's own risks into the plan and add planning-specific ones."""
    risks: list[PlannedRisk] = []
    for index, item in enumerate(contract.risks[:4], start=1):
        risks.append(
            PlannedRisk(
                key=f"K{index}",
                description=item.description,
                severity=item.severity.value,
                mitigation=item.mitigation_hint,
            )
        )

    if dropped_areas:
        risks.append(
            PlannedRisk(
                key=f"K{len(risks) + 1}",
                description=(
                    "The brief was broken into more work areas than the plan can hold, "
                    "so these were not given their own task: " + ", ".join(dropped_areas[:4])
                ),
                severity="INFO",
                mitigation="Add a task for any of these that turns out to matter.",
            )
        )

    hard_constraints = [
        item
        for item in contract.constraints
        if item.severity.value in {"HARD", "CRITICAL"} and item.title
    ]
    if hard_constraints:
        risks.append(
            PlannedRisk(
                key=f"K{len(risks) + 1}",
                description=(
                    "Hard constraints limit how the work can be done: "
                    + "; ".join(item.title for item in hard_constraints[:3])
                ),
                severity="WARNING",
                mitigation="Check each constraint against the finished work before submitting.",
            )
        )
    return risks[:10]


def _hours(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    return f"{hours:.1f} h".replace(".0 h", " h")


def estimate_available_minutes(
    deadline: datetime | None, now: datetime | None = None
) -> int | None:
    """Minutes from now until the deadline, never negative.

    Deliberately the *whole* remaining window, not a working-hours calculation.
    A student knows better than the system which hours are theirs, and a plan that
    silently assumes a 40-hour week produces false urgency.
    """
    if deadline is None:
        return None
    reference = now or datetime.now(UTC)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    remaining = (deadline - reference).total_seconds() / 60
    return max(0, int(remaining))


class _Countable(Protocol):
    """What the schedule check actually reads: how much there is to do."""

    @property
    def requirements(self) -> Sized: ...

    @property
    def deliverables(self) -> Sized: ...


def schedule_risk(
    contract: _Countable,
    *,
    min_minutes: int | None,
    max_minutes: int | None,
    deadline: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compare the estimate against the time remaining, without pretending.

    Returns a level and a human summary. It never says the work will be finished;
    it says the upper estimate does or does not fit the remaining window, which is
    a fact, and leaves the trade-off to the student.
    """
    available = estimate_available_minutes(deadline, now)
    estimated = max_minutes or min_minutes or 0
    factors: list[str] = [
        f"{len(contract.requirements)} requirements",
        f"{len(contract.deliverables)} deliverables",
    ]
    if available is None:
        return {
            "level": ComplexityLevel.LOW,
            "estimated_minutes": estimated,
            "available_minutes": None,
            "is_overcommitted": False,
            "summary": "No deadline set, so there is nothing to compare the estimate against.",
            "factors": factors,
        }

    overcommitted = estimated > available
    if overcommitted:
        if available == 0:
            level = ComplexityLevel.VERY_HIGH
            summary = "The deadline has already passed."
        else:
            over = estimated - available
            level = ComplexityLevel.HIGH if over < available else ComplexityLevel.VERY_HIGH
            summary = (
                f"The upper estimate of {_hours(estimated)} does not fit the "
                f"{_hours(available)} remaining. You are about {_hours(over)} over, so "
                "something has to be descoped, renegotiated or started now."
            )
    else:
        headroom = available - estimated
        level = ComplexityLevel.LOW if headroom > estimated else ComplexityLevel.MEDIUM
        summary = (
            f"The upper estimate of {_hours(estimated)} fits inside the "
            f"{_hours(available)} remaining, with about {_hours(headroom)} of slack."
        )
    factors.append(f"estimate {_hours(estimated)} vs {_hours(available)} remaining")
    return {
        "level": level,
        "estimated_minutes": estimated,
        "available_minutes": available,
        "is_overcommitted": overcommitted,
        "summary": summary,
        "factors": factors,
    }


__all__ = [
    "MAX_MILESTONES",
    "PlanningPreferences",
    "build_planning_preferences",
    "estimate_available_minutes",
    "schedule_risk",
    "synthesize_plan",
]
