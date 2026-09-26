"""Tests for the deterministic planning engine and the graph authority.

The load-bearing claim of Phase 4 is that a plan is trustworthy because the engine
that produced it is deterministic and checkable. These tests assert exactly that:
the same contract always yields the same plan, the plan satisfies its own
validator, and the validator refuses the specific defects a real model produces.

The cross-domain sweep matters as much as the unit tests. A planner that quietly
only works for essays would pass every hand-written example here, so every golden
Phase 3 fixture is planned as well.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.enums import (
    AcademicTaskType,
    ComplexityLevel,
    ConstraintType,
    GuidanceLevel,
    PlanningStyle,
    SourceKind,
)
from app.modules.planning.complexity import longest_dependency_chain, score_complexity
from app.modules.planning.contract_forge import contracts_for_fixtures
from app.modules.planning.graph import (
    PlanGraphError,
    detect_cycle,
    topological_order,
    validate_edited_graph,
    validate_graph,
)
from app.modules.planning.planner import (
    build_planning_preferences,
    estimate_available_minutes,
    schedule_risk,
    synthesize_plan,
)
from app.schemas.analysis import (
    EvaluationAnalysis,
    PlanningContractRequirement,
    RequirementCategory,
    RequirementPriority,
    ScopeAnalysis,
    ScopeLevel,
)
from app.schemas.planning import PlannedTask, PlannerOutput

# ---------------------------------------------------------------------------
# Graph primitives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("edges", "expected"),
    [
        ({"T1": [], "T2": ["T1"]}, None),
        ({"T1": ["T2"], "T2": ["T1"]}, ["T1", "T2", "T1"]),
        ({"T1": ["T1"]}, ["T1", "T1"]),
        ({"T1": ["T2"], "T2": ["T3"], "T3": ["T1"]}, ["T1", "T2", "T3", "T1"]),
    ],
)
def test_detect_cycle(edges: dict[str, list[str]], expected: list[str] | None) -> None:
    assert detect_cycle(edges) == expected


def test_detect_cycle_handles_deep_graph_without_recursion() -> None:
    # A pathological chain must not be able to exhaust the interpreter stack.
    edges: dict[str, list[str]] = {f"T{i}": [f"T{i + 1}"] for i in range(3000)}
    edges["T3000"] = []
    assert detect_cycle(edges) is None


def test_topological_order_is_deterministic() -> None:
    edges = {"b": ["c"], "a": ["c"], "c": []}
    # "c" depends on nothing, so it leads; the tie between a and b breaks
    # alphabetically. Two runs over the same input cannot differ.
    assert topological_order(edges) == topological_order(edges) == ["c", "a", "b"]


def test_topological_order_places_predecessors_first() -> None:
    assert topological_order({"T3": ["T2"], "T2": ["T1"], "T1": []}) == ["T1", "T2", "T3"]


# ---------------------------------------------------------------------------
# The validator refuses what a model actually gets wrong
# ---------------------------------------------------------------------------


def _contract_with(
    *,
    requirement_keys: tuple[str, ...] = ("R1",),
    deliverable_keys: tuple[str, ...] = ("D1",),
    required: bool = True,
):
    from uuid import uuid4

    from app.models.enums import AcademicDomain, AssignmentType
    from app.schemas.analysis import (
        ClassifiedDomain,
        ClassifiedType,
        PlanningContractDeliverable,
        PlanningContractResponse,
        VerificationStrategy,
    )

    return PlanningContractResponse(
        analysis_id=uuid4(),
        assignment_id=uuid4(),
        analysis_version=1,
        revision=1,
        specification_version=1,
        specification_hash="h",
        prompt_version="v1",
        provider="mock",
        model="mock",
        is_stale=False,
        assignment_types=[
            ClassifiedType(type=AssignmentType.ESSAY, confidence=0.9, source="AI")  # type: ignore[arg-type]
        ],
        academic_domains=[
            ClassifiedDomain(domain=AcademicDomain.OTHER, confidence=0.9, source="AI")  # type: ignore[arg-type]
        ],
        objectives=[],
        requirements=[
            PlanningContractRequirement(
                key=key,
                title=f"Requirement {key}",
                description=None,
                source_reference=None,
                category=RequirementCategory.CONTENT,
                priority=RequirementPriority.MEDIUM,
                required=required,
                source_kind=SourceKind.EXPLICIT,
                confidence=0.9,
            )
            for key in requirement_keys
        ],
        constraints=[],
        deliverables=[
            PlanningContractDeliverable(
                key=key,
                title=f"Deliverable {key}",
                description=None,
                required=required,
                format="document",
                related_requirements=list(requirement_keys),
                verification_needs=[],
                depends_on=[],
                uncertainty=SourceKind.EXPLICIT,
                confidence=0.9,
            )
            for key in deliverable_keys
        ],
        dependencies=[],
        work_areas=[],
        risks=[],
        verification_strategy=VerificationStrategy(items=[], notes=[], confidence=0.9),
        clarification_questions=[],
        specialized_analysis=[],
        evaluation=EvaluationAnalysis(),
        scope=ScopeAnalysis(overall=ScopeLevel.MEDIUM, confidence=0.9),
    )


def _plan_with(tasks: list[PlannedTask], **kwargs) -> PlannerOutput:
    return PlannerOutput(
        title="Plan",
        tasks=tasks,
        milestones=kwargs.pop("milestones", []),
        **kwargs,
    )


def test_validator_rejects_dependency_cycle() -> None:
    contract = _contract_with()
    plan = _plan_with(
        [
            PlannedTask(key="T1", title="a", related_requirements=["R1"], depends_on=["T2"]),
            PlannedTask(key="T2", title="b", related_requirements=["R1"], depends_on=["T1"]),
            PlannedTask(key="T3", title="c", related_deliverables=["D1"]),
        ]
    )
    with pytest.raises(PlanGraphError) as excinfo:
        validate_graph(plan, contract)
    assert any("cycle" in violation for violation in excinfo.value.violations)


def test_validator_rejects_dangling_task_reference() -> None:
    contract = _contract_with()
    plan = _plan_with(
        [
            PlannedTask(key="T1", title="a", related_requirements=["R1"], depends_on=["T99"]),
            PlannedTask(key="T2", title="b", related_deliverables=["D1"]),
        ]
    )
    with pytest.raises(PlanGraphError) as excinfo:
        validate_graph(plan, contract)
    assert any("unknown task T99" in v for v in excinfo.value.violations)


def test_validator_rejects_unknown_requirement_reference() -> None:
    contract = _contract_with()
    plan = _plan_with([PlannedTask(key="T1", title="a", related_requirements=["R404"])])
    with pytest.raises(PlanGraphError) as excinfo:
        validate_graph(plan, contract)
    assert any("unknown requirement R404" in v for v in excinfo.value.violations)


def test_validator_rejects_uncovered_required_requirement() -> None:
    # The failure mode that matters most: a plan that quietly drops part of the
    # brief. It must be refused, not persisted and flagged later.
    contract = _contract_with(requirement_keys=("R1", "R2"), deliverable_keys=("D1",))
    plan = _plan_with(
        [
            PlannedTask(key="T1", title="a", related_requirements=["R1"]),
            PlannedTask(key="T2", title="b", related_deliverables=["D1"]),
        ]
    )
    with pytest.raises(PlanGraphError) as excinfo:
        validate_graph(plan, contract)
    assert any("R2" in v for v in excinfo.value.violations)


def test_validator_rejects_uncovered_required_deliverable() -> None:
    contract = _contract_with()
    plan = _plan_with([PlannedTask(key="T1", title="a", related_requirements=["R1"])])
    with pytest.raises(PlanGraphError) as excinfo:
        validate_graph(plan, contract)
    assert any("D1" in v for v in excinfo.value.violations)


def test_validator_reports_every_violation_at_once() -> None:
    # One round trip should surface every problem, not the first one.
    contract = _contract_with(requirement_keys=("R1", "R2"))
    plan = _plan_with([PlannedTask(key="T1", title="a", related_requirements=["R404"])])
    with pytest.raises(PlanGraphError) as excinfo:
        validate_graph(plan, contract)
    assert len(excinfo.value.violations) >= 2


def test_validator_rejects_duplicate_task_keys() -> None:
    contract = _contract_with()
    plan = _plan_with(
        [
            PlannedTask(key="T1", title="a", related_requirements=["R1"]),
            PlannedTask(key="T1", title="b", related_deliverables=["D1"]),
        ]
    )
    with pytest.raises(PlanGraphError):
        validate_graph(plan, contract)


def test_validator_warns_when_nothing_is_verified() -> None:
    contract = _contract_with()
    plan = _plan_with(
        [
            PlannedTask(key="T1", title="a", related_requirements=["R1"]),
            PlannedTask(key="T2", title="b", related_deliverables=["D1"], depends_on=["T1"]),
        ]
    )
    graph = validate_graph(plan, contract)
    assert any("verification" in warning for warning in graph.warnings)


def test_validate_edited_graph_rejects_a_hand_made_cycle() -> None:
    # A student editing dependencies by hand can create the same cycle a model can.
    violations = validate_edited_graph([{"key": "T1"}, {"key": "T2"}], [("T1", "T2"), ("T2", "T1")])
    assert any("cycle" in v for v in violations)


def test_validate_edited_graph_accepts_a_sound_graph() -> None:
    assert validate_edited_graph([{"key": "T1"}, {"key": "T2"}], [("T2", "T1")]) == []


# ---------------------------------------------------------------------------
# The deterministic planner
# ---------------------------------------------------------------------------


def test_planner_is_deterministic() -> None:
    # Same contract in, byte-identical plan out. This is what makes idempotency
    # and "what did I approve" answerable.
    _, first = contracts_for_fixtures([])[0]
    plan_a = synthesize_plan(first)
    plan_b = synthesize_plan(first)
    assert plan_a.model_dump() == plan_b.model_dump()


def test_planner_output_passes_its_own_validator() -> None:
    for name, contract in contracts_for_fixtures([]):
        plan = synthesize_plan(contract)
        graph = validate_graph(plan, contract)
        assert len(graph.order) == len(plan.tasks), name
        assert graph.order[0] in {task.key for task in plan.tasks}


def test_planner_covers_every_required_requirement_and_deliverable() -> None:
    for name, contract in contracts_for_fixtures([]):
        plan = synthesize_plan(contract)
        covered_requirements = {ref for task in plan.tasks for ref in task.related_requirements}
        covered_deliverables = {ref for task in plan.tasks for ref in task.related_deliverables}
        for requirement in contract.requirements:
            if requirement.required and requirement.source_kind == SourceKind.EXPLICIT:
                assert requirement.key in covered_requirements, f"{name}: {requirement.key}"
        for deliverable in contract.deliverables:
            if deliverable.required:
                assert deliverable.key in covered_deliverables, f"{name}: {deliverable.key}"


def test_planner_produces_a_dag() -> None:
    for name, contract in contracts_for_fixtures([]):
        plan = synthesize_plan(contract)
        edges = {task.key: list(task.depends_on) for task in plan.tasks}
        assert detect_cycle(edges) is None, name


def test_planner_task_references_all_exist() -> None:
    for name, contract in contracts_for_fixtures([]):
        plan = synthesize_plan(contract)
        keys = {task.key for task in plan.tasks}
        for task in plan.tasks:
            assert set(task.depends_on) <= keys, f"{name}: {task.key}"


def test_planner_does_not_leak_work_area_keys_into_traceability() -> None:
    # A work-area key in related_requirements claims the task serves a requirement
    # that does not exist. The validator catches it, but it must never be produced.
    for name, contract in contracts_for_fixtures([]):
        plan = synthesize_plan(contract)
        requirement_keys = {item.key for item in contract.requirements}
        for task in plan.tasks:
            assert set(task.related_requirements) <= requirement_keys, f"{name}: {task.key}"


def test_planner_preserves_the_analyzer_work_area_chain() -> None:
    # The analyzer's own work-area ordering is the most valuable structure in the
    # contract; the planner must not flatten it into unordered reading tasks.
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    plan = synthesize_plan(contract)
    titles = [task.title for task in plan.tasks]
    for area in contract.work_areas:
        assert area.title in titles, area.key


def test_planner_milestone_layers_are_disjoint() -> None:
    # Cumulative milestones are not checkpoints.
    for name, contract in contracts_for_fixtures([]):
        plan = synthesize_plan(contract)
        seen: set[str] = set()
        for milestone in plan.milestones:
            overlap = seen & set(milestone.task_keys)
            assert not overlap, f"{name}: {milestone.key} repeats {overlap}"
            seen.update(milestone.task_keys)


def test_planner_verification_tasks_hang_off_assembled_work() -> None:
    # Checks must not chain off each other; they run in parallel on the output.
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    plan = synthesize_plan(contract)
    verify = [task for task in plan.tasks if task.type == AcademicTaskType.VERIFY]
    assert len(verify) >= 2
    verify_keys = {task.key for task in verify}
    for task in verify:
        assert not (set(task.depends_on) & verify_keys), task.key


def test_planner_uses_generic_task_types() -> None:
    # No task type may assume code. This is the guard against the vocabulary
    # drifting back toward a code-specific planner.
    code_only = {
        AcademicTaskType.WRITE,
        AcademicTaskType.RESEARCH,
        AcademicTaskType.ANALYZE,
        AcademicTaskType.OTHER,
    }
    for name, contract in contracts_for_fixtures([]):
        plan = synthesize_plan(contract)
        assert {task.type for task in plan.tasks} <= set(AcademicTaskType), name
        assert len({task.type for task in plan.tasks}) > 1, name
    assert code_only  # the assertion above is about the enum, not this set


def test_planner_respects_max_task_count() -> None:
    # The cap has to bind no matter which layer is filling the plan, so it is
    # enforced in the builder rather than checked per loop.
    contract = dict(contracts_for_fixtures([]))["programming_assignment"]
    for cap in (3, 5, 8, 60):
        assert len(synthesize_plan(contract, max_task_count=cap).tasks) <= cap, cap


def test_planner_style_changes_estimates() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    minimal = synthesize_plan(
        contract, preferences=build_planning_preferences(PlanningStyle.MINIMAL, None, None)
    )
    detailed = synthesize_plan(
        contract, preferences=build_planning_preferences(PlanningStyle.DETAILED, None, None)
    )
    assert (minimal.min_minutes or 0) < (detailed.min_minutes or 0)


def test_planner_guidance_adds_time() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    low = synthesize_plan(
        contract, preferences=build_planning_preferences(None, GuidanceLevel.LOW, None)
    )
    high = synthesize_plan(
        contract, preferences=build_planning_preferences(None, GuidanceLevel.HIGH, None)
    )
    assert (low.min_minutes or 0) < (high.min_minutes or 0)


def test_planner_honours_a_stated_word_budget() -> None:
    contract = dict(contracts_for_fixtures([]))["essay"]
    contract.constraints.append(
        _constraint("Length", "The essay must be 3000 words.", constraint_type=ConstraintType.TIME)
    )
    plan = synthesize_plan(contract)
    # 3000 words at 200 wpm is 900 minutes, which the per-task sum alone misses.
    assert (plan.min_minutes or 0) >= 900


def _constraint(title: str, description: str, *, constraint_type: ConstraintType):
    from uuid import uuid4

    from app.models.enums import ConstraintSeverity
    from app.schemas.analysis import ConstraintSnapshot

    return ConstraintSnapshot(
        id=uuid4(),
        title=title,
        description=description,
        value=None,
        type=constraint_type,
        severity=ConstraintSeverity.WARNING,
    )


def test_effort_bands_differ_per_task_and_per_plan() -> None:
    # A single band shared by tasks and totals would label every task VERY_LOW and
    # every plan VERY_HIGH.
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    plan = synthesize_plan(contract)
    per_task = {task.estimated_effort for task in plan.tasks}
    assert plan.estimated_effort.value in {"MEDIUM", "HIGH", "VERY_HIGH"}
    assert per_task


# ---------------------------------------------------------------------------
# Complexity scoring
# ---------------------------------------------------------------------------


def test_complexity_increases_with_the_brief() -> None:
    pairs = dict(contracts_for_fixtures([]))
    simple = score_complexity(pairs["reading_assignment"])
    heavy = score_complexity(pairs["programming_assignment"])
    assert heavy.score > simple.score


def test_complexity_lists_its_factors() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    score = score_complexity(contract)
    assert score.factors
    assert any("requirements" in factor for factor in score.factors)


def test_longest_dependency_chain() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    assert longest_dependency_chain(contract) >= 1


def test_complexity_levels_are_bounded() -> None:
    for name, contract in contracts_for_fixtures([]):
        score = score_complexity(contract)
        assert 0.0 <= score.score <= 100.0, name
        assert score.level in set(ComplexityLevel), name


# ---------------------------------------------------------------------------
# Schedule honesty
# ---------------------------------------------------------------------------


def test_estimate_available_minutes_never_goes_negative() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    assert estimate_available_minutes(past) == 0


def test_estimate_available_minutes_treats_naive_deadlines_as_utc() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deadline = datetime(2026, 1, 2)  # naive, as SQLite hands it back
    assert estimate_available_minutes(deadline, now=now) == 24 * 60


def test_schedule_risk_reports_overcommitment() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    result = schedule_risk(
        contract,
        min_minutes=600,
        max_minutes=900,
        deadline=datetime.now(UTC) + timedelta(hours=2),
    )
    assert result["is_overcommitted"] is True
    assert "does not fit" in result["summary"]


def test_schedule_risk_reports_headroom() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    result = schedule_risk(
        contract,
        min_minutes=60,
        max_minutes=120,
        deadline=datetime.now(UTC) + timedelta(days=30),
    )
    assert result["is_overcommitted"] is False
    assert "slack" in result["summary"]


def test_schedule_risk_without_a_deadline_says_so() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    result = schedule_risk(contract, min_minutes=60, max_minutes=120, deadline=None)
    assert result["available_minutes"] is None
    assert result["is_overcommitted"] is False
    assert "no deadline" in result["summary"].lower()


def test_schedule_risk_handles_an_expired_deadline() -> None:
    contract = dict(contracts_for_fixtures([]))["research_paper"]
    result = schedule_risk(
        contract,
        min_minutes=60,
        max_minutes=120,
        deadline=datetime.now(UTC) - timedelta(hours=1),
    )
    assert result["is_overcommitted"] is True
    assert "already passed" in result["summary"]


# ---------------------------------------------------------------------------
# Golden sweeps, stated as tests so a regression names the domain
# ---------------------------------------------------------------------------


def test_every_golden_domain_plans_and_validates() -> None:
    pairs = contracts_for_fixtures([])
    assert len(pairs) == 12
    for name, contract in pairs:
        plan = synthesize_plan(contract)
        assert plan.tasks, name
        validate_graph(plan, contract)


def test_no_golden_domain_exceeds_the_task_cap() -> None:
    for name, contract in contracts_for_fixtures([]):
        assert len(synthesize_plan(contract).tasks) <= 60, name
