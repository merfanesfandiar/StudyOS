"""Tests for model tier routing.

Routing is the one place where a subtle bug is invisible until the bill arrives,
so these tests assert the decision is monotonic in complexity and that a stated
preference is either honoured or explained.
"""

from __future__ import annotations

import pytest
from app.ai.errors import LLMResponseFormatError, LLMUnavailableError
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse
from app.ai.registry import ModelRegistry, ModelRouter, complete_with_fallback
from app.core.config import get_settings
from app.models.enums import AIMode, ComplexityLevel, ModelTier
from app.modules.planning.complexity import ComplexityScore
from app.modules.planning.contract_forge import contracts_for_fixtures


def _settings(**overrides):
    """An isolated settings copy.

    ``get_settings()`` is a cached singleton, so mutating it in a test would leak
    configuration into every test that runs afterwards.
    """
    return get_settings().model_copy(
        update={"llm_efficient_model": "cheap-v1", "llm_advanced_model": "smart-v1", **overrides}
    )


def _registry(**overrides) -> ModelRegistry:
    return ModelRegistry(_settings(**overrides))


def _score(level: ComplexityLevel, *, score: float = 50.0) -> ComplexityScore:
    """A complexity score with a derived confidence.

    ``confidence`` is a property of the distance to the nearest band boundary, so
    it is driven through ``score`` rather than injected. A score far from any
    boundary is confident; a score sitting on one is not.
    """
    return ComplexityScore(level=level, score=score, factors=["test factor"])


# ---------------------------------------------------------------------------
# The StrEnum trap
# ---------------------------------------------------------------------------


def test_complexity_levels_compare_by_rank_not_alphabetically() -> None:
    # StrEnum compares by value, so "HIGH" >= "MEDIUM" is False. Routing that used
    # the operators directly would send every non-low brief to the cheap model.
    router = ModelRouter(_registry())
    assert router.at_least(ComplexityLevel.HIGH, ComplexityLevel.MEDIUM) is True
    assert router.at_least(ComplexityLevel.VERY_HIGH, ComplexityLevel.MEDIUM) is True
    assert router.at_least(ComplexityLevel.MEDIUM, ComplexityLevel.HIGH) is False
    assert router.at_least(ComplexityLevel.LOW, ComplexityLevel.LOW) is True


def test_routing_is_monotonic_in_complexity() -> None:
    router = ModelRouter(_registry())
    tiers = [
        router.select(_score(level), AIMode.AUTO).tier
        for level in (
            ComplexityLevel.LOW,
            ComplexityLevel.MEDIUM,
            ComplexityLevel.HIGH,
            ComplexityLevel.VERY_HIGH,
        )
    ]
    # Once a brief earns the advanced model, raising complexity never takes it back.
    assert tiers == sorted(tiers, key=lambda t: 0 if t == ModelTier.EFFICIENT else 1)
    assert tiers[-1] == ModelTier.ADVANCED


# ---------------------------------------------------------------------------
# Preference handling
# ---------------------------------------------------------------------------


def test_deep_always_selects_advanced() -> None:
    router = ModelRouter(_registry())
    for level in ComplexityLevel:
        assert router.select(_score(level), AIMode.DEEP).tier == ModelTier.ADVANCED


def test_fast_selects_efficient_for_ordinary_briefs() -> None:
    router = ModelRouter(_registry())
    selection = router.select(_score(ComplexityLevel.HIGH), AIMode.FAST)
    assert selection.tier == ModelTier.EFFICIENT
    assert selection.overridden is False


def test_fast_is_overridden_only_on_the_top_band() -> None:
    router = ModelRouter(_registry())
    selection = router.select(_score(ComplexityLevel.VERY_HIGH, score=90.0), AIMode.FAST)
    assert selection.tier == ModelTier.ADVANCED
    assert selection.overridden is True
    # An override without a stated reason is an override the student cannot argue with.
    assert selection.override_reason


def test_fast_is_not_overridden_on_a_borderline_score() -> None:
    # Overriding a stated preference on a low-confidence guess would be
    # indefensible, so a borderline score defers to the student.
    router = ModelRouter(_registry())
    selection = router.select(_score(ComplexityLevel.VERY_HIGH, score=74.0), AIMode.FAST)
    assert selection.tier == ModelTier.EFFICIENT
    assert selection.overridden is False


def test_balanced_uses_a_higher_threshold_than_auto() -> None:
    router = ModelRouter(_registry())
    level = ComplexityLevel.MEDIUM
    assert router.select(_score(level), AIMode.AUTO).tier == ModelTier.ADVANCED
    assert router.select(_score(level), AIMode.BALANCED).tier == ModelTier.EFFICIENT


def test_every_selection_carries_a_human_reason() -> None:
    router = ModelRouter(_registry())
    for mode in AIMode:
        for level in ComplexityLevel:
            selection = router.select(_score(level), mode)
            assert selection.reason
            assert selection.model


