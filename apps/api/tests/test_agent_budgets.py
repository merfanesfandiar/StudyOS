"""A budget that cannot be evaluated is not a budget.

The agent runtime shipped with ``max_cost_per_run``, ``max_cost_per_step`` and a
``decision_token_ratio``, all configurable, all enforced somewhere. Two of the
three could never fire:

* ``_charge_run`` accumulated ``response.estimated_cost``, and no provider ever
  set that field, so a run's cost column stayed at exactly zero forever. The
  pre-call check then compared ``0 + estimate`` against the ceiling and passed,
  every time, for every model.
* the per-step check substituted ``max_cost_per_step / 2`` as its "estimate", a
  number derived from the limit rather than from the model. It could only ever
  be half the limit, so it could breach only a limit that was itself zero.

Unpriced models were indistinguishable from free ones. This file pins the
behaviour that replaced that: a run records what it actually cost, and the token
ceilings - previously described in the module docstring as enforced but never
implemented anywhere - stop a run before the call, not after the invoice.

Each test here was checked to fail against the pre-fix code.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from app.ai.provider import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ModelPricing,
    approximate_tokens,
)
from app.ai.providers.mock import MockLLMProvider
from app.core.config import get_settings
from app.models import User
from app.models.entities import (
    AcademicWorkPlan,
    AgentRun,
    AgentTaskExecution,
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
    AgentExecutionStatus,
    AgentRunStatus,
    PlanStatus,
)
from app.modules.agent.limits import (
    AgentLimits,
    BudgetExceeded,
    assert_input_token_budget,
    assert_priced_model,
    assert_token_budget,
    assert_tool_run_budget,
    estimate_step_cost,
)
from app.modules.agent.service import (
    _charge_run,
    _decision_output_tokens,
    _gate_provider_call,
)
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

#: Deliberately steep. At this price a 4,000-token output costs 6 cents, so a
#: default 1.00 per-step ceiling is not breached by accident and a test that sets
#: a small ceiling is testing the ceiling, not the arithmetic.
PRICE = ModelPricing(prompt_per_1k=0.005, completion_per_1k=0.015)
MOCK_MODEL = "mock-academic-analyzer-v1"


@pytest.fixture
def priced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a price for the mock model."""
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "llm_pricing",
        {MOCK_MODEL: {"prompt": 0.005, "completion": 0.015}},
    )


@pytest.fixture
def unpriced(monkeypatch: pytest.MonkeyPatch) -> None:
    """No price for anything, and a policy that admits it."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_pricing", {})
    monkeypatch.setattr(settings, "llm_unpriced_model_policy", "record")


def _request(text: str = "Short.") -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role="user", content=text),),
        response_schema={"type": "object"},
        prompt_version="test",
    )


def _limits(**overrides: object) -> AgentLimits:
    base: dict[str, object] = {
        "max_iterations": 5,
        "max_task_attempts": 3,
        "max_consecutive_failures": 3,
        "max_cost_per_run": Decimal("1.00"),
        "max_cost_per_step": Decimal("1.00"),
        "max_output_tokens_per_step": 4_000,
        "max_input_tokens_per_step": 32_000,
        "max_tokens_per_run": 400_000,
        "step_timeout_seconds": 30.0,
        "max_artifacts": 20,
        "retry_backoff_seconds": 0.0,
        "checkpoint_ttl_seconds": 900.0,
        "max_tool_calls_per_step": 4,
        "max_tool_calls_per_run": 60,
        "decision_token_ratio": 0.5,
    }
    base.update(overrides)
    return AgentLimits(**base)  # type: ignore[arg-type]


def _run_row(**overrides: object) -> AgentRun:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "assignment_id": uuid.uuid4(),
        "plan_id": uuid.uuid4(),
        "plan_version": 1,
        "status": AgentRunStatus.RUNNING.value,
        "mode": "SUPERVISED",
        "max_iterations": 5,
        "max_cost": Decimal("1.00"),
        "iteration_count": 0,
        "lock_version": 0,
    }
    fields.update(overrides)
    return AgentRun(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A run reports what it actually cost
# ---------------------------------------------------------------------------


async def test_a_provider_call_records_a_real_cost(priced: None) -> None:
    """The field the cost guardrail reads must not stay None.

    Load-bearing: with ``estimated_cost`` left unset by the provider this is
    ``None`` and every cost assertion below is vacuously satisfied forever.
    """
    provider = MockLLMProvider(model=MOCK_MODEL)
    response = await provider.complete(_request("A representative length prompt."))

    assert response.estimated_cost is not None
    assert response.estimated_cost > 0


async def test_an_unpriced_model_reports_no_cost_rather_than_zero(
    unpriced: None,
) -> None:
    """None means unknown. Zero would be a lie an operator could act on."""
    provider = MockLLMProvider(model=MOCK_MODEL)
    response = await provider.complete(_request())

    assert response.estimated_cost is None


def test_a_zero_cost_response_is_still_charged(priced: None) -> None:
    """``if response.estimated_cost`` skipped zero.

    Free-tier and cached responses cost exactly zero, and that is a real cost that
    belongs in the total. The falsy check treated them as "no data" and left the
    accumulated total untouched.
    """
    run = _run_row()
    _charge_run(
        run,
        LLMResponse(
            content="{}",
            provider="mock",
            model=MOCK_MODEL,
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            estimated_cost=0.0,
        ),
    )

    assert Decimal(str(run.estimated_cost)) == Decimal("0")
    # Tokens must still be accumulated, or a free call would look like no call.
    assert (run.token_usage or {}).get("total_tokens") == 15


# ---------------------------------------------------------------------------
# Budgets stop the run before the call
# ---------------------------------------------------------------------------


def test_the_run_token_ceiling_projects_the_completion_too(priced: None) -> None:
    """Checking only the prompt lets one call overspend its remaining budget.

    397,000 tokens spent against a 400,000 ceiling leaves 3,000. A 2,000-token
    prompt looks affordable on its own, and it is only the 4,000-token completion
    allowance that makes the call a breach. A prompt-only check passes it, and the
    run finishes 1,000 tokens over the budget it was promised.
    """
    spent, prompt, ceiling = 397_000, 2_000, 4_000

    # The prompt alone fits. This is the check that has to keep passing for the
    # projection below to mean anything.
    assert spent + prompt < 400_000

    with pytest.raises(BudgetExceeded) as caught:
        assert_token_budget(
            _limits(max_tokens_per_run=400_000, max_output_tokens_per_step=ceiling),
            spent,
            prompt,
        )

    assert caught.value.code == "AGENT_TOKEN_LIMIT"


def test_an_oversized_prompt_is_refused_by_size_not_by_budget(priced: None) -> None:
    """One oversized prompt is a bug, not a run that ran out of money."""
    with pytest.raises(BudgetExceeded) as caught:
        assert_input_token_budget(_limits(max_input_tokens_per_step=32_000), 33_000)

    assert caught.value.code == "AGENT_INPUT_TOO_LARGE"


def test_an_unpriced_model_is_refused_when_the_deployment_requires_prices(
    unpriced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator's guarantee must be real or advisory, not accidental."""
    monkeypatch.setattr(get_settings(), "llm_unpriced_model_policy", "refuse")

    with pytest.raises(BudgetExceeded) as caught:
        assert_priced_model(None, MOCK_MODEL)

    assert caught.value.code == "AGENT_MODEL_UNPRICED"


