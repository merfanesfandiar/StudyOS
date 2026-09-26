"""Deterministic provider: no network, no credentials, reproducible output.

It runs the same analysis contract a real model is asked for by generating the
JSON from the deterministic heuristics engine. Tests, CI and offline development
therefore exercise the full parse + validate + persist pipeline.
"""

from __future__ import annotations

import json

from app.ai import heuristics
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage


class MockLLMProvider(LLMProvider):
    name = "mock"

    def __init__(self, model: str = "mock-academic-analyzer-v1") -> None:
        self.model = model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = request.metadata.get("analyzer_input") or {}
        include_questions = bool(request.metadata.get("include_questions", True))
        result = heuristics.analyze(payload, include_questions=include_questions)
        content = json.dumps(result, ensure_ascii=False, default=str)

        # Approximate usage so token accounting and cost estimation are exercised
        # without pretending to know real tokenizer output.
        prompt_tokens = max(1, len(json.dumps(payload, default=str)) // 4)
        completion_tokens = max(1, len(content) // 4)
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
