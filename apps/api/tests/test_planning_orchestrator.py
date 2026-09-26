"""How the planning orchestrator behaves when the model misbehaves.

The deterministic engine is the floor the product stands on, so the interesting
question is never "does a good model produce a good plan" but "what happens when
the model is unreachable, unparseable, or confidently wrong". These tests hold
that line: a fallback is always a stated fallback, telemetry always says who
actually produced the plan, and a failure with fallback switched off is an error
rather than a silent downgrade.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.ai.errors import LLMError, LLMUnavailableError
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage
from app.models import (
    Assignment,
    AssignmentAnalysis,
    Course,
    PlanningRun,
    User,
    Workspace,
)
from app.models.enums import ComplexityLevel, ModelTier, PlanningRunStatus, PlanningStyle
from app.modules.planning.contract_forge import contracts_for_fixtures
from app.modules.planning.orchestrator import generate_plan
from app.modules.planning.planner import build_planning_preferences
from app.schemas.analysis import PlanningContractResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Providers that fail in the specific ways a real one does
# ---------------------------------------------------------------------------


class _BrokenProvider(LLMProvider):
    """A provider that is simply not there."""

    name = "broken"
    model = "broken-model-v1"

    def __init__(self, error: LLMError | None = None) -> None:
        self.error = error or LLMUnavailableError("no route to host")
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        raise self.error


class _GarbageProvider(LLMProvider):
    """A provider that answers, with something that is not a plan."""

    name = "garbage"
    model = "garbage-model-v1"

    def __init__(self, content: str = "I think you should just start writing.") -> None:
        self.content = content
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content=self.content,
            provider=self.name,
            model=self.model,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class _CyclicProvider(_GarbageProvider):
    """A provider that returns a structurally valid plan with a cycle in it."""

    def __init__(self, contract: PlanningContractResponse) -> None:
        payload = {
            "title": "Cyclic plan",
            "summary": "A plan whose tasks depend on each other.",
            "objectives": [],
            "estimated_effort": "MEDIUM",
            "min_minutes": 60,
            "max_minutes": 90,
            "tasks": [
                {
                    "key": "A",
                    "title": "First",
                    "description": "",
                    "type": "READ",
                    "priority": "MEDIUM",
                    "position": 0,
                    "estimated_effort": "LOW",
                    "min_minutes": 30,
                    "max_minutes": 45,
                    "depends_on": ["B"],
                    "related_requirements": [],
                    "related_deliverables": [],
                },
                {
                    "key": "B",
                    "title": "Second",
                    "description": "",
                    "type": "WRITE",
                    "priority": "MEDIUM",
                    "position": 1,
                    "estimated_effort": "LOW",
                    "min_minutes": 30,
                    "max_minutes": 45,
                    "depends_on": ["A"],
                    "related_requirements": [],
                    "related_deliverables": [],
                },
            ],
            "milestones": [],
            "verification_points": [],
            "risks": [],
        }
        super().__init__(json.dumps(payload))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def contract() -> PlanningContractResponse:
    return contracts_for_fixtures([])[0][1]


@pytest.fixture
def preferences():
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


async def _run(
    db: AsyncSession,
    *,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
    provider: LLMProvider,
    **kwargs,
):
    from app.ai.registry import ModelSelection

    selection = ModelSelection(
        tier=ModelTier.ADVANCED,
        model=provider.model,
        reason="test",
        confidence=1.0,
        complexity=ComplexityLevel.MEDIUM,
    )
    return await generate_plan(
        db,
        assignment=assignment,
        analysis=analysis,
        contract=contract,
        provider=provider,
        selection=selection,
        preferences=preferences,
        user_id=owner.id,
        fallback_enabled=kwargs.pop("fallback_enabled", True),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_an_unreachable_model_falls_back_and_says_so(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """The student still gets a plan, and the run records that it was not the model's."""
    provider = _BrokenProvider()
    result = await _run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        owner=owner,
        contract=contract,
        preferences=preferences,
        provider=provider,
    )

    assert provider.calls == 1, "the model must actually be asked before falling back"
    assert result.used_fallback is True
    assert result.plan.payload["used_fallback"] is True
    assert result.graph.violations == []
    assert any("failed" in warning for warning in result.plan.payload["rejection_reasons"])


