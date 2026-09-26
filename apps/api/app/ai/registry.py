"""Model registry and router: two tiers, one explainable decision.

Phase 4 promises two model tiers, a complexity-driven choice between them, and
honest reporting of what was used and what it cost. This module is that decision,
kept separate from the planning service so it can be tested without a database
and so the routing rule is readable in one place.

Three properties matter more than cleverness here:

* **Explainable.** Every selection carries one sentence a human can check, plus
  the factors behind it. A router nobody can audit is a router nobody can trust.
* **Honest about overrides.** A student who asked for FAST and got the advanced
  model is told so, with the reason. Silently ignoring the preference would make
  the preference meaningless and the cost unpredictable.
* **Degradable.** When the chosen tier is unavailable, the run falls back to the
  cheaper tier and records the fallback, rather than failing the student's request
  or silently succeeding on a model nobody expected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.ai.errors import LLMError, LLMUnavailableError
from app.ai.factory import build_llm_provider
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse
from app.core.config import Settings
from app.models.enums import AIMode, ComplexityLevel, ModelTier
from app.modules.planning.complexity import ComplexityScore


class ProviderFactory(Protocol):
    """How the registry asks for a provider, so tests can supply their own."""

    def __call__(self, settings: Settings, model: str) -> LLMProvider: ...


def _default_factory(settings: Settings, model: str) -> LLMProvider:
    return build_llm_provider(settings, model=model)


@dataclass(frozen=True, slots=True)
class ModelEndpoint:
    """One configured endpoint in one tier."""

    tier: ModelTier
    model: str
    #: Rough relative cost per 1k tokens, used only to report a relative figure.
    cost_weight: float = 1.0


@dataclass(slots=True)
class ModelSelection:
    """A routing decision, with the reasoning attached."""

    tier: ModelTier
    model: str
    reason: str
    confidence: float
    complexity: ComplexityLevel
    complexity_factors: list[str] = field(default_factory=list)
    ai_mode: AIMode = AIMode.AUTO
    overridden: bool = False
    override_reason: str | None = None

    @property
    def cost_weight(self) -> float:
        return 2.5 if self.tier == ModelTier.ADVANCED else 1.0


class ModelRegistry:
    """Holds the configured endpoints and hands providers out by tier.

    Endpoints are built lazily and cached. Construction is cheap, but building a
    provider validates configuration, and a routing decision should not be the
    thing that surfaces a misconfiguration.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        factory: ProviderFactory | None = None,
    ) -> None:
        self._settings = settings
        self._factory = factory or _default_factory
        self._endpoints = {
            ModelTier.EFFICIENT: ModelEndpoint(
                tier=ModelTier.EFFICIENT, model=settings.llm_efficient_model, cost_weight=1.0
            ),
            ModelTier.ADVANCED: ModelEndpoint(
                tier=ModelTier.ADVANCED, model=settings.llm_advanced_model, cost_weight=2.5
            ),
        }
        self._providers: dict[ModelTier, LLMProvider] = {}

    def endpoint(self, tier: ModelTier) -> ModelEndpoint:
        return self._endpoints[tier]

    def model_for(self, tier: ModelTier) -> str:
        return self._endpoints[tier].model

    def provider(self, tier: ModelTier) -> LLMProvider:
        """Return the provider for a tier, building it on first use."""
        if tier not in self._providers:
            self._providers[tier] = self._factory(self._settings, self._endpoints[tier].model)
        return self._providers[tier]

    @property
    def fallback_tier(self) -> ModelTier:
        """Where a run degrades to. Always the cheaper tier.

        Degrading upward would defeat the point of a fallback and could turn a
        transient failure into an expensive one.
        """
        return ModelTier.EFFICIENT


