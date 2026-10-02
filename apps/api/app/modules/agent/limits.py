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

from app.core.config import Settings
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
    step_timeout_seconds: float
    max_artifacts: int
    retry_backoff_seconds: float
    checkpoint_ttl_seconds: float
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
            step_timeout_seconds=settings.agent_step_timeout_seconds,
            max_artifacts=settings.agent_max_artifacts,
            retry_backoff_seconds=settings.agent_retry_backoff_seconds,
            checkpoint_ttl_seconds=settings.agent_checkpoint_ttl_seconds,
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


def assert_cost_budget(limits: AgentLimits, spent: Decimal, step_estimate: Decimal) -> None:
    """Refuse a provider call that would breach either cost ceiling.

    Checked *before* the call, not after: the point of a budget is that the
    unauthorised spend never happens.
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