async def test_a_timeout_is_a_fallback_not_a_crash(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """A timeout is the most common real failure, so it is tested on its own."""
    from app.ai.errors import LLMTimeoutError

    provider = _BrokenProvider(LLMTimeoutError("took too long"))
    result = await _run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        owner=owner,
        contract=contract,
        preferences=preferences,
        provider=provider,
    )
    assert result.used_fallback is True
    assert "LLM_TIMEOUT" in " ".join(result.plan.payload["rejection_reasons"])


async def test_an_unparseable_answer_falls_back(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """Prose instead of JSON is a fallback, not a plan."""
    result = await _run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        owner=owner,
        contract=contract,
        preferences=preferences,
        provider=_GarbageProvider(),
    )
    assert result.used_fallback is True
    assert result.graph.violations == []


async def test_a_valid_looking_but_cyclic_answer_is_refused(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """A cycle is the failure mode a schema check cannot see."""
    provider = _CyclicProvider(contract)
    result = await _run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        owner=owner,
        contract=contract,
        preferences=preferences,
        provider=provider,
    )
    assert result.used_fallback is True
    assert result.graph.violations == []
    reasons = " ".join(result.plan.payload["rejection_reasons"]).lower()
    assert "cycle" in reasons or "circular" in reasons


async def test_fallback_disabled_surfaces_the_provider_failure(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """A configuration that forbids the floor must fail loudly, not quietly degrade."""
    with pytest.raises(LLMError):
        await _run(
            db_session,
            assignment=assignment,
            analysis=analysis,
            owner=owner,
            contract=contract,
            preferences=preferences,
            provider=_BrokenProvider(),
            fallback_enabled=False,
        )

    runs = list(await db_session.scalars(select(PlanningRun)))
    assert runs, "a run that failed must still be recorded"
    run = runs[-1]
    assert run.status == PlanningRunStatus.FAILED.value
    assert run.completed_at is not None
    assert run.error_code == "LLM_UNAVAILABLE"
    assert run.error_message


async def test_fallback_disabled_also_refuses_an_invalid_proposal(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """Invalid output is a rejection, not merely a bad answer."""
    with pytest.raises(LLMError):
        await _run(
            db_session,
            assignment=assignment,
            analysis=analysis,
            owner=owner,
            contract=contract,
            preferences=preferences,
            provider=_GarbageProvider(),
            fallback_enabled=False,
        )


async def test_run_telemetry_records_the_actual_producer(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """A fallback must be legible in the run record, not only in the response."""
    await _run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        owner=owner,
        contract=contract,
        preferences=preferences,
        provider=_BrokenProvider(),
    )
    run = (await db_session.scalars(select(PlanningRun))).one()
    assert run.status == PlanningRunStatus.SUCCEEDED.value
    assert run.completed_at is not None
    assert run.duration_ms is not None and run.duration_ms >= 0
    assert run.output_hash
    assert run.error_code is None
    assert run.provider == "broken", "the attempted provider is what ran"


async def test_an_explicit_idempotency_key_makes_no_second_call(
    db_session: AsyncSession,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    owner: User,
    contract: PlanningContractResponse,
    preferences,
) -> None:
    """A retried request costs nothing: no model call, no second version."""
    provider = _GarbageProvider()
    first = await _run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        owner=owner,
        contract=contract,
        preferences=preferences,
        provider=provider,
        idempotency_key="retry-me-please",
    )
    assert provider.calls == 1
    assert first.run_id is not None

    second = await _run(
        db_session,
        assignment=assignment,
        analysis=analysis,
        owner=owner,
        contract=contract,
        preferences=preferences,
        provider=provider,
        idempotency_key="retry-me-please",
    )
    assert provider.calls == 1, "the repeat must not reach the model"
    assert second.plan.id == first.plan.id
    assert second.run_id is None, "no run happened, so there is no run id to report"
