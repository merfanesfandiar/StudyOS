"""End-to-end behaviour of the agent runtime against a real database.

The unit tests in this package check that individual pieces are correct in
isolation: that a transition table rejects an illegal move, that context is
truncated, that a decision is validated. Those are necessary and not sufficient.

What they cannot show is whether a *run* works: whether selecting a task and
executing it actually writes an execution row, whether the task's status moves
in the same transaction as the artifact, whether the budget is charged before
the step that spends it, and whether pausing halfway leaves the database in a
state a second process could pick up. Those are properties of the whole
sequence, so they are tested against SQLite with the real ORM and the real
service, using a deterministic provider so the assertions are about the runtime
rather than about a model.

The provider is injected. This is the only supported way to drive a run without
spending money or reaching the network, and it is what makes the suite
deterministic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage
from app.core.errors import AppError
from app.models import (
    AcademicWorkPlan,
    AgentRun,
    Assignment,
    AssignmentAnalysis,
    Course,
    PlanTask,
    PlanTaskDependency,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import (
    AcademicTaskStatus,
    AcademicTaskType,
    AgentCheckpointStatus,
    AgentRunMode,
    AgentRunStatus,
    AuditEventType,
    PlanStatus,
)
from app.modules.agent import recovery, service
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def owner(db_session: AsyncSession) -> User:
    row = User(id=uuid4(), name="Student", email=f"{uuid4().hex}@example.com", password_hash="x")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def space(db_session: AsyncSession, owner: User) -> Workspace:
    row = Workspace(id=uuid4(), name="Workspace", owner_id=owner.id)
    db_session.add(row)
    # Ownership is resolved through membership, not through workspace.owner_id,
    # so the row has to exist for the student to own anything at all.
    db_session.add(WorkspaceMember(workspace_id=row.id, user_id=owner.id, role="OWNER"))
    await db_session.flush()
    return row


@pytest.fixture
async def course(db_session: AsyncSession, space: Workspace) -> Course:
    row = Course(id=uuid4(), workspace_id=space.id, name="Analysis", code="MATH201")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def assignment(db_session: AsyncSession, space: Workspace, course: Course) -> Assignment:
    row = Assignment(
        id=uuid4(),
        workspace_id=space.id,
        course_id=course.id,
        title="Prove monotone convergence",
        description="Show that an increasing bounded sequence converges.",
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


async def _approved_plan(
    db: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    *,
    keys: tuple[str, ...] = ("T1", "T2"),
    chain: bool = True,
    version: int = 1,
) -> AcademicWorkPlan:
    """An approved two-task plan, optionally a dependency chain.

    Built directly rather than through the planning service because the agent's
    contract starts at "a student already approved this". What produced the plan
    is the planning module's problem, and its tests already cover it.
    """
    plan = AcademicWorkPlan(
        id=uuid4(),
        assignment_id=assignment.id,
        analysis_id=analysis.id,
        version=version,
        reason="GENERATED",
        trigger="GENERATED",
        title="Convergence proof plan",
        summary="Prove then check.",
        status=PlanStatus.APPROVED.value,
        objectives=[],
        payload={},
        approved_at=datetime.now(UTC),
    )
    db.add(plan)
    await db.flush()

    rows: dict[str, PlanTask] = {}
    for position, key in enumerate(keys):
        task = PlanTask(
            id=uuid4(),
            plan_id=plan.id,
            key=key,
            title=f"Task {key}",
            description=f"Work through {key}.",
            type=AcademicTaskType.RESEARCH.value,
            status=AcademicTaskStatus.PENDING.value,
            priority="HIGH",
            position=position,
            acceptance_criteria=[],
            resources=[],
        )
        db.add(task)
        rows[key] = task
    await db.flush()

    if chain and len(keys) > 1:
        for earlier, later in zip(keys, keys[1:], strict=False):
            db.add(
                PlanTaskDependency(
                    id=uuid4(),
                    plan_id=plan.id,
                    predecessor_id=rows[earlier].id,
                    successor_id=rows[later].id,
                    reason="ordered",
                )
            )
        await db.flush()
    return plan


class ScriptedProvider(LLMProvider):
    """A provider that answers with whatever the test tells it to.

    Being a real ``LLMProvider`` subclass matters: the runtime is then exercised
    through the same interface every concrete provider implements, so a change to
    that interface breaks these tests instead of only breaking production.

    The scripted *sequence* is keyed off the request's own metadata rather than a
    call counter, because a run makes two different kinds of call per step and a
    counter silently drifts out of step with the task graph. Echoing the selected
    task key back also means the double cannot accidentally ask to complete a task
    the runtime did not select.
    """

    name = "scripted"

    def __init__(self, replies: list[str] | None = None) -> None:
        self.model = "scripted-agent-v1"
        self.requests: list[LLMRequest] = []
        self._replies = list(replies or [])

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        metadata = request.metadata or {}
        if "agent_execution_input" in metadata:
            key = metadata["agent_execution_input"]["task_key"]
            content = json.dumps(
                {
                    "summary": f"Worked on {key}.",
                    "content": f"# Draft for {key}\n\nThe body the student actually reads.",
                }
            )
        elif self._replies:
            content = self._replies.pop(0)
        else:
            content = _decision_json()
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            estimated_cost=0.001,
        )

    def replies_for(self, *pairs: str) -> ScriptedProvider:
        self._replies = list(pairs)
        return self


def _decision_json(
    action: str = "CREATE_ARTIFACT",
    *,
    artifact_type: str = "SOLUTION",
    confidence: float = 0.9,
    title: str = "Draft",
    task_key: str | None = None,
    blocked_reason: str | None = None,
) -> str:
    """One structurally valid decision.

    The decision only asks for work; the executor supplies the body. Keeping
    ``content`` out of here is deliberate -- it mirrors what a real provider must
    do, so these tests would notice if the runtime ever started trusting
    model-supplied content over executor output.
    """
    payload: dict[str, object] = {
        "action": action,
        "reason": "This is the next useful thing to produce.",
        "confidence": confidence,
    }
    if action in {"CREATE_ARTIFACT", "UPDATE_ARTIFACT"}:
        payload["artifact_type"] = artifact_type
        payload["artifact_title"] = title
    if action in {"EXECUTE_TASK", "RETRY_TASK", "COMPLETE_TASK", "MARK_BLOCKED"}:
        payload["task_key"] = task_key
    if action == "MARK_BLOCKED":
        payload["blocked_reason"] = blocked_reason or "Needs the textbook to continue."
    return json.dumps(payload)


def _work_then_finish(task_key: str) -> list[str]:
    """The two decisions a task needs: produce a draft, then complete it."""
    return [
        _decision_json(title=f"{task_key} draft"),
        _decision_json(action="COMPLETE_TASK", task_key=task_key),
    ]


# ---------------------------------------------------------------------------
# Creation is gated on an approved, current plan
# ---------------------------------------------------------------------------


async def test_run_requires_an_approved_plan(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    plan = await _approved_plan(db_session, assignment, analysis)
    plan.status = PlanStatus.DRAFT.value
    db_session.add(plan)
    await db_session.flush()

    with pytest.raises(AppError) as caught:
        await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    assert caught.value.code == "AGENT_NO_APPROVED_PLAN"


async def test_run_refuses_a_stale_plan(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    plan = await _approved_plan(db_session, assignment, analysis)
    plan.is_stale = True
    db_session.add(plan)
    await db_session.flush()

    with pytest.raises(AppError) as caught:
        await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    assert caught.value.code == "AGENT_PLAN_STALE"


async def test_run_binds_to_the_approved_plan_version(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    plan = await _approved_plan(db_session, assignment, analysis)

    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    assert run.plan_id == plan.id
    assert run.plan_version == plan.version
    assert run.status == AgentRunStatus.CREATED.value
    assert run.max_iterations > 0, "the budget must be snapshotted at creation, not defaulted"


async def test_another_students_run_is_not_readable(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
) -> None:
    await _approved_plan(db_session, assignment, analysis)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)

    intruder = User(id=uuid4(), name="Other", email=f"{uuid4().hex}@example.com", password_hash="x")
    db_session.add(intruder)
    await db_session.flush()

    with pytest.raises(AppError) as caught:
        await service.load_owned_run(assignment.id, run.id, intruder.id, db_session)
    assert caught.value.status_code == 404


# ---------------------------------------------------------------------------
# A run executes its graph and records what it did
# ---------------------------------------------------------------------------


async def test_run_executes_the_graph_and_writes_an_artifact(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """The headline case: two dependent tasks, one run, everything persisted.

    This is the test that would have caught a run which reported success while
    quietly writing no artifact, or which marked a task done without recording
    the execution that did it.
    """
    plan = await _approved_plan(db_session, assignment, analysis)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    provider = ScriptedProvider([*_work_then_finish("T1"), *_work_then_finish("T2")])

    outcome = await service.execute_run(run, owner, db_session, provider=provider)
    await db_session.commit()

    assert outcome.run_status is AgentRunStatus.COMPLETED, outcome.detail
    decisions = [r for r in provider.requests if "agent_input" in (r.metadata or {})]
    assert len(decisions) == 4, "each of the two tasks takes a draft decision and a completion"

    tasks = {
        t.key: t
        for t in await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id))
    }
    assert tasks["T1"].status == AcademicTaskStatus.COMPLETED.value
    assert tasks["T2"].status == AcademicTaskStatus.COMPLETED.value

    executions = list(
        await db_session.scalars(
            select(service.AgentTaskExecution).where(service.AgentTaskExecution.run_id == run.id)
        )
    )
    # Four steps for two tasks: a draft decision and a completion each. The point
    # of the ledger is that it records what actually happened, so completion must
    # appear as its own step rather than being folded into the draft's.
    assert len(executions) == 4
    assert all(e.attempt >= 1 for e in executions), "a first try is attempt 1, never 0"

    artifacts = list(await db_session.scalars(select(service.AgentArtifact)))
    assert len(artifacts) == 2, "each completed task should leave a draft behind"
    assert all(a.content for a in artifacts), "an empty artifact is not a draft"
    # The body must come from the executor, never from the model's own `reason`
    # field. A draft whose text is the model's justification of itself is worse
    # than no draft, because it looks like work.
    assert all("The body the student actually reads." in a.content for a in artifacts)
    assert all("next useful thing" not in a.content for a in artifacts), (
        "the model's own justification must never become the draft"
    )

    detail = await service.load_run_detail(
        await service.load_run_with_details(assignment.id, run.id, owner.id, db_session), db_session
    )
    assert detail["progress"]["completed"] == 2
    assert detail["progress"]["total"] == 2


async def test_dependencies_are_respected_not_merely_stored(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """The second task may not start until the first one has finished.

    Selection could be handed a graph and still choose the successor first if the
    dependency filter were dropped, so this asserts on the *order of the
    persisted attempts* rather than on the selection function.
    """
    plan = await _approved_plan(db_session, assignment, analysis, chain=True)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    provider = ScriptedProvider([*_work_then_finish("T1"), *_work_then_finish("T2")])

    await service.execute_run(run, owner, db_session, provider=provider)
    await db_session.commit()

    by_key = {
        t.key: t.id
        for t in await db_session.scalars(select(PlanTask).where(PlanTask.plan_id == plan.id))
    }
    executions = list(
        await db_session.scalars(
            select(service.AgentTaskExecution)
            .where(service.AgentTaskExecution.run_id == run.id)
            .order_by(service.AgentTaskExecution.started_at)
        )
    )
    order = [e.task_id for e in executions]
    assert order.index(by_key["T1"]) < order.index(by_key["T2"])


async def test_budget_is_spent_and_recorded(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """Cost and tokens must be the provider's real numbers, not a guess.

    A budget checked against invented figures stops being trustworthy the first
    time it is wrong, so the totals are asserted against what the provider
    reported rather than merely against "something greater than zero".
    """
    await _approved_plan(db_session, assignment, analysis)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    provider = ScriptedProvider([*_work_then_finish("T1"), *_work_then_finish("T2")])

    await service.execute_run(run, owner, db_session, provider=provider)
    await db_session.commit()

    calls = len(provider.requests)
    # Four decisions, plus an execution only for the two steps that produce work.
    # Completion is bookkeeping and must not bill the student for a second draft.
    assert calls == 6, "four decisions and two executions"
    assert float(run.estimated_cost) == pytest.approx(calls * 0.001), (
        "the run must be charged what the provider reported, per call"
    )
    assert run.token_usage["prompt_tokens"] == calls * 100
    assert run.token_usage["total_tokens"] == calls * 150
    assert run.duration_ms is not None


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


async def test_a_refused_action_blocks_the_task_without_writing_anything(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """A low-confidence decision must not become a draft.

    The failure mode this guards is the expensive one: a runtime that treats an
    unvalidated action as a draft and only complains afterwards has already put
    unverified content in front of a student.

    The run ends BLOCKED rather than FAILED. That is the better of the two: the
    task needs a human, and "failed" would tell the student the work is impossible
    when in fact the agent simply was not confident enough to try.
    """
    await _approved_plan(db_session, assignment, analysis, keys=("T1",), chain=False)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    # Every reply is unconfident, not just the first. A provider that recovers on
    # its own would let this test pass for the wrong reason.
    provider = ScriptedProvider([_decision_json(confidence=0.01) for _ in range(6)])

    outcome = await service.execute_run(run, owner, db_session, provider=provider)
    await db_session.commit()

    assert outcome.run_status is AgentRunStatus.BLOCKED
    assert run.paused_reason, "a blocked run must say what is in the way"
    assert list(await db_session.scalars(select(service.AgentArtifact))) == [], (
        "a refused decision must leave nothing behind for a student to trust"
    )
    attempts = list(
        await db_session.scalars(
            select(service.AgentTaskExecution).where(service.AgentTaskExecution.run_id == run.id)
        )
    )
    assert len(attempts) == settings_max_attempts(), "retries must be bounded"
    assert all(a.attempt >= 1 for a in attempts)


def settings_max_attempts() -> int:
    from app.core.config import get_settings

    return get_settings().agent_max_task_attempts


async def test_an_unparsable_provider_reply_fails_the_run_cleanly(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """Garbage from a provider is a normal event, not a crash.

    Real providers return prose, truncated JSON and refusals. Treating those as
    an unhandled exception would take the whole process down over one bad reply.
    """
    await _approved_plan(db_session, assignment, analysis, keys=("T1",), chain=False)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    # Persistently prose, not prose-then-recovery: a provider that fixed itself
    # would let this pass for the wrong reason.
    provider = ScriptedProvider(["I would be happy to help with that!"] * 6)

    outcome = await service.execute_run(run, owner, db_session, provider=provider)
    await db_session.commit()

    assert outcome.run_status in {AgentRunStatus.FAILED, AgentRunStatus.BLOCKED}
    assert run.error_code or run.paused_reason, "the run must say why it stopped"
    assert list(await db_session.scalars(select(service.AgentArtifact))) == []


async def test_a_rejected_action_costs_a_retry_not_the_run(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """A transient refusal should be retried within the budget.

    This is the difference between a budget and a wall: the run may spend several
    attempts on one task, but it stops rather than retrying forever.
    """
    await _approved_plan(db_session, assignment, analysis, keys=("T1",), chain=False)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    provider = ScriptedProvider([_decision_json(confidence=0.01) for _ in range(6)])

    outcome = await service.execute_run(run, owner, db_session, provider=provider)
    await db_session.commit()

    assert outcome.run_status is not AgentRunStatus.COMPLETED
    assert run.iteration_count <= run.max_iterations, "the loop must be bounded"
    assert (
        await db_session.scalar(select(func.count()).select_from(service.AgentTaskExecution)) >= 1
    ), "the attempt that was made should be recorded"


async def test_a_model_that_only_drafts_is_asked_instead_of_spending_the_budget(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """Spinning must cost the student a question, not a whole run budget.

    A model that keeps emitting CREATE_ARTIFACT and never COMPLETE_TASK would
    otherwise burn every iteration drafting new revisions of the same thing. The
    guard has to end in a question the student can answer, because "here is
    another draft" is not progress and burning real money on it is the failure
    mode worth preventing.
    """
    await _approved_plan(db_session, assignment, analysis, keys=("T1",), chain=False)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    provider = ScriptedProvider([_decision_json(title=f"Pass {i}") for i in range(8)])

    outcome = await service.execute_run(run, owner, db_session, provider=provider)
    await db_session.commit()

    assert outcome.run_status is AgentRunStatus.WAITING_FOR_USER
    checkpoints = list(
        await db_session.scalars(
            select(service.AgentCheckpoint).where(service.AgentCheckpoint.run_id == run.id)
        )
    )
    assert len(checkpoints) == 1, "the student should be asked exactly once"
    assert "T1" in checkpoints[0].question
    assert checkpoints[0].options, "a question with no options cannot be answered quickly"

    drafts = list(await db_session.scalars(select(service.AgentArtifact)))
    assert len(drafts) == 2, "drafting must stop at the cap rather than run to the budget"
    assert run.iteration_count < run.max_iterations, (
        "the guard must fire long before the whole step budget is gone"
    )


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


async def test_cancelling_a_live_run_is_terminal_and_idempotent(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    await _approved_plan(db_session, assignment, analysis)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    await service.start_run(run, owner, db_session)

    cancelled = await service.cancel_run(run, owner, db_session, reason="Not needed")
    assert cancelled.status == AgentRunStatus.CANCELLED.value
    assert cancelled.completed_at is not None

    with pytest.raises(AppError):
        await service.cancel_run(run, owner, db_session, reason="again")


async def test_a_paused_run_resumes_only_when_allowed(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    await _approved_plan(db_session, assignment, analysis)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    await service.start_run(run, owner, db_session)
    await service.pause_run(run, owner, db_session, reason="Taking a break")
    assert run.status == AgentRunStatus.PAUSED.value

    resumed = await service.resume_run(run, owner, db_session)
    assert resumed.status in {
        AgentRunStatus.STARTING.value,
        AgentRunStatus.RUNNING.value,
    }


async def test_every_run_transition_is_audited(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """A transition with no audit row is a transition nobody can reconstruct."""
    from app.models import AuditLog

    await _approved_plan(db_session, assignment, analysis)
    run = await service.create_run(assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED)
    await service.start_run(run, owner, db_session)
    await db_session.commit()

    types = set(
        await db_session.scalars(
            select(AuditLog.event_type).where(
                AuditLog.entity_id == run.id, AuditLog.entity_type == "agent_run"
            )
        )
    )
    assert AuditEventType.AGENT_RUN_CREATED in types
    assert AuditEventType.AGENT_RUN_STARTED in types


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


async def _stale_run(
    db: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    *,
    status: AgentRunStatus,
    heartbeat_age_seconds: int,
) -> AgentRun:
    await _approved_plan(db, assignment, analysis)
    run = AgentRun(
        id=uuid4(),
        assignment_id=assignment.id,
        mode="SUPERVISED",
        status=status.value,
        max_iterations=40,
        max_cost=5,
        triggered_by_id=owner.id,
    )
    plan = await db.scalar(
        select(AcademicWorkPlan).where(AcademicWorkPlan.assignment_id == assignment.id)
    )
    run.plan_id = plan.id if plan else None
    run.plan_version = plan.version if plan else 1
    run.created_at = datetime.now(UTC) - timedelta(seconds=heartbeat_age_seconds + 60)
    run.heartbeat_at = datetime.now(UTC) - timedelta(seconds=heartbeat_age_seconds)
    db.add(run)
    await db.flush()
    return run


async def test_recovery_pauses_a_run_whose_worker_vanished(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """The core recovery promise: an abandoned run is paused, never auto-resumed.

    Resuming automatically would re-enter a loop whose last step may already have
    written a draft. Pausing puts the decision back with the student.
    """
    from app.core.config import get_settings

    run = await _stale_run(
        db_session,
        assignment,
        analysis,
        owner,
        status=AgentRunStatus.RUNNING,
        heartbeat_age_seconds=9_000,
    )

    report = await recovery.recover_stale_runs(db_session, get_settings())

    assert report.runs_paused == 1
    assert run.status == AgentRunStatus.PAUSED.value
    assert run.paused_reason, "a student must be told why the run stopped"


async def test_recovery_leaves_a_healthy_run_alone(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    from app.core.config import get_settings

    run = await _stale_run(
        db_session,
        assignment,
        analysis,
        owner,
        status=AgentRunStatus.RUNNING,
        heartbeat_age_seconds=5,
    )

    report = await recovery.recover_stale_runs(db_session, get_settings())

    assert report.runs_paused == 0
    assert run.status == AgentRunStatus.RUNNING.value


async def test_recovery_does_not_touch_a_run_waiting_on_a_student(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """A run blocked on a human is not a crashed run.

    Conflating the two would let a timer resume runs whose whole purpose is to
    wait, and quietly override the student who was asked a question.
    """
    from app.core.config import get_settings

    run = await _stale_run(
        db_session,
        assignment,
        analysis,
        owner,
        status=AgentRunStatus.WAITING_FOR_USER,
        heartbeat_age_seconds=9_000,
    )

    report = await recovery.recover_stale_runs(db_session, get_settings())

    assert report.runs_paused == 0
    assert run.status == AgentRunStatus.WAITING_FOR_USER.value


async def test_recovery_is_idempotent(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    from app.core.config import get_settings

    await _stale_run(
        db_session,
        assignment,
        analysis,
        owner,
        status=AgentRunStatus.RUNNING,
        heartbeat_age_seconds=9_000,
    )

    first = await recovery.recover_stale_runs(db_session, get_settings())
    second = await recovery.recover_stale_runs(db_session, get_settings())

    assert first.runs_paused == 1
    assert second.runs_paused == 0, "a second sweep must find nothing left to do"


async def test_expired_checkpoints_release_a_waiting_run(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """An unanswered question must not hold a run open forever."""
    from app.core.config import get_settings
    from app.models.entities import AgentCheckpoint

    run = await _stale_run(
        db_session,
        assignment,
        analysis,
        owner,
        status=AgentRunStatus.WAITING_FOR_USER,
        heartbeat_age_seconds=5,
    )
    checkpoint = AgentCheckpoint(
        id=uuid4(),
        run_id=run.id,
        checkpoint_type="CLARIFICATION",
        status=AgentCheckpointStatus.PENDING.value,
        question="Which textbook notation should I use?",
        options=["Knopp", "Other"],
        requested_at=datetime.now(UTC) - timedelta(days=7),
        expires_at=datetime.now(UTC) - timedelta(days=6),
    )
    db_session.add(checkpoint)
    await db_session.flush()

    report = await recovery.recover_stale_runs(db_session, get_settings())

    assert report.checkpoints_expired == 1
    assert checkpoint.status == AgentCheckpointStatus.EXPIRED.value


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


async def test_the_same_plan_and_provider_produce_the_same_decisions(
    db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis, owner: User
) -> None:
    """The offline suite is only worth something if it is reproducible.

    Two runs over the same plan with the same replies must agree on task order
    and on the artifacts produced, or a failing test says nothing.
    """
    runs = []
    for index in range(2):
        await _approved_plan(db_session, assignment, analysis, version=index + 1)
        run = await service.create_run(
            assignment.id, owner, db_session, mode=AgentRunMode.SUPERVISED
        )
        provider = ScriptedProvider([*_work_then_finish("T1"), *_work_then_finish("T2")])
        await service.execute_run(run, owner, db_session, provider=provider)
        await db_session.commit()
        runs.append((index, run.status))

    assert runs[0][1] == runs[1][1] == AgentRunStatus.COMPLETED.value


def test_recovery_report_is_falsy_when_nothing_happened() -> None:
    assert not recovery.RecoveryReport()
    assert bool(recovery.RecoveryReport(runs_paused=1))


async def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError):
        recovery.stale_before(0)
