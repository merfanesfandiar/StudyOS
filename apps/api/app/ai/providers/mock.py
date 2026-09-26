"""Deterministic provider: no network, no credentials, reproducible output.

It answers both prompt versions the product asks for by generating the JSON from
the deterministic engines. Tests, CI and offline development therefore exercise the
full parse + validate + persist pipeline rather than a canned fixture, and a
regression in the engine shows up as a test failure instead of a silent divergence
between what CI and production do.
"""

from __future__ import annotations

import json

from app.ai import heuristics
from app.ai.provider import LLMProvider, LLMRequest, LLMResponse, LLMUsage
from app.schemas.analysis import PlanningContractResponse


class MockLLMProvider(LLMProvider):
    name = "mock"

    def __init__(self, model: str = "mock-academic-analyzer-v1") -> None:
        self.model = model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if "planner_input" in request.metadata:
            return self._plan(request)
        return self._analyze(request)

    def _analyze(self, request: LLMRequest) -> LLMResponse:
        payload = request.metadata.get("analyzer_input") or {}
        include_questions = bool(request.metadata.get("include_questions", True))
        result = heuristics.analyze(payload, include_questions=include_questions)
        return self._respond(result, payload)

    def _plan(self, request: LLMRequest) -> LLMResponse:
        """Answer a planning call from the contract the request carried.

        The validated contract travels in metadata alongside the flattened prompt
        input. A provider that can use structure should, and reconstructing the
        brief from the flattened view would mean a lossy round trip through fields
        the planner never reads.
        """
        from app.modules.planning.planner import (
            PlanningPreferences,
            synthesize_plan,
        )

        contract = PlanningContractResponse.model_validate(request.metadata["planning_contract"])
        preferences = PlanningPreferences(**request.metadata["planner_preferences"])
        plan = synthesize_plan(
            contract,
            preferences=preferences,
            max_task_count=int(request.metadata.get("max_task_count", 60)),
        )
        return self._respond(plan.model_dump(mode="json"), request.metadata)

    def _respond(self, result: object, payload: object) -> LLMResponse:
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
