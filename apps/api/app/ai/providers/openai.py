"""OpenAI-compatible provider.

Works with any endpoint that implements the ``/chat/completions`` contract. The
domain layer never imports this module directly; only the provider factory does.

The model is asked for a JSON object. If a model ignores that and wraps the JSON
in prose, the parser rejects it rather than guessing: StudyOS never trusts raw
model output.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.ai.errors import LLMTimeoutError, LLMUnavailableError
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage

#: Map our four-way separation onto the wire. ``developer`` becomes a second
#: system message on endpoints that do not understand the role, which preserves
#: the separation instead of merging instructions into untrusted data.
_ROLE_MAP = {"system": "system", "developer": "system", "user": "user"}


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        max_output_tokens: int = 4000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        #: Injectable so the transport contract can be tested without a network.
        self.transport = transport

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": _ROLE_MAP[message.role], "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": min(request.max_output_tokens, self.max_output_tokens),
            "response_format": {"type": "json_object"},
        }

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise LLMUnavailableError(
                "No API key is configured for the OpenAI provider.",
                {"provider": self.name},
            )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=self._body(request),
                )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("The model provider timed out.", {"provider": self.name}) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                "The model provider is unavailable.", {"provider": self.name}
            ) from exc

        if response.status_code >= 400:
            raise LLMUnavailableError(
                "The model provider rejected the request.",
                {"provider": self.name, "status_code": response.status_code},
            )

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(
                "The model provider returned an unexpected response shape.",
                {"provider": self.name},
            ) from exc
        if not isinstance(content, str):
            raise LLMUnavailableError(
                "The model provider returned non-text content.",
                {"provider": self.name},
            )

        usage = payload.get("usage") or {}
        return LLMResponse(
            content=content,
            provider=self.name,
            model=str(payload.get("model") or self.model),
            usage=LLMUsage(
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
            ),
        )
