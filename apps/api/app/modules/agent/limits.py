"""Effort budgets for one agent run.

The runtime has no capability limits because it has no dangerous capabilities.
What it has are *effort* limits: a bounded number of steps, retries, tokens and
currency. These exist so that a confused model, a cyclic plan or a provider that
keeps failing produces a run that stops with an explanation rather than a run
that quietly consumes money.

Every check raises :class:`BudgetExceeded`, which the runtime converts into a
structured failure with a category the retry policy understands. A budget is
never enforced by returning a truncated result and hoping the caller notices —
silence is how runaway loops go unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.ai.provider import LLMUsage, ModelPricing
from app.core.config import Settings, get_settings
from app.models.enums import AgentFailureCategory, AgentRunStatus


class BudgetExceeded(Exception):
    """A run tried to spend more than it was allowed.

    Carries a failure category so the policy can distinguish "we are out of
    budget" (never retryable) from "the provider was unavailable" (retryable).
    """

    def __init__(
        self,
        code: str,
        message: str,
        category: AgentFailureCategory = AgentFailureCategory.SYSTEM_ERROR,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.category = category


@dataclass(frozen=True, slots=True)
class AgentLimits:
    """The immutable budget attached to a run at creation.

    Snapshot rather than read live from settings: a run started under one budget
    must not silently receive a different one from a config reload mid-flight,
    or "how many attempts was this run allowed?" has no answer.
    """

    max_iterations: int
    max_task_attempts: int
    max_consecutive_failures: int
    max_cost_per_run: Decimal
    max_cost_per_step: Decimal
    #: Output-token ceiling for one call, passed to the provider as
    #: ``max_output_tokens`` rather than checked afterwards. A limit observed after
    #: the response arrives is a report of what happened, not a budget.
    max_output_tokens_per_step: int
    #: Prompt-token ceiling for one call, enforced against the assembled prompt
    #: before it is sent.
    max_input_tokens_per_step: int
    #: Token ceiling for the whole run. The iteration budget does not imply it:
    #: forty permitted steps at five thousand tokens each is not a bounded spend.
    max_tokens_per_run: int
    step_timeout_seconds: float
    max_artifacts: int
    retry_backoff_seconds: float
    checkpoint_ttl_seconds: float
    max_tool_calls_per_step: int
    #: Ceiling on tool dispatches across the whole run, not just one step. The
    #: per-step limit bounds a single confused loop; this bounds a run that
    #: behaves plausibly step to step but never converges, which the per-step
    #: budget cannot see. Counted from the persisted invocation rows so the
    #: ceiling survives a restart.
    max_tool_calls_per_run: int
    #: Fraction of the per-step token budget spent on deciding vs producing.
    decision_token_ratio: float

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentLimits:
        return cls(
            max_iterations=settings.agent_max_iterations,
            max_task_attempts=settings.agent_max_task_attempts,
            max_consecutive_failures=settings.agent_max_consecutive_failures,
            max_cost_per_run=Decimal(str(settings.agent_max_cost_per_run)),
            max_cost_per_step=Decimal(str(settings.agent_max_cost_per_step)),
            max_output_tokens_per_step=settings.agent_max_output_tokens_per_step,
            max_input_tokens_per_step=settings.agent_max_input_tokens_per_step,
            max_tokens_per_run=settings.agent_max_tokens_per_run,
            step_timeout_seconds=settings.agent_step_timeout_seconds,
            max_artifacts=settings.agent_max_artifacts,
            retry_backoff_seconds=settings.agent_retry_backoff_seconds,
            checkpoint_ttl_seconds=settings.agent_checkpoint_ttl_seconds,
            max_tool_calls_per_step=settings.agent_max_tool_calls_per_step,
            max_tool_calls_per_run=settings.agent_max_tool_calls_per_run,
            decision_token_ratio=settings.agent_decision_token_ratio,
        )

    def backoff_seconds(self, attempt: int) -> float:
        """Delay before ``attempt``+1. Exponential, capped by the step timeout.

        Capped because a backoff longer than the timeout is not backoff, it is a
        hang: the step would fail before the retry could ever run.
        """
        if self.retry_backoff_seconds <= 0:
            return 0.0
        delay = self.retry_backoff_seconds * float(2 ** max(0, attempt - 1))
        return float(min(delay, self.step_timeout_seconds))


def assert_iteration_budget(limits: AgentLimits, iteration: int) -> None:
    """Refuse to start step ``iteration + 1`` once the loop budget is spent."""
    if iteration >= limits.max_iterations:
        raise BudgetExceeded(
            "AGENT_ITERATION_LIMIT",
            f"This run reached its limit of {limits.max_iterations} steps.",
        )


def assert_token_budget(limits: AgentLimits, run_total_tokens: int, step_tokens: int) -> None:
    """Refuse a call that would breach the per-run token ceiling.

    *step_tokens* is the size of the prompt about to be sent. The completion is
    bounded separately by ``max_output_tokens_per_step``, which is passed to the
    provider, so the run total is projected as prompt plus that ceiling: checking
    only the prompt would let a run spend four times its remaining budget in one
    call while every individual prompt looked affordable.
    """
    projected = run_total_tokens + step_tokens + limits.max_output_tokens_per_step
    if limits.max_tokens_per_run > 0 and projected > limits.max_tokens_per_run:
        raise BudgetExceeded(
            "AGENT_TOKEN_LIMIT",
            (
                f"This run reached its limit of {limits.max_tokens_per_run} tokens. "
                "Raise the limit or resume with a smaller budget to continue."
            ),
        )


def assert_input_token_budget(limits: AgentLimits, prompt_tokens: int) -> None:
    """Refuse to send a prompt larger than the per-call input ceiling.

    A single oversized prompt is not a budget problem, it is a bug or an
    oversized assignment, and it is reported as such rather than as a run that ran
    out of money.
    """
    if prompt_tokens > limits.max_input_tokens_per_step:
        raise BudgetExceeded(
            "AGENT_INPUT_TOO_LARGE",
            (
                f"This step's context is about {prompt_tokens} tokens, over the "
                f"per-step limit of {limits.max_input_tokens_per_step}."
            ),
        )


def assert_cost_budget(limits: AgentLimits, spent: Decimal, step_estimate: Decimal) -> None:
    """Refuse a provider call that would breach either cost ceiling.

    Checked *before* the call, not after: the point of a budget is that the
    unauthorised spend never happens.

    Both ceilings are skipped when they are zero, which means "unbounded". They
    are not skipped when the estimate is unknown: an unknown cost against a real
    ceiling is handled by :func:`assert_priced_model` before it gets here.
    """
    if limits.max_cost_per_run > 0 and spent + step_estimate > limits.max_cost_per_run:
        raise BudgetExceeded(
            "AGENT_COST_LIMIT",
            (
                f"This run reached its cost limit of {limits.max_cost_per_run}. "
                "Raise the limit or resume with a smaller budget to continue."
            ),
        )
    if limits.max_cost_per_step > 0 and step_estimate > limits.max_cost_per_step:
        raise BudgetExceeded(
            "AGENT_STEP_COST_LIMIT",
            f"Step {step_estimate} exceeds the per-step limit of {limits.max_cost_per_step}.",
        )


def estimate_step_cost(
    pricing: ModelPricing | None,
    prompt_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Cost of one call, or zero when the model has no configured price.

    Zero here means "cannot be estimated", and the caller must treat it as such by
    consulting :func:`assert_priced_model`. Substituting zero because a number was
    unavailable is precisely how a budget that never fires looks like a budget
    that was never approached.
    """
    if pricing is None:
        return Decimal("0")
    return Decimal(str(pricing.cost_for(LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=output_tokens,
        total_tokens=prompt_tokens + output_tokens,
    ))))


