"""Provider-neutral LLM contract.

The application depends only on this module. No provider SDK, HTTP client or
vendor type appears anywhere in the domain or application layers.

``LLMRequest.metadata`` is application context that a provider may use to ground
its answer (the mock provider uses it to analyze deterministically). It is never
sent over the wire: real providers only receive ``messages`` and
``response_schema``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "developer", "user"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: tuple[LLMMessage, ...]
    response_schema: dict[str, Any]
    prompt_version: str
    temperature: float = 0.0
    max_output_tokens: int = 4000
    #: Application-only grounding data. Never transmitted.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


def approximate_tokens(messages: tuple[LLMMessage, ...]) -> int:
    """Rough token count for a prompt, for pre-send budget checks.

    Deliberately an approximation and deliberately shared. A real tokenizer is a
    per-vendor dependency, which this module's contract exists to keep out of the
    application, and a budget needs a number *before* the request is sent rather
    than the exact one after.

    The constant is the familiar 4-characters-per-token rule of thumb. It is
    biased low for JSON and non-Latin scripts, so it is used only where being
    wrong by 20% is acceptable: refusing an affordable call. The authoritative
    count still comes from the provider's own usage, which is what gets charged.
    """
    characters = sum(len(message.content) for message in messages)
    return max(1, characters // 4)


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """What one model costs, per 1,000 tokens.

    Lives at the provider boundary rather than in the domain because the domain
    deliberately never names a model. The alternative - a pricing table keyed by
    model in a service - puts the knowledge in the wrong place: only the provider
    knows which concrete model it actually reached, including after a fallback.
    """

    prompt_per_1k: float = 0.0
    completion_per_1k: float = 0.0

    def cost_for(self, usage: LLMUsage) -> float:
        return round(
            (usage.prompt_tokens / 1000) * self.prompt_per_1k
            + (usage.completion_tokens / 1000) * self.completion_per_1k,
            6,
        )


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    #: ``None`` means "this deployment does not know what the model costs", which
    #: is different from zero. A run that cannot be costed must be reported as
    #: uncosted rather than as free, or the budget that guards it means nothing.
    estimated_cost: float | None = None


class LLMProvider(ABC):
    """A configured model endpoint that returns structured JSON text."""

    #: Stable provider identifier, stored with every run.
    name: str = "unknown"
    #: The concrete model, stored with every run.
    model: str = "unknown"

    def pricing(self, model: str | None = None) -> ModelPricing | None:
        """Price for *model*, defaulting to this provider's own.

        Resolved from configuration by the concrete model name rather than by the
        tier that was asked for, because a tier is a capability and two models on
        the same tier can cost very different amounts.

        ``None`` is a supported, honest answer. The run then records no cost and
        the caller treats the budget as unenforceable for that deployment, which
        is a state an operator can see - as opposed to assuming the work was free
        and reporting a confident zero.
        """
        from app.core.config import get_settings

        entry = get_settings().llm_pricing.get(model or self.model)
        if entry is None:
            return None
        return ModelPricing(
            prompt_per_1k=float(entry.get("prompt", 0.0)),
            completion_per_1k=float(entry.get("completion", 0.0)),
        )

    def cost_of(self, usage: LLMUsage) -> float | None:
        """Cost of *usage* on this provider's model, or ``None`` if unpriced."""
        price = self.pricing()
        return None if price is None else price.cost_for(usage)

    def cost_of_usage(self, usage: LLMUsage, model: str) -> float | None:
        """Cost of *usage* on *model*, or ``None`` if this deployment has no price.

        Takes the model explicitly so a provider can price against the model the
        response actually names. Optional by model rather than only by instance,
        because a single provider object can serve more than one configured model.
        """
        price = self.pricing(model)
        return None if price is None else price.cost_for(usage)

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the model's raw JSON text. Raises ``LLMError`` on failure."""
        raise NotImplementedError