def test_an_unpriced_model_is_permitted_when_the_policy_is_record(
    unpriced: None,
) -> None:
    """Recording is the default so an unconfigured deployment still works."""
    assert_priced_model(None, MOCK_MODEL)


def test_the_step_estimate_uses_the_configured_price(priced: None) -> None:
    """Not the ceiling divided by two."""
    cost = estimate_step_cost(PRICE, prompt_tokens=1_000, output_tokens=1_000)

    assert cost == Decimal("0.02")


def test_the_gate_blocks_a_run_that_cannot_afford_the_call(priced: None) -> None:
    """The whole point: the run stops rather than discovering it on the invoice.

    Load-bearing: ``run.estimated_cost`` used to stay zero because nothing set
    it, so this ceiling was never approached and never fired.
    """
    run = _run_row()
    run.estimated_cost = Decimal("0.999")
    run.token_usage = {"total_tokens": 1_000}
    provider = MockLLMProvider(model=MOCK_MODEL)

    with pytest.raises(BudgetExceeded) as caught:
        _gate_provider_call(
            run,
            _limits(max_cost_per_run=Decimal("1.00"), max_cost_per_step=Decimal("1.00")),
            provider,
            _request("A short prompt."),
        )

    assert caught.value.code == "AGENT_COST_LIMIT"


def test_the_gate_permits_a_call_a_priced_run_can_afford(priced: None) -> None:
    """A budget that blocks everything is as broken as one that blocks nothing."""
    run = _run_row()
    run.token_usage = {"total_tokens": 1_000}

    _gate_provider_call(run, _limits(), MockLLMProvider(model=MOCK_MODEL), _request())


def test_the_gate_refuses_uncosted_work_when_prices_are_required(
    unpriced: None,
) -> None:
    """A run with an empty cost column while spending money is unauditable."""
    monkey = get_settings()
    monkey.llm_unpriced_model_policy = "refuse"
    try:
        with pytest.raises(BudgetExceeded) as caught:
            _gate_provider_call(
                _run_row(), _limits(), MockLLMProvider(model=MOCK_MODEL), _request()
            )
    finally:
        monkey.llm_unpriced_model_policy = "record"

    assert caught.value.code == "AGENT_MODEL_UNPRICED"


def test_a_decision_gets_the_smaller_share_of_the_output_budget() -> None:
    """``decision_token_ratio`` was configurable and unused.

    Every step reserved the full output ceiling, so the decision that merely
    *approved* a task reserved as much output as the task itself.
    """
    limits = _limits(max_output_tokens_per_step=4_000, decision_token_ratio=0.4)

    assert _decision_output_tokens(limits) == 1_600


