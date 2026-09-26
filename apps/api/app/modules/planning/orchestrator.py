"""Plan generation: the model's opinion, checked by the engine.

The order here is the whole design. The engine proposes a plan, the validator
judges it, and the deterministic planner is always available as the answer. That
ordering is what stops a bad model response from becoming a student's plan.

Three outcomes, in the order they are tried:

1. Ask the routed model tier for a plan.
2. Validate it against the contract and the graph rules. If it passes, it is
   used, because a model can phrase a better plan than fixed rules can.
3. If it fails, or the call fails outright, synthesize deterministically. The
   student gets a plan either way, and the run records that the fallback happened
   rather than presenting a fallback as a model result.

A model response is never repaired. Either it is a valid plan or the
deterministic engine answers, because a half-repaired plan is one nobody has
actually reviewed.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import LLMError
from app.ai.provider import LLMProvider, LLMRequest
from app.ai.registry import ModelSelection
from app.core.errors import AppError
from app.models import AcademicWorkPlan, Assignment, AssignmentAnalysis, PlanTask
from app.models.enums import PlanningRunStatus, PlanTrigger
from app.modules.planning.complexity import score_complexity
from app.modules.planning.graph import PlanGraphError, ValidatedGraph, validate_graph
from app.modules.planning.planner import PlanningPreferences, synthesize_plan
from app.modules.planning.service import (
    PlanGraphView,
    find_idempotent_plan,
    finish_run,
    load_plan_graph,
    persist_plan,
    plan_idempotency_key,
    start_run,
)
from app.schemas.analysis import PlanningContractResponse
from app.schemas.planning import PlannerOutput

#: Rough blended price per 1k tokens, used only to report a relative figure.
#: A real deployment configures this per tier; the point of storing it at all is
#: that a run's cost is visible rather than unknown.
COST_PER_1K_TOKENS = 0.002


@dataclass(slots=True)
class GenerationResult:
    """What a generation attempt produced, and how it got there.

    ``graph`` is loaded back from storage rather than reused from validation, so
    a caller renders exactly the plan that was persisted. If the two ever disagree
    the response should show the stored truth, because that is the truth.
    """

    plan: AcademicWorkPlan
    graph: PlanGraphView
    #: The planning run that produced this plan, or ``None`` when an existing
    #: plan was returned unchanged and no run happened.
    run_id: UUID | None
    #: True when the deterministic engine answered instead of the model.
    used_fallback: bool
    warnings: list[str]


class PlanRejectedError(AppError):
    """The model proposed a plan that failed validation.

    Surfaced as a distinct code so the client can tell "the model got it wrong"
    apart from "the model was unreachable", which need different responses from a
    student.
    """

    def __init__(self, violations: list[str]) -> None:
        super().__init__(
            422,
            "PLAN_REJECTED",
            "The generated plan did not pass validation and was discarded.",
            {"violations": violations},
        )


async def generate_plan(
    db: AsyncSession,
    *,
    assignment: Assignment,
    analysis: AssignmentAnalysis,
    contract: PlanningContractResponse,
    provider: LLMProvider,
    selection: ModelSelection,
    preferences: PlanningPreferences,
    user_id: UUID,
    trigger: PlanTrigger = PlanTrigger.GENERATED,
    reason: str = "",
    idempotency_key: str | None = None,
    preserve: Sequence[PlanTask] = (),
    max_task_count: int = 60,
    hours_per_grade_point: float = 45.0,
    fallback_enabled: bool = True,
    prompt_version: str = "academic_planner_v1",
    force: bool = False,
) -> GenerationResult:
    """Produce a validated plan and persist it as a new version."""
    complexity = score_complexity(contract)
    key = idempotency_key or plan_idempotency_key(
        assignment_id=str(assignment.id),
        analysis_revision=analysis.revision,
        prompt_version=prompt_version,
        provider=provider.name,
        model=provider.model,
        style=preferences.style.value,
        guidance=preferences.guidance.value,
    )

    # A repeated request with the same key must not produce a second version or a
    # second model call. Checked before anything is written, so a double-clicked
    # button costs nothing. `force` is the explicit way to ask for a fresh plan
    # anyway, so it is the one thing that skips this.
    if idempotency_key is not None and not force:
        existing = await find_idempotent_plan(assignment.id, key, db)
        if existing is not None:
            graph = await load_plan_graph(db, existing)
            return GenerationResult(
                plan=existing,
                graph=graph,
                run_id=None,
                used_fallback=bool((existing.payload or {}).get("used_fallback")),
                warnings=["this plan was already generated and has been returned unchanged"],
            )

    run = await start_run(
        db,
        assignment=assignment,
        analysis=analysis,
        user_id=user_id,
        idempotency_key=key,
        provider=provider.name,
        model=provider.model,
        model_tier=selection.tier,
        routing_reason=selection.reason,
        routing_confidence=selection.confidence,
        complexity=complexity.level,
        prompt_version=prompt_version,
    )

    started = time.monotonic()
    proposed: PlannerOutput | None = None
    validated: ValidatedGraph
    validation_warnings: list[str] = []
    rejections: list[str] = []
    token_usage: dict[str, Any] | None = None
    cost: float | None = None

    # The model is always asked. `fallback_enabled` governs degrading to the
    # cheaper *tier* and whether a failed call may fall back at all, not whether
    # the model is consulted: a plan produced without asking any model is a
    # different product decision.
    try:
        response = await provider.complete(
            build_planner_request(
                contract,
                preferences=preferences,
                model=provider.model,
                prompt_version=prompt_version,
                max_task_count=max_task_count,
            )
        )
        token_usage = response.usage.as_dict()
        cost = round((response.usage.total_tokens / 1000) * COST_PER_1K_TOKENS, 6)
        candidate = _parse_planner_output(response.content)
        validated = validate_graph(candidate, contract)
        validation_warnings = list(validated.warnings)
        proposed = candidate
    except LLMError as exc:
        if not fallback_enabled:
            raise
        rejections = [f"the model call failed: {exc.code or exc.__class__.__name__}"]
    except PlanGraphError as exc:
        if not fallback_enabled:
            raise
        rejections = exc.violations

    used_fallback = proposed is None
    if proposed is None:
        # The deterministic engine is the floor. Whatever the model did, the
        # student gets a sound plan and the run says where it came from.
        proposed = synthesize_plan(
            contract,
            preferences=preferences,
            max_task_count=max_task_count,
            hours_per_grade_point=hours_per_grade_point,
        )
        validated = validate_graph(proposed, contract)
        validation_warnings = list(validated.warnings)

    plan = await persist_plan(
        db,
        assignment=assignment,
        analysis=analysis,
        plan_output=proposed,
        graph=validated,
        contract=contract,
        trigger=trigger,
        reason=reason or ("deterministic fallback" if used_fallback else ""),
        preferences=preferences,
        idempotency_key=key,
        preserve=preserve,
        changed_sections=_changed_sections(proposed, rejections),
        used_fallback=used_fallback,
        rejection_reasons=rejections,
    )

    warnings = list(validation_warnings)
    if used_fallback:
        detail = "; ".join(rejections[:3]) if rejections else "no usable model response"
        warnings.append(f"this plan was produced by the planning engine, not the model ({detail})")

    await finish_run(
        db,
        run,
        status=PlanningRunStatus.SUCCEEDED,
        plan=plan,
        duration_ms=int((time.monotonic() - started) * 1000),
        token_usage=token_usage,
        estimated_cost=cost,
        output_hash=_output_hash(proposed),
    )
    return GenerationResult(
        plan=plan,
        graph=await load_plan_graph(db, plan),
        run_id=run.id,
        used_fallback=used_fallback,
        warnings=warnings,
    )


def _parse_planner_output(content: str) -> PlannerOutput:
    """Parse model text into a plan, or fail.

    No repair beyond a fenced code block. A response that needs surgery has not
    been reviewed by anyone, and the deterministic engine is a better answer than
    a guess at what the model meant.
    """
    from app.ai.errors import LLMResponseFormatError

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError(
            "The planner response was not valid JSON.", {"reason": str(exc)[:200]}
        ) from exc
    try:
        return PlannerOutput.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - re-raised as a provider error
        raise LLMResponseFormatError(
            "The planner response did not match the plan schema.",
            {"reason": str(exc)[:300]},
        ) from exc


def build_planner_request(
    contract: PlanningContractResponse,
    *,
    preferences: PlanningPreferences,
    model: str,
    prompt_version: str,
    max_task_count: int,
) -> LLMRequest:
    """Build the planner request.

    The contract is passed as grounding metadata rather than interpolated into
    prose, matching how the analyzer is called, so a provider can use it
    deterministically and a real provider receives it as structured content.
    """
    from app.ai.prompts import planner as planner_prompts

    return LLMRequest(
        messages=planner_prompts.build_planner_messages(
            contract, preferences=preferences, max_task_count=max_task_count
        ),
        response_schema=planner_prompts.planner_response_schema(),
        prompt_version=prompt_version,
        temperature=0.0,
        max_output_tokens=8000,
        metadata={
            # The flattened view is what the model reads. The whole contract rides
            # along for providers that can use structure, so no one has to invert
            # the prompt to get the brief back.
            "planner_input": planner_prompts.build_planner_input(
                contract,
                preferences=preferences,
                max_task_count=max_task_count,
            ),
            "planning_contract": contract.model_dump(mode="json"),
            "planner_preferences": asdict(preferences),
            "max_task_count": max_task_count,
            "model": model,
        },
    )


def _changed_sections(plan: PlannerOutput, rejections: list[str]) -> list[str]:
    from app.modules.planning.service import (
        SECTION_EFFORT,
        SECTION_MILESTONES,
        SECTION_TASKS,
        SECTION_TRACEABILITY,
    )

    sections = [SECTION_TASKS, SECTION_TRACEABILITY, SECTION_EFFORT]
    if plan.milestones:
        sections.append(SECTION_MILESTONES)
    if rejections:
        sections.append("rejected_model_output")
    return sections


def _output_hash(plan: PlannerOutput) -> str:
    material = json.dumps(plan.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(material.encode()).hexdigest()