def test_selection_reports_the_factors_behind_it() -> None:
    router = ModelRouter(_registry())
    selection = router.select(_score(ComplexityLevel.HIGH), AIMode.AUTO)
    assert selection.complexity_factors == ["test factor"]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_exposes_configured_models_per_tier() -> None:
    registry = _registry(llm_efficient_model="cheap-v1", llm_advanced_model="smart-v1")
    assert registry.model_for(ModelTier.EFFICIENT) == "cheap-v1"
    assert registry.model_for(ModelTier.ADVANCED) == "smart-v1"


def test_registry_caches_providers() -> None:
    built: list[str] = []

    def factory(settings, model: str) -> LLMProvider:
        built.append(model)
        return _StubProvider(model)

    registry = ModelRegistry(_settings(), factory=factory)
    registry.provider(ModelTier.EFFICIENT)
    registry.provider(ModelTier.EFFICIENT)
    assert len(built) == 1


def test_fallback_tier_is_always_the_cheaper_one() -> None:
    # Degrading upward would turn a transient failure into an expensive one.
    assert _registry().fallback_tier == ModelTier.EFFICIENT


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


class _StubProvider(LLMProvider):
    name = "stub"

    def __init__(self, model: str, *, fail: bool = False, error: Exception | None = None) -> None:
        self.model = model
        self._fail = fail
        self._error = error
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._fail:
            raise LLMUnavailableError("endpoint down")
        return LLMResponse(content="{}", provider=self.name, model=self.model)


def _request_factory(model: str) -> LLMRequest:
    return LLMRequest(
        messages=(), response_schema={}, prompt_version="v1", metadata={"model": model}
    )


@pytest.mark.asyncio
async def test_fallback_degrades_to_the_efficient_tier() -> None:
    advanced = _StubProvider("smart-v1", fail=True)
    efficient = _StubProvider("cheap-v1")

    def factory(settings, model: str) -> LLMProvider:
        return advanced if model == "smart-v1" else efficient

    registry = ModelRegistry(_settings(), factory=factory)
    selection = ModelRouter(registry).select(_score(ComplexityLevel.HIGH), AIMode.DEEP)
    response, fell_back = await complete_with_fallback(registry, selection, _request_factory)
    assert response.model == "cheap-v1"
    assert fell_back == ModelTier.ADVANCED
    assert efficient.calls == 1


@pytest.mark.asyncio
async def test_no_fallback_when_the_first_attempt_succeeds() -> None:
    def factory(settings, model: str) -> LLMProvider:
        return _StubProvider(model)

    registry = ModelRegistry(_settings(), factory=factory)
    selection = ModelRouter(registry).select(_score(ComplexityLevel.LOW), AIMode.FAST)
    _, fell_back = await complete_with_fallback(registry, selection, _request_factory)
    assert fell_back is None


@pytest.mark.asyncio
async def test_a_format_error_does_not_trigger_a_second_call() -> None:
    # The model answered and the answer was unusable. Retrying on another model
    # spends money to reach the same place, so it must propagate.
    advanced = _StubProvider("smart-v1", error=LLMResponseFormatError("bad json"))
    efficient = _StubProvider("cheap-v1")
    calls: list[str] = []

    def factory(settings, model: str) -> LLMProvider:
        calls.append(model)
        return advanced if model == "smart-v1" else efficient

    registry = ModelRegistry(_settings(), factory=factory)
    selection = ModelRouter(registry).select(_score(ComplexityLevel.HIGH), AIMode.DEEP)
    with pytest.raises(LLMResponseFormatError):
        await complete_with_fallback(registry, selection, _request_factory)
    assert calls == ["smart-v1"]
    assert efficient.calls == 0


@pytest.mark.asyncio
async def test_fallback_can_be_disabled() -> None:
    def factory(settings, model: str) -> LLMProvider:
        return _StubProvider(model, fail=True)

    registry = ModelRegistry(_settings(), factory=factory)
    selection = ModelRouter(registry).select(_score(ComplexityLevel.HIGH), AIMode.DEEP)
    with pytest.raises(LLMUnavailableError):
        await complete_with_fallback(registry, selection, _request_factory, fallback_enabled=False)


# ---------------------------------------------------------------------------
# Real contracts
# ---------------------------------------------------------------------------


def test_real_briefs_route_sensibly() -> None:
    from app.modules.planning.complexity import score_complexity

    router = ModelRouter(_registry())
    for name, contract in contracts_for_fixtures([]):
        real = score_complexity(contract)
        selection = router.select(real, AIMode.AUTO)
        assert selection.tier in {ModelTier.EFFICIENT, ModelTier.ADVANCED}, name
        assert selection.reason, name
        assert real.factors