class ModelRouter:
    """Chooses a tier from the contract's complexity and the student's preference.

    The rule is a short decision list rather than a learned policy, because a
    student who chose FAST deserves to know exactly when they did not get it.
    """

    #: At or above this complexity, a plan gets the advanced model even on FAST.
    #: Only the top band, and only with a confident score: overriding a stated
    #: preference on a borderline guess would be indefensible.
    OVERRIDE_THRESHOLD = ComplexityLevel.VERY_HIGH

    #: Explicit rank. These enums are ``StrEnum``, so ``>=`` compares their *values*
    #: lexicographically and "HIGH" >= "MEDIUM" is False. Comparing them directly
    #: silently routes every non-low brief to the cheap model, so ordering always
    #: goes through this table.
    _RANK: dict[ComplexityLevel, int] = {
        ComplexityLevel.LOW: 0,
        ComplexityLevel.MEDIUM: 1,
        ComplexityLevel.HIGH: 2,
        ComplexityLevel.VERY_HIGH: 3,
    }

    @classmethod
    def at_least(cls, level: ComplexityLevel, threshold: ComplexityLevel) -> bool:
        return cls._RANK[level] >= cls._RANK[threshold]

    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    def select(
        self,
        complexity: ComplexityScore,
        ai_mode: AIMode = AIMode.AUTO,
    ) -> ModelSelection:
        level = complexity.level

        if ai_mode == AIMode.DEEP:
            return ModelSelection(
                tier=ModelTier.ADVANCED,
                model=self.registry.model_for(ModelTier.ADVANCED),
                reason="You asked for deep planning, so the advanced model is used.",
                confidence=1.0,
                complexity=level,
                complexity_factors=complexity.factors,
                ai_mode=ai_mode,
            )

        if ai_mode == AIMode.FAST:
            if self.at_least(level, self.OVERRIDE_THRESHOLD) and complexity.confidence >= 0.5:
                return ModelSelection(
                    tier=ModelTier.ADVANCED,
                    model=self.registry.model_for(ModelTier.ADVANCED),
                    reason=(
                        "This brief is unusually complex, so the advanced model is used "
                        "despite the fast preference."
                    ),
                    confidence=complexity.confidence,
                    complexity=level,
                    complexity_factors=complexity.factors,
                    ai_mode=ai_mode,
                    overridden=True,
                    override_reason=(
                        "The brief scored in the top complexity band, where a cheaper "
                        "model tends to drop requirements."
                    ),
                )
            return ModelSelection(
                tier=ModelTier.EFFICIENT,
                model=self.registry.model_for(ModelTier.EFFICIENT),
                reason="You asked for fast planning, so the efficient model is used.",
                confidence=complexity.confidence,
                complexity=level,
                complexity_factors=complexity.factors,
                ai_mode=ai_mode,
            )

        if ai_mode == AIMode.BALANCED:
            threshold = ComplexityLevel.HIGH
        else:  # AUTO
            threshold = ComplexityLevel.MEDIUM

        tier = ModelTier.ADVANCED if self.at_least(level, threshold) else ModelTier.EFFICIENT
        return ModelSelection(
            tier=tier,
            model=self.registry.model_for(tier),
            reason=(
                f"This brief scored {level.value.lower()} complexity, so the "
                f"{'advanced' if tier == ModelTier.ADVANCED else 'efficient'} model is used."
            ),
            confidence=complexity.confidence,
            complexity=level,
            complexity_factors=complexity.factors,
            ai_mode=ai_mode,
        )


async def complete_with_fallback(
    registry: ModelRegistry,
    selection: ModelSelection,
    request_factory: Callable[[str], LLMRequest],
    *,
    fallback_enabled: bool = True,
) -> tuple[LLMResponse, ModelTier | None]:
    """Run a request on the selected tier, degrading to the cheaper tier on failure.

    ``request_factory`` is called per attempt so the retry carries the selected
    model rather than a stale one. Returns ``(response, fell_back_from)`` where
    ``fell_back_from`` is the tier that failed, or ``None`` when the first attempt
    worked.

    A failure is only worth degrading for when it is about the endpoint. A schema
    or format error means the model answered and the answer was unusable, which
    retrying on a different model will not fix, so that propagates and the
    deterministic planner takes over instead.
    """
    tiers: list[ModelTier] = [selection.tier]
    fallback = registry.fallback_tier
    if fallback_enabled and fallback != selection.tier:
        tiers.append(fallback)

    last_error: LLMError | None = None
    for index, tier in enumerate(tiers):
        try:
            provider = registry.provider(tier)
            model = selection.model if index == 0 else registry.model_for(tier)
            response = await provider.complete(request_factory(model))
            return response, (selection.tier if index > 0 else None)
        except LLMUnavailableError as exc:
            last_error = exc
            continue
        except LLMError:
            # Not a transport problem. Do not spend another call on it.
            raise
    if last_error is not None:
        raise last_error
    raise LLMUnavailableError("No model tier was available for this run.")
