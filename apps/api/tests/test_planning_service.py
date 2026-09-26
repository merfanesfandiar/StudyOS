"""Persistence and lifecycle behaviour of the planning service.

The unit tests in ``test_planning_engine.py`` check that a *proposed* plan is
sane. These check that the plan which reaches the database is still that plan. The
distinction matters: a plan can validate perfectly and then lose its dependency
edges, its milestone membership or the student's own tasks on the way to storage,
and every read path afterwards would quietly show something else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.errors import AppError
from app.models import (
    AcademicWorkPlan,
    Assignment,
    AssignmentAnalysis,
    Course,
    PlanTask,
    PlanTaskDependency,
    User,
    Workspace,
)
from app.models.enums import (
    AcademicTaskStatus,
    ComplexityLevel,
    ModelTier,
    PlanningRunStatus,
    PlanningStyle,
    PlanStatus,
    PlanTrigger,
)
from app.modules.planning import service
from app.modules.planning.contract_forge import contracts_for_fixtures
from app.modules.planning.graph import validate_graph
from app.modules.planning.planner import (
    PlanningPreferences,
    build_planning_preferences,
    synthesize_plan,
)
from app.schemas.analysis import PlanningContractResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def contract() -> PlanningContractResponse:
    return contracts_for_fixtures([])[0][1]


@pytest.fixture
def preferences() -> PlanningPreferences:
    return build_planning_preferences(PlanningStyle.BALANCED, None, None)


@pytest.fixture
async def owner(db_session: AsyncSession) -> User:
    user = User(id=uuid4(), name="Student", email=f"{uuid4().hex}@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def workspace(db_session: AsyncSession, owner: User) -> Workspace:
    row = Workspace(id=uuid4(), name="Workspace", owner_id=owner.id)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def course(db_session: AsyncSession, workspace: Workspace) -> Course:
    row = Course(id=uuid4(), workspace_id=workspace.id, name="Real Analysis", code="MATH201")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def assignment(db_session: AsyncSession, workspace: Workspace, course: Course) -> Assignment:
    row = Assignment(
        id=uuid4(),
        workspace_id=workspace.id,
        course_id=course.id,
        title="Prove that the sequence converges",
        description="Show the convergence argument in full.",
        deadline=datetime.now(UTC) + timedelta(days=14),
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def analysis(db_session: AsyncSession, assignment: Assignment) -> AssignmentAnalysis:
    row = AssignmentAnalysis(
        id=uuid4(),
        assignment_id=assignment.id,
        analysis_version=1,
        revision=1,
        specification_version=1,
        specification_hash="a" * 64,
        idempotency_key="k" * 64,
        prompt_version="academic_analyzer_v1",
        provider="mock",
        model="mock-academic-analyzer-v1",
        summary="A convergence proof.",
        confidence=0.8,
        payload={},
    )
    db_session.add(row)
    await db_session.flush()
    return row


def _edges(graph: service.PlanGraphView) -> dict[str, set[str]]:
    """The loaded graph as ``task key -> prerequisite keys``.

    ``PlanGraphView`` holds rows rather than a key map, so this is the shape the
    assertions actually care about: the same convention the validator uses.
    """
    by_id = {task.id: task for task in graph.tasks}
    out: dict[str, set[str]] = {task.key: set() for task in graph.tasks}
    for edge in graph.dependencies:
        out[by_id[edge.successor_id].key].add(by_id[edge.predecessor_id].key)
    return out


async def _task_row(db: AsyncSession, plan: AcademicWorkPlan, key: str) -> PlanTask:
    return (
        await db.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id, PlanTask.key == key))
    ).one()


async def _persist(
    db: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
    *,
    trigger: PlanTrigger = PlanTrigger.GENERATED,
    idempotency_key: str | None = None,
    preserve: tuple = (),
) -> tuple[AcademicWorkPlan, object]:
    output = synthesize_plan(contract, preferences=preferences)
    graph = validate_graph(output, contract)
    plan = await service.persist_plan(
        db,
        assignment=assignment,
        analysis=analysis,
        plan_output=output,
        graph=graph,
        contract=contract,
        trigger=trigger,
        reason="",
        preferences=preferences,
        idempotency_key=idempotency_key,
        preserve=preserve,
    )
    await db.commit()
    return plan, output


# ---------------------------------------------------------------------------
# Dependencies survive persistence
# ---------------------------------------------------------------------------


async def test_dependencies_are_persisted_not_just_proposed(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """The DAG that validated must be the DAG that is stored.

    Writing the tasks without the edges would leave a plan that passes every
    in-memory check and reloads as a set of unrelated tasks.
    """
    plan, output = await _persist(db_session, assignment, analysis, contract, preferences)

    edges = list(
        await db_session.scalars(
            select(PlanTaskDependency).where(PlanTaskDependency.plan_id == plan.id)
        )
    )
    proposed = {task.key: set(task.depends_on) for task in output.tasks}
    assert proposed, "fixture should produce a plan with dependencies"

    rows = list(await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id)))
    by_id = {row.id: row for row in rows}
    assert len(by_id) == len(rows), "task ids should be unique within a plan"
    stored: dict[str, set[str]] = {key: set() for key in proposed}
    for edge in edges:
        assert edge.predecessor_id in by_id and edge.successor_id in by_id
        stored[by_id[edge.successor_id].key].add(by_id[edge.predecessor_id].key)
    assert stored == proposed


async def test_persisted_graph_reloads_and_matches(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """What comes back out of the database is the same plan that went in."""
    plan, output = await _persist(db_session, assignment, analysis, contract, preferences)

    graph = await service.load_plan_graph(db_session, plan)
    proposed = {task.key: set(task.depends_on) for task in output.tasks}
    assert {task.key for task in graph.tasks} == set(proposed)
    assert _edges(graph) == proposed
    # The same graph the proposal validated under, in the same order.
    assert set(validate_graph(output, contract).order) == {task.key for task in graph.tasks}


# ---------------------------------------------------------------------------
# Milestone membership round trip
# ---------------------------------------------------------------------------


async def test_milestone_membership_round_trips(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """A milestone must report the tasks it actually contains.

    Milestones have no join table, so membership lives in the payload. If that
    key goes missing, milestones render empty rather than failing loudly.
    """
    plan, output = await _persist(db_session, assignment, analysis, contract, preferences)
    assert output.milestones

    graph = await service.load_plan_graph(db_session, plan)
    for milestone in graph.milestones:
        keys = service._milestone_task_keys(milestone, graph)
        assert keys, f"{milestone.key} came back with no tasks"
        assert set(keys) <= {task.key for task in output.tasks}


async def test_payload_records_contract_counts(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """Schedule risk is computed from stored counts on read.

    Without them the response builder has nothing to work with and the schedule
    section silently degrades.
    """
    plan, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    payload = plan.payload or {}
    assert payload["requirement_count"] == len(contract.requirements)
    assert payload["deliverable_count"] == len(contract.deliverables)
    assert "milestones" in payload


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


async def test_versions_increment_and_previous_stays_readable(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """Regeneration adds a version. It never overwrites one."""
    first, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    second, _ = await _persist(
        db_session,
        assignment,
        analysis,
        contract,
        preferences,
        trigger=PlanTrigger.REGENERATED,
    )
    assert (first.version, second.version) == (1, 2)

    versions = await service.list_plan_versions(assignment.id, db_session)
    assert [item.version for item in versions] == [2, 1]

    latest = await service.latest_plan(assignment.id, db_session, include_draft=True)
    assert latest is not None and latest.id == second.id


async def test_approved_plan_is_immutable_and_edits_are_refused(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
    owner: User,
) -> None:
    """Approval is the point of no return for a single version.

    Changing an approved plan in place would make "what did I sign off on"
    unanswerable, which is the one question a plan has to survive.
    """
    plan, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    await service.approve_plan(db_session, plan, user_id=owner.id)
    await db_session.commit()
    assert plan.status == PlanStatus.APPROVED.value
    assert plan.approved_at is not None
    assert plan.approved_by_id == owner.id

    with pytest.raises(AppError) as excinfo:
        service.assert_editable(plan)
    assert excinfo.value.status_code == 409

    # And the service refuses the edit itself, not just a helper.
    with pytest.raises(AppError) as excinfo:
        await service.add_task(db_session, plan, title="Sneaked in after approval")
    assert excinfo.value.code == "PLAN_IMMUTABLE"


async def test_idempotent_plan_is_reused(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """A repeated request with the same key returns the same plan.

    Double-submitting a generate button should not produce two versions, and the
    run telemetry should not claim the model was called twice.
    """
    key = "k" * 64
    plan, _ = await _persist(
        db_session, assignment, analysis, contract, preferences, idempotency_key=key
    )
    found = await service.find_idempotent_plan(assignment.id, key, db_session)
    assert found is not None and found.id == plan.id

    again = await service.find_idempotent_plan(assignment.id, key, db_session)
    assert again is not None and again.id == plan.id

    missing = await service.find_idempotent_plan(assignment.id, "z" * 64, db_session)
    assert missing is None


# ---------------------------------------------------------------------------
# User work is not destroyed by regeneration
# ---------------------------------------------------------------------------


async def test_user_authored_tasks_survive_regeneration(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """A student's own task must reappear, intact, in the new version.

    This is the promise of partial regeneration. Losing it means a student's work
    disappears because a button was pressed twice.
    """
    first, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    added = await service.add_task(
        db_session,
        first,
        title="Ask the seminar group about the epsilon bound",
        description="Confirm the choice of epsilon before the proof.",
        related_requirements=[],
    )
    await db_session.commit()
    added.notes = "asked on 12 May"
    await db_session.commit()

    first_tasks = list(
        await db_session.scalars(
            select(PlanTask).where(PlanTask.plan_id == first.id).order_by(PlanTask.position)
        )
    )
    second, output = await _persist(
        db_session,
        assignment,
        analysis,
        contract,
        preferences,
        trigger=PlanTrigger.REGENERATED,
        preserve=tuple(first_tasks),
    )

    carried = [
        task
        for task in await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == second.id))
        if task.is_user_authored
    ]
    assert len(carried) == 1
    assert carried[0].title == "Ask the seminar group about the epsilon bound"
    assert carried[0].notes == "asked on 12 May"
    assert carried[0].description.startswith("Confirm the choice")


async def test_carried_task_keys_cannot_collide_with_generated_keys(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """Generated and preserved tasks must not fight over the same key.

    The student task kept its key from the old version, where ``T3`` meant their
    own work. In the new version ``T3`` is a generated task. Reusing the key would
    either violate the unique constraint or silently retarget their traceability.
    """
    first, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    await service.add_task(db_session, first, title="Personal note to self")
    await db_session.commit()

    first_tasks = list(
        await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == first.id))
    )
    second, output = await _persist(
        db_session,
        assignment,
        analysis,
        contract,
        preferences,
        trigger=PlanTrigger.REGENERATED,
        preserve=tuple(first_tasks),
    )

    keys = list(await db_session.scalars(select(PlanTask.key).where(PlanTask.plan_id == second.id)))
    assert len(keys) == len(set(keys)), "duplicate task keys in one plan"
    generated = {task.key for task in output.tasks}
    carried = set(keys) - generated
    assert carried and not (carried & generated)


async def test_dependencies_between_carried_tasks_are_kept(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """Edges between the student's own tasks carry over.

    Both endpoints are carried, so the edge is meaningful. Edges onto generated
    tasks are dropped on purpose, because those endpoints may not exist.
    """
    first, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    one = await service.add_task(db_session, first, title="Draft the outline")
    two = await service.add_task(
        db_session, first, title="Review the outline", depends_on=[one.key]
    )
    await db_session.commit()

    first_tasks = list(
        await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == first.id))
    )
    second, _ = await _persist(
        db_session,
        assignment,
        analysis,
        contract,
        preferences,
        trigger=PlanTrigger.REGENERATED,
        preserve=tuple(first_tasks),
    )

    carried = {
        task.title: task
        for task in await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == second.id))
        if task.is_user_authored
    }
    assert set(carried) == {"Draft the outline", "Review the outline"}
    rows = list(
        await db_session.scalars(
            select(PlanTaskDependency).where(PlanTaskDependency.plan_id == second.id)
        )
    )
    by_id = {
        task.id: task
        for task in await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == second.id))
    }
    carried_edges = {
        (by_id[edge.predecessor_id].title, by_id[edge.successor_id].title) for edge in rows
    }
    assert ("Draft the outline", "Review the outline") in carried_edges
    assert two.key is not None


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


async def test_task_update_marks_the_task_user_authored(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """A task a student edited by hand must be protected from regeneration.

    Otherwise the first regeneration deletes work the student deliberately did,
    because the system has no record that they touched it.
    """
    plan, output = await _persist(db_session, assignment, analysis, contract, preferences)
    target_row = await _task_row(db_session, plan, output.tasks[0].key)
    row = await service.update_task(
        db_session, plan, target_row, {"title": "Renamed by the student"}
    )
    await db_session.commit()
    assert row.is_user_authored is True
    assert row.title == "Renamed by the student"


async def test_edited_graph_is_revalidated_and_cycles_are_refused(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """An edit that creates a cycle is rejected, not stored.

    The database cannot see a cycle across rows, so this check is the only thing
    standing between a client and a plan that cannot be executed.
    """
    plan, output = await _persist(db_session, assignment, analysis, contract, preferences)
    tasks = list(
        await db_session.scalars(
            select(PlanTask).where(PlanTask.plan_id == plan.id).order_by(PlanTask.position)
        )
    )
    if len(tasks) < 2:
        pytest.skip("fixture produced a single-task plan")

    assignment_id = assignment.id
    with pytest.raises(AppError):
        await service.update_task(db_session, plan, tasks[0], {}, depends_on=[tasks[-1].key])
    await db_session.rollback()
    # Re-read everything: a rollback expires the whole session, and touching an
    # expired attribute in async faults instead of awaiting.
    reloaded = await service.latest_plan(assignment_id, db_session, include_draft=True)
    assert reloaded is not None
    stored = await service.load_plan_graph(db_session, reloaded)
    before = {task.key: set(task.depends_on) for task in output.tasks}
    assert _edges(stored) == before, "a refused edit must leave no trace"


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


async def test_stale_plans_are_marked_not_deleted(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
    owner: User,
) -> None:
    """When the analysis moves, old plans are flagged.

    Deleting them would destroy a student's approved work over a spec change they
    did not cause.
    """
    plan, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    await service.approve_plan(db_session, plan, user_id=owner.id)
    await db_session.commit()

    marked = await service.mark_stale_plans(db_session, assignment.id)
    await db_session.commit()
    assert marked == 1
    reloaded = await service.latest_plan(assignment.id, db_session, include_draft=True)
    assert reloaded is not None and reloaded.is_stale is True
    # Approval was a fact about the past; a spec change does not retract it.
    assert reloaded.status == PlanStatus.APPROVED.value
    assert reloaded.approved_at is not None
    assert service.is_plan_stale(reloaded, analysis) is True


# ---------------------------------------------------------------------------
# Response building
# ---------------------------------------------------------------------------


async def test_response_reports_progress_and_schedule(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """The rendered plan must agree with the stored plan.

    A response that disagrees with the database is worse than an error, because
    the student acts on it.
    """
    plan, output = await _persist(db_session, assignment, analysis, contract, preferences)
    graph = await service.load_plan_graph(db_session, plan)
    response = service.build_plan_response(plan, assignment=assignment, graph=graph)

    assert len(response.tasks) == len(output.tasks)
    assert response.version == 1
    assert response.status == PlanStatus.READY_FOR_REVIEW
    assert response.progress_percentage == 0
    assert response.schedule_risk is not None
    assert response.is_stale is False
    assert response.version == 1

    covered: set[str] = set()
    for task in response.tasks:
        covered.update(task.related_requirements)
    for requirement in contract.requirements:
        if requirement.required:
            assert requirement.key in covered, requirement.key


async def test_response_marks_partial_completion(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """Finishing half the tasks must show half done, not a rounded fiction."""
    plan, output = await _persist(db_session, assignment, analysis, contract, preferences)
    target_row = await _task_row(db_session, plan, output.tasks[0].key)
    await service.update_task(
        db_session, plan, target_row, {"status": AcademicTaskStatus.COMPLETED.value}
    )
    await db_session.commit()

    graph = await service.load_plan_graph(db_session, plan)
    response = service.build_plan_response(plan, assignment=assignment, graph=graph)
    assert 0 < response.progress_percentage < 100
    assert response.tasks[0].status == AcademicTaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Run telemetry
# ---------------------------------------------------------------------------


async def test_run_records_the_model_that_answered(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences: PlanningPreferences,
) -> None:
    """A run must name the model and tier, and record the plan it produced.

    Without this, a bad plan cannot be traced back to the model that wrote it,
    which is the only way to tell a model problem from a planning problem.
    """
    run = await service.start_run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        user_id=owner.id,
        idempotency_key="r" * 64,
        provider="mock",
        model="mock-academic-analyzer-v1",
        model_tier=ModelTier.ADVANCED,
        routing_reason="the brief is broad",
        routing_confidence=0.7,
        complexity=ComplexityLevel.HIGH,
        prompt_version="academic_planner_v1",
    )
    assert run.status == PlanningRunStatus.RUNNING.value

    plan, _ = await _persist(db_session, assignment, analysis, contract, preferences)
    await service.finish_run(
        db_session,
        run,
        status=PlanningRunStatus.SUCCEEDED,
        plan=plan,
        duration_ms=1234,
        token_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        estimated_cost=0.0001,
        output_hash="a" * 64,
    )
    await db_session.commit()

    assert run.status == PlanningRunStatus.SUCCEEDED.value
    assert run.plan_id == plan.id
    assert run.duration_ms == 1234
    assert run.token_usage["total_tokens"] == 30
    assert run.estimated_cost is not None
    assert run.routing_reason == "the brief is broad"
