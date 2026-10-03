"""The single-writer guarantee must not be bought with a held lock.

The pre-Phase-5.5 implementation took a ``SELECT ... FOR UPDATE`` on the run
before entering the execution loop and committed only when the run stopped. A row
lock on the run and a pooled database connection were therefore pinned for the
entire run, including every provider call, so a slow step held both for its whole
duration. That is the workload a request-scoped pool is least able to absorb.

The fix replaces the held lock with a compare-and-swap that is committed before
any provider call. These tests pin the two properties that change makes real:

* a claim is durable on its own, so nothing waits on the caller, and
* exactly one concurrent writer can win a claim.

The second is the only thing that makes "one run, one writer" true. A bare
``lock_version = lock_version + 1`` read back by two writers would let both
believe they had claimed the same iteration.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.db.base import Base
from app.models import User
from app.models.entities import (
    AcademicWorkPlan,
    AgentRun,
    Assignment,
    AssignmentAnalysis,
    Course,
    PlanTask,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import (
    AcademicTaskStatus,
    AcademicTaskType,
    AgentRunStatus,
    PlanStatus,
)
from app.modules.agent import service as agent_service
from app.modules.agent.service import RunClaimLost, claim_step
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# ---------------------------------------------------------------------------
# Fixtures: the minimum shape claim_step cares about
# ---------------------------------------------------------------------------


@pytest.fixture
async def owner(db_session: AsyncSession) -> User:
    row = User(id=uuid4(), name="Student", email=f"{uuid4().hex}@example.com", password_hash="x")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def assignment(db_session: AsyncSession, owner: User) -> Assignment:
    space = Workspace(id=uuid4(), name="Workspace", owner_id=owner.id)
    db_session.add(space)
    db_session.add(WorkspaceMember(workspace_id=space.id, user_id=owner.id, role="OWNER"))
    course = Course(id=uuid4(), workspace_id=space.id, name="Analysis", code="MATH201")
    db_session.add(course)
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


@pytest.fixture
async def plan(db_session: AsyncSession, assignment: Assignment, analysis: AssignmentAnalysis):
    """An approved plan with one pending task.

    ``execute_run`` fails a run whose plan is missing before it reaches its first
    claim, so the loop is untestable without one.
    """
    row = AcademicWorkPlan(
        id=uuid4(),
        assignment_id=assignment.id,
        analysis_id=analysis.id,
        version=1,
        reason="GENERATED",
        trigger="GENERATED",
        title="Plan",
        summary="",
        status=PlanStatus.APPROVED.value,
        objectives=[],
        payload={},
        approved_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.flush()
    for position, key in enumerate(("T1", "T2")):
        db_session.add(
            PlanTask(
                id=uuid4(),
                plan_id=row.id,
                key=key,
                title=f"Task {key}",
                description="Do the work.",
                type=AcademicTaskType.RESEARCH.value,
                status=AcademicTaskStatus.PENDING.value,
                priority="HIGH",
                position=position,
                acceptance_criteria=[],
                resources=[],
            )
        )
    await db_session.flush()
    return row


@pytest.fixture
async def run_row(
    db_session: AsyncSession, assignment: Assignment, plan: AcademicWorkPlan, owner: User
) -> AgentRun:
    row = AgentRun(
        id=uuid4(),
        assignment_id=assignment.id,
        plan_id=plan.id,
        plan_version=1,
        status=AgentRunStatus.RUNNING.value,
        mode="SUPERVISED",
        max_iterations=5,
        max_cost=5,
        iteration_count=0,
        lock_version=0,
        triggered_by_id=owner.id,
    )
    db_session.add(row)
    await db_session.flush()
    return row


# ---------------------------------------------------------------------------
# The claim is durable on its own
# ---------------------------------------------------------------------------

async def test_a_claim_is_committed_before_the_caller_proceeds(tmp_path: Path) -> None:
    """The claim must be durable the moment ``claim_step`` returns.

    This is the property the whole change rests on. While the claim sat inside an
    uncommitted transaction, a second writer read the old version, concluded
    nobody had taken this iteration, and took it too.

    The suite's fixture is an in-memory SQLite pool that hands every session the
    same connection, so it cannot observe visibility at all. This test therefore
    uses a file-backed database throughout, where a second engine is genuinely a
    second connection with its own transaction - the only honest way to ask
    "would another writer see this yet?".
    """
    path = tmp_path / "claim.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    run_id = uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as writer:
        run = AgentRun(
            id=run_id,
            assignment_id=uuid4(),
            plan_id=None,
            plan_version=1,
            status=AgentRunStatus.RUNNING.value,
            mode="SUPERVISED",
            max_iterations=5,
            max_cost=5,
            iteration_count=0,
            lock_version=0,
        )
        writer.add(run)
        await writer.commit()

        await claim_step(run, writer)

    # A separate engine, a separate connection, its own transaction.
    async with AsyncSession(engine, expire_on_commit=False) as observer:
        seen = await observer.scalar(select(AgentRun.lock_version).where(AgentRun.id == run_id))
        seen_iterations = await observer.scalar(
            select(AgentRun.iteration_count).where(AgentRun.id == run_id)
        )
    await engine.dispose()

    assert seen == 1, "the claim was not committed; a second writer could take this iteration"
    assert seen_iterations == 1, "the claimed iteration must be counted durably too"


async def test_a_claim_blocks_a_writer_on_a_genuinely_separate_connection(
    tmp_path: Path,
) -> None:
    """The end-to-end guarantee, with no shared connection to hide behind.

    Two writers, two connections, both reading version 0. Exactly one may
    proceed. This is the race the CAS exists to settle, reproduced for real rather
    than simulated with a stale in-memory object.
    """
    path = tmp_path / "race.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    run_id = uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        seed.add(
            AgentRun(
                id=run_id,
                assignment_id=uuid4(),
                plan_id=None,
                plan_version=1,
                status=AgentRunStatus.RUNNING.value,
                mode="SUPERVISED",
                max_iterations=5,
                max_cost=5,
                iteration_count=0,
                lock_version=0,
            )
        )
        await seed.commit()

    async def attempt() -> bool:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            loaded = await session.get(AgentRun, run_id)
            assert loaded is not None
            try:
                await claim_step(loaded, session)
            except RunClaimLost:
                return False
            return True

    winners = await asyncio.gather(attempt(), attempt())

    async with AsyncSession(engine, expire_on_commit=False) as check:
        final = await check.scalar(select(AgentRun.lock_version).where(AgentRun.id == run_id))
    await engine.dispose()

    assert sum(winners) == 1, f"exactly one writer may claim; got {sum(winners)}"
    assert final == 1, "a lost claim must not advance the version"


async def test_a_claim_advances_the_version_by_exactly_one(
    db_session: AsyncSession, run_row: AgentRun
) -> None:
    first = await claim_step(run_row, db_session)
    assert first == 1
    second = await claim_step(run_row, db_session)
    assert second == 2


async def test_a_claim_refreshes_the_heartbeat(
    db_session: AsyncSession, run_row: AgentRun
) -> None:
    """A claim is also how a long run proves it is still alive."""
    run_row.heartbeat_at = None
    await claim_step(run_row, db_session)
    assert run_row.heartbeat_at is not None


# ---------------------------------------------------------------------------
# Exactly one writer wins
# ---------------------------------------------------------------------------


async def test_a_second_writer_cannot_claim_the_same_iteration(
    db_session: AsyncSession, run_row: AgentRun
) -> None:
    """The ``WHERE lock_version = expected`` predicate is the guarantee.

    Both writers read version 0. One executes the UPDATE and gets
    ``rowcount == 1``; the other's predicate no longer matches, so it must be
    told it lost rather than proceeding to run a second executor over the same
    plan.
    """
    run_id = run_row.id
    await claim_step(run_row, db_session)

    loser = AgentRun(id=run_id, assignment_id=run_row.assignment_id)
    loser.lock_version = 0  # what the losing writer still believes

    with pytest.raises(RunClaimLost):
        await claim_step(loser, db_session)


async def _version_of(db: AsyncSession, run_id: object) -> int | None:
    return await db.scalar(select(AgentRun.lock_version).where(AgentRun.id == run_id))


async def _beat_of(db: AsyncSession, run_id: object) -> datetime | None:
    return await db.scalar(select(AgentRun.heartbeat_at).where(AgentRun.id == run_id))


async def test_a_lost_claim_does_not_disturb_the_winner(
    db_session: AsyncSession, run_row: AgentRun
) -> None:
    """Failing to claim must leave the winning version untouched."""
    run_id = run_row.id
    await claim_step(run_row, db_session)
    winner_version = await _version_of(db_session, run_id)

    loser = AgentRun(id=run_id, assignment_id=run_row.assignment_id)
    loser.lock_version = 0
    with pytest.raises(RunClaimLost):
        await claim_step(loser, db_session)

    # Re-read rather than inspecting the ORM object: a failed claim rolls the
    # session back, which expires every attribute on it.
    assert await _version_of(db_session, run_id) == winner_version


async def test_the_loser_gets_no_heartbeat_bump(
    db_session: AsyncSession, run_row: AgentRun
) -> None:
    """Otherwise a run that never won an iteration still looks alive."""
    run_id = run_row.id
    run_row.heartbeat_at = None
    await db_session.flush()
    await claim_step(run_row, db_session)
    first_beat = await _beat_of(db_session, run_id)
    assert first_beat is not None

    loser = AgentRun(id=run_id, assignment_id=run_row.assignment_id)
    loser.lock_version = 0
    with pytest.raises(RunClaimLost):
        await claim_step(loser, db_session)

    assert await _beat_of(db_session, run_id) == first_beat


# ---------------------------------------------------------------------------
# The loop itself
# ---------------------------------------------------------------------------


async def test_execute_run_survives_being_claimed_out_from_under_it(
    db_session: AsyncSession, run_row: AgentRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run superseded mid-loop reports BUSY instead of racing the winner.

    Returning rather than raising is deliberate: the caller is a request handler
    that should answer "someone else is working on this", not 500 because a
    background worker got there first.
    """
    real_claim = agent_service.claim_step
    calls = {"n": 0}

    async def racing_claim(run: AgentRun, db: AsyncSession) -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            # Another worker advances the run between our read and our claim.
            await db.execute(
                AgentRun.__table__.update()
                .where(AgentRun.id == run.id)
                .values(lock_version=(run.lock_version or 0) + 5)
            )
            run.lock_version = run.lock_version  # keep the stale value we believe
        return await real_claim(run, db)

    monkeypatch.setattr(agent_service, "claim_step", racing_claim)

    outcome = await agent_service.execute_run(run_row, _owner(run_row), db_session, max_steps=5)

    assert outcome.kind == "BUSY"
    assert "already advancing" in outcome.detail


def _owner(run: AgentRun) -> User:
    """Rebuild the minimal User the failure path reads.

    ``execute_run`` needs an identity for audit rows only, so this avoids
    querying the session for something the run already records.
    """
    return User(id=run.triggered_by_id, name="Student", email="s@example.com", password_hash="x")