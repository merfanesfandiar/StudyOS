"""Provider-neutral AI layer.

Contains the LLM abstraction, versioned prompts, deterministic heuristics, the
mock and OpenAI providers, the golden academic dataset and the analysis
evaluation framework. It depends on the domain schemas but never the other way
around: no module under ``app.models`` imports anything from ``app.ai``.
"""

from app.ai.errors import (
    LLMError,
    LLMResponseFormatError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.ai.factory import build_llm_provider
from app.ai.provider import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)

__all__ = [
    "LLMError",
    "LLMMessage",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMResponseFormatError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "LLMUsage",
    "build_llm_provider",
]
