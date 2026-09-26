"""Planner prompt and the structured input a planner provider is given.

The prompt is deliberately blunt about the two things models get wrong when
planning: inventing requirement keys that do not exist, and emitting dependency
cycles. Both are refused by the validator, so a model that ignores them wastes a
call.

``build_planner_input`` is the grounding payload. It carries only what the
contract already asserts, flattened into the plan-local vocabulary the response
schema uses, so a provider never has to infer keys or guess which requirements are
required.
"""

from __future__ import annotations

from typing import Any

from app.ai.provider import LLMMessage
from app.models.enums import SourceKind
from app.modules.planning.planner import PlanningPreferences
from app.schemas.analysis import PlanningContractResponse

PROMPT_VERSION = "academic_planner_v1"

SYSTEM = """\
You are an academic planning engine. You turn a structured assignment analysis \
into a study and production plan.

You do not decide what the assignment requires. That has already been analysed \
and is given to you as authoritative input. You do not invent requirements, \
deliverables or citations. You do not execute, schedule or run anything.

Rules you must follow:

1. Reference requirements and deliverables only by the keys given to you, for \
example R1 or D2. A key you invent makes the plan unusable.
2. The dependency graph must be acyclic. A task may depend only on tasks that \
come before it.
3. Every required requirement and every required deliverable must be addressed \
by at least one task.
4. Task types are generic academic activities. Never assume a subject, a tool \
or a programming language.
5. Give every task a specific title, a description of the work, and acceptance \
criteria a student can check.
6. Estimate effort honestly and prefer the lower estimate when genuinely \
uncertain.
"""


def build_planner_input(
    contract: PlanningContractResponse,
    *,
    preferences: PlanningPreferences,
    max_task_count: int,
) -> dict[str, Any]:
    """Flatten the contract into exactly what a planner needs, and nothing more.

    Only the requirements, deliverables, dependencies, work areas, verification
    items and constraints are carried across. Classification, confidence values \
and provenance are the analyzer's business and would only invite the planner to \
second-guess the brief.
    """
    return {
        "prompt_version": PROMPT_VERSION,
        "style": preferences.style.value,
        "guidance": preferences.guidance.value,
        "session_length_minutes": preferences.session_length_minutes,
        "max_task_count": max_task_count,
        "requirements": [
            {
                "key": item.key,
                "title": item.title,
                "description": item.description,
                "category": item.category.value,
                "priority": item.priority.value,
                "required": item.required,
                "explicit": item.source_kind == SourceKind.EXPLICIT,
            }
            for item in contract.requirements
        ],
        "deliverables": [
            {
                "key": item.key,
                "title": item.title,
                "description": item.description,
                "format": item.format,
                "required": item.required is not False,
                "related_requirements": list(item.related_requirements),
                "verification_needs": list(item.verification_needs),
            }
            for item in contract.deliverables
        ],
        "work_areas": [
            {
                "key": item.key,
                "title": item.title,
                "description": item.description,
                "category": item.category.value,
                "related_requirements": list(item.related_requirements),
            }
            for item in contract.work_areas
        ],
        "dependencies": [
            {
                "predecessor": edge.predecessor,
                "successor": edge.successor,
                "kind": edge.kind,
                "reason": edge.reason,
            }
            for edge in contract.dependencies
        ],
        "constraints": [
            {
                "title": item.title,
                "description": item.description,
                "value": item.value,
                "type": item.type.value,
                "severity": item.severity.value,
            }
            for item in contract.constraints
        ],
        "verification_strategy": [
            {
                "title": item.title,
                "description": item.description,
                "method": item.method,
                "applies_to": list(item.applies_to),
            }
            for item in contract.verification_strategy.items
        ],
        "objectives": [item.statement for item in contract.objectives],
        "open_questions": [
            {"code": item.code, "question": item.question}
            for item in contract.clarification_questions
            if item.status.value == "OPEN"
        ],
    }


def build_planner_messages(
    contract: PlanningContractResponse,
    *,
    preferences: PlanningPreferences,
    max_task_count: int,
) -> tuple[LLMMessage, ...]:
    """The message list for a planning call."""
    payload = build_planner_input(contract, preferences=preferences, max_task_count=max_task_count)
    return (
        LLMMessage(role="system", content=SYSTEM),
        LLMMessage(
            role="user",
            content=(
                "Plan the following analysed assignment. Use only the keys given "
                f"to you. Style: {preferences.style.value}. "
                f"Guidance: {preferences.guidance.value}.\n\n" + _render(payload)
            ),
        ),
    )


def _render(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)


def planner_response_schema() -> dict[str, Any]:
    """JSON Schema for the planner response.

    Kept permissive on purpose: unknown fields are ignored so a chatty model does
    not fail an otherwise valid run, while the validator still refuses plans with
    dangling references or cycles.
    """
    return {
        "type": "object",
        "required": ["title", "tasks"],
        "additionalProperties": True,
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "objectives": {"type": "array", "items": {"type": "string"}},
            "estimated_effort": {
                "type": "string",
                "enum": [
                    "VERY_LOW",
                    "LOW",
                    "MEDIUM",
                    "HIGH",
                    "VERY_HIGH",
                    "UNKNOWN",
                ],
            },
            "min_minutes": {"type": ["integer", "null"]},
            "max_minutes": {"type": ["integer", "null"]},
            "confidence": {"type": "number"},
            "tasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["key", "title"],
                    "additionalProperties": True,
                    "properties": {
                        "key": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "type": {"type": "string"},
                        "priority": {"type": "string"},
                        "estimated_effort": {"type": "string"},
                        "min_minutes": {"type": ["integer", "null"]},
                        "max_minutes": {"type": ["integer", "null"]},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "related_requirements": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "related_deliverables": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "verification_method": {"type": "string"},
                        "acceptance_criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "resources": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "milestones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["key", "title"],
                    "additionalProperties": True,
                    "properties": {
                        "key": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "task_keys": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "verification_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["key", "title"],
                    "additionalProperties": True,
                    "properties": {
                        "key": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "method": {"type": "string"},
                        "task_keys": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["key", "description"],
                    "additionalProperties": True,
                    "properties": {
                        "key": {"type": "string"},
                        "description": {"type": "string"},
                        "severity": {"type": "string"},
                        "mitigation": {"type": "string"},
                        "related_task_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        },
    }
