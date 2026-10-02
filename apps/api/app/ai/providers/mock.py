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
        #: Scripted agent outcomes, consumed in order. Lets a test drive the
        #: runtime through success, failure, retry, checkpoint, partial
        #: completion, invalid output and low confidence without a network call
        #: and without monkeypatching the provider.
        self._agent_script: list[str] = []

    def script_agent(self, *outcomes: str) -> None:
        """Queue raw decision payloads for the next agent calls."""
        self._agent_script = list(outcomes)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if "agent_input" in request.metadata:
            return self._agent(request)
        if "agent_execution_input" in request.metadata:
            return self._execute(request)
        if "planner_input" in request.metadata:
            return self._plan(request)
        return self._analyze(request)

    # -- Phase 5: the agent runtime ------------------------------------
    #
    # The mock answers agent calls deterministically. With no script queued it
    # picks a valid action from the task context, so the default path is a
    # well-behaved run; a queued script is how tests exercise the unhappy paths.
    # There is no randomness anywhere here, which is what makes the runtime's
    # retry and recovery behaviour reproducible.

    def _agent(self, request: LLMRequest) -> LLMResponse:
        if self._agent_script:
            content = self._agent_script.pop(0)
            return self._respond_text(content, request.metadata)
        payload = request.metadata["agent_input"]
        task_key = str(payload.get("task_key", "T1"))
        decision = {
            "action": "EXECUTE_TASK",
            "task_key": task_key,
            "reason": "This task is executable and its predecessors are done.",
            "expected_output": "A draft the student can review.",
            "confidence": 0.9,
        }
        return self._respond_text(json.dumps(decision), request.metadata)

    def _execute(self, request: LLMRequest) -> LLMResponse:
        payload = request.metadata["agent_execution_input"]
        task_key = str(payload.get("task_key", "T1"))
        task_type = str(payload.get("task_type", "OTHER"))
        body = (
            f"Work product for {task_key} ({task_type}).\n\n"
            "Produced deterministically by the mock provider for offline runs, "
            "CI and tests. A real provider would replace this with real work."
        )
        result = {"summary": f"Produced work for {task_key}.", "content": body}
        return self._respond_text(json.dumps(result), request.metadata)

    def _respond_text(self, content: str, payload: object) -> LLMResponse:
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            usage=_approximate_usage(content, payload),
        )

    def _respond(self, result: object, payload: object) -> LLMResponse:
        return self._respond_text(json.dumps(result, ensure_ascii=False, default=str), payload)

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


def _approximate_usage(content: str, payload: object) -> LLMUsage:
    """Approximate token accounting.

    Explicitly an approximation: it exists so token accounting and cost
    estimation are exercised end to end, not to claim real tokenizer output.
    """
    prompt_tokens = max(1, len(json.dumps(payload, default=str)) // 4)
    completion_tokens = max(1, len(content) // 4)
    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