def test_a_tiny_ratio_still_leaves_room_to_answer() -> None:
    """A decision too small to express is a worse failure than a slight overrun."""
    limits = _limits(max_output_tokens_per_step=400, decision_token_ratio=0.1)

    assert _decision_output_tokens(limits) == 256


def test_the_run_tool_ceiling_is_checked_across_a_whole_run() -> None:
    """A per-step limit cannot see a run that is modest every step but endless."""
    limits = _limits(max_tool_calls_per_run=3)

    assert_tool_run_budget(limits, 2)  # still inside the ceiling

    with pytest.raises(BudgetExceeded) as caught:
        assert_tool_run_budget(limits, 3)

    assert caught.value.code == "AGENT_TOOL_RUN_LIMIT"


def test_a_zero_run_tool_ceiling_means_unbounded() -> None:
    """Zero disables the ceiling, matching the cost budgets' convention."""
    assert_tool_run_budget(_limits(max_tool_calls_per_run=0), 10_000)


def test_the_shared_estimator_measures_the_actual_prompt() -> None:
    """It must look at the messages, not at application metadata.

    The mock originally counted the metadata JSON it never sends, so the prompt
    the budget gate measured and the prompt the charge described were different
    numbers on every run.
    """
    request = _request("x" * 4_000)

    assert approximate_tokens(request.messages) == 1_000
    assert approximate_tokens(request.messages) != approximate_tokens(()) + 1 - 1


# ---------------------------------------------------------------------------
# Deleting a task must preserve the attempt history it exists for
# ---------------------------------------------------------------------------


@pytest.fixture
async def file_backed(tmp_path: Path) -> AsyncSession:
    """A file-backed database with FK enforcement on.

    Needed because the deletion test is about what the *database* does with
    ``ON DELETE SET NULL``, and the shared in-memory fixture cannot exercise a
    cross-session delete.
    """
    from app.db.base import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}")
    # Mirrors app/db/session.py. Without this the ON DELETE clause is never
    # executed at all and the test below passes for the wrong reason.
    event.listen(engine.sync_engine, "connect", _enable_fk)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


def _enable_fk(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def test_deleting_a_task_keeps_its_attempt_history(file_backed: AsyncSession) -> None:
    """``SET NULL`` on a NOT NULL column does not preserve anything.

    It blocks the delete. Migration ``0007`` set the action and left the column
    non-nullable, so the guarantee that motivated the change - "keep the failure
    evidence" - was in fact a guarantee that a task could never be deleted. The
    migration round-trip test did not catch it because it deletes no rows: it
    proves the schema migrates, not that the constraint permits the operation it
    was written for.
    """
    user = User(id=uuid.uuid4(), name="S", email=f"{uuid.uuid4().hex}@e.com", password_hash="x")
    space = Workspace(id=uuid.uuid4(), name="W", owner_id=user.id)
    course = Course(id=uuid.uuid4(), workspace_id=space.id, name="C", code="M1")
    assignment = Assignment(
        id=uuid.uuid4(),
        workspace_id=space.id,
        course_id=course.id,
        title="A",
        description="d",
        deadline=datetime.now(UTC) + timedelta(days=7),
    )
    analysis = AssignmentAnalysis(
        id=uuid.uuid4(),
        assignment_id=assignment.id,
        analysis_version=1,
        revision=1,
        specification_version=1,
        specification_hash="a" * 64,
        idempotency_key="k" * 64,
        prompt_version="p",
        provider="mock",
        model=MOCK_MODEL,
        summary="s",
        confidence=0.8,
        payload={},
    )
    plan = AcademicWorkPlan(
        id=uuid.uuid4(),
        assignment_id=assignment.id,
        analysis_id=analysis.id,
        version=1,
        reason="GENERATED",
        trigger="GENERATED",
        title="P",
        summary="",
        status=PlanStatus.APPROVED.value,
        objectives=[],
        payload={},
        approved_at=datetime.now(UTC),
    )
    task = PlanTask(
        id=uuid.uuid4(),
        plan_id=plan.id,
        key="T1",
        title="T",
        description="d",
        type=AcademicTaskType.RESEARCH.value,
        status=AcademicTaskStatus.PENDING.value,
        priority="HIGH",
        position=0,
        acceptance_criteria=[],
        resources=[],
    )
    run = _run_row(assignment_id=assignment.id, plan_id=plan.id)
    execution = AgentTaskExecution(
        id=uuid.uuid4(),
        run_id=run.id,
        task_id=task.id,
        task_key="T1",
        attempt=1,
        status=AgentExecutionStatus.FAILED.value,
    )
    file_backed.add_all(
        [user, space, WorkspaceMember(workspace_id=space.id, user_id=user.id, role="OWNER"), course,
         assignment, analysis, plan, task, run, execution]
    )
    await file_backed.commit()

    await file_backed.delete(task)
    await file_backed.commit()

    surviving = await file_backed.scalar(
        select(AgentTaskExecution).where(AgentTaskExecution.id == execution.id)
    )
    assert surviving is not None, "the attempt history was destroyed with the task"
    assert surviving.task_id is None, "a non-nullable SET NULL leaves a dangling reference"
    # Still attributable without the task row.
    assert surviving.task_key == "T1"