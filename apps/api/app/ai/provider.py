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


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    estimated_cost: float | None = None


class LLMProvider(ABC):
    """A configured model endpoint that returns structured JSON text."""

    #: Stable provider identifier, stored with every run.
    name: str = "unknown"
    #: The concrete model, stored with every run.
    model: str = "unknown"

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the model's raw JSON text. Raises ``LLMError`` on failure."""
        raise NotImplementedError
