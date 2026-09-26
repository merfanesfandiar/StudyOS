"""Provider selection. The application layer calls this, never a provider class."""

from __future__ import annotations

from app.ai.errors import LLMUnavailableError
from app.ai.provider import LLMProvider
from app.ai.providers.mock import MockLLMProvider
from app.ai.providers.openai import OpenAIProvider
from app.core.config import Settings, get_settings


def build_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Return the configured provider.

    Defaults to the deterministic mock provider, so the product and its tests
    work with no API key and no network access. A misconfigured real provider
    fails loudly rather than silently falling back.
    """
    config = settings or get_settings()
    if config.llm_provider == "openai":
        if not config.llm_api_key:
            raise LLMUnavailableError(
                "The openai provider is selected but LLM_API_KEY is not set.",
                {"provider": "openai"},
            )
        return OpenAIProvider(
            api_key=config.llm_api_key,
            model=config.llm_model,
            base_url=config.llm_base_url,
            timeout_seconds=config.llm_timeout_seconds,
            max_output_tokens=config.llm_max_output_tokens,
        )
    return MockLLMProvider(model=config.llm_model)