def assert_priced_model(pricing: ModelPricing | None, model: str) -> None:
    """Refuse to run uncosted when the deployment demands real prices.

    With ``LLM_UNPRICED_MODEL_POLICY=refuse`` a run on a model with no configured
    price stops immediately with an explanation. The alternative - proceeding and
    recording no cost - produces a run whose cost column is empty while it spends
    real money, and an operator has no way to tell which runs those are.
    """
    if pricing is not None:
        return
    if get_settings().llm_unpriced_model_policy != "refuse":
        return
    raise BudgetExceeded(
        "AGENT_MODEL_UNPRICED",
        (
            f"No price is configured for {model}, and this deployment refuses to run "
            "unpriced models. Add it to LLM_PRICING or set "
            "LLM_UNPRICED_MODEL_POLICY=record."
        ),
    )


def assert_tool_run_budget(limits: AgentLimits, run_tool_calls: int) -> None:
    """Refuse a tool dispatch once the run has spent its whole tool allowance.

    A run-scoped count rather than a per-step one: a model that calls two tools
    every step looks disciplined within each step yet can still spend a hundred
    calls over a run. Counted from persisted rows so a resume cannot reset it.
    """
    if limits.max_tool_calls_per_run > 0 and run_tool_calls >= limits.max_tool_calls_per_run:
        raise BudgetExceeded(
            "AGENT_TOOL_RUN_LIMIT",
            (
                f"This run reached its limit of {limits.max_tool_calls_per_run} tool calls. "
                "Resume with a larger budget or finish the remaining tasks by hand."
            ),
            category=AgentFailureCategory.VALIDATION_ERROR,
        )


def assert_artifact_budget(limits: AgentLimits, artifact_count: int) -> None:
    if artifact_count >= limits.max_artifacts:
        raise BudgetExceeded(
            "AGENT_ARTIFACT_LIMIT",
            f"This run reached its limit of {limits.max_artifacts} artifacts.",
        )


def may_retry(limits: AgentLimits, attempt: int, consecutive_failures: int) -> bool:
    """Whether another attempt is permitted.

    Both conditions must hold: the task has attempts left *and* the run has not
    already failed too many tasks in a row. The second is what stops a plan with
    twenty broken tasks from costing twenty times the retry limit.
    """
    return (
        attempt < limits.max_task_attempts
        and consecutive_failures < limits.max_consecutive_failures
    )


def status_for_budget_failure(exc: BudgetExceeded) -> AgentRunStatus:
    """A budget breach is terminal for the run, never a retryable pause.

    Retrying into a spent budget would loop forever by construction, so the run
    fails with an explanation the student can act on.
    """
    return AgentRunStatus.FAILED
