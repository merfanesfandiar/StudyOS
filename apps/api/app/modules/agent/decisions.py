"""Structured decisions and the validation pipeline.

A model never mutates state. It returns a JSON object conforming to
:class:`AgentDecisionOutput`, which then passes three independent checks before
the runtime will act on it:

1. **Schema.** Pydantic validates the shape, the closed action vocabulary and
   the per-action required arguments. This is where an invented action dies.
2. **Semantic.** The decision is checked against the run it claims to act in: is
   the named task real, is it in this plan, is it still executable, does the
   artifact exist. A model cannot reference a task the runtime never selected.
3. **Permission.** The action is checked against the mode and the plan. A
   supervised run may not approve its own work, an autonomous run may not skip an
   approval the task actually depends on, and no action may grant a capability.

Each layer can fail on its own, and a failure records *which* layer failed. That
distinction is what makes a model that consistently emits malformed output
visible as a problem rather than as an unexplained retry loop.

What is deliberately absent: private reasoning. ``reason`` is a short structured
justification the student can read. Nothing here stores, requests or displays a
chain of thought, and the prompt says so explicitly.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.models.enums import (
    AcademicTaskStatus,
    AgentAction,
    AgentArtifactType,
    AgentCheckpointType,
    AgentExecutionStatus,
    AgentRunMode,
)

#: Above this the runtime treats a decision as a guess rather than a judgement
#: and pauses for the student. A model that is 95% sure should say so.
CONFIDENCE_FLOOR = 0.55


class AgentDecisionOutput(BaseModel):
    """What a provider must return for one runtime step.

    A closed model on purpose. ``action`` is an enum, and every action declares
    which of the other fields it requires, so a decision cannot be structurally
    valid while being semantically empty — "EXECUTE_TASK" with no ``task_key`` is
    rejected here rather than crashing three layers down.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: AgentAction
    #: Short, user-readable justification. Explicitly *not* reasoning.
    reason: str = Field(min_length=1, max_length=1_000)
    expected_output: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Required by EXECUTE_TASK, RETRY_TASK, COMPLETE_TASK and MARK_BLOCKED.
    task_key: str | None = Field(default=None, max_length=20)
    #: Required by CREATE_ARTIFACT.
    artifact_type: AgentArtifactType | None = None
    artifact_title: str | None = Field(default=None, max_length=240)
    #: Required by ASK_USER and REQUEST_APPROVAL.
    question: str | None = Field(default=None, max_length=1_000)
    checkpoint_type: AgentCheckpointType | None = None
    checkpoint_options: list[str] | None = Field(default=None, max_length=8)
    #: Required by UPDATE_ARTIFACT.
    artifact_id: str | None = None
    #: Why a task is blocked. Required by MARK_BLOCKED, because a block the
    #: student cannot act on is not useful to them.
    blocked_reason: str | None = Field(default=None, max_length=500)

    @field_validator("confidence")
    @classmethod
    def _default_mid_confidence(cls, value: float) -> float:
        # A model that omits confidence entirely is not claiming certainty; 0.5
        # is the honest default and keeps it on the borderline rather than 0.0,
        # which would make every decision a checkpoint.
        return value

    def missing_for(self) -> list[str]:
        """Fields this action requires that are absent.

        Returned rather than raised so the schema layer can report *all* the
        problems with a decision at once. A model told three things it got wrong
        fixes three things; a model told one at a time needs three round trips.
        """
        needed: list[str] = []
        if (
            self.action
            in {
                AgentAction.EXECUTE_TASK,
                AgentAction.RETRY_TASK,
                AgentAction.COMPLETE_TASK,
                AgentAction.MARK_BLOCKED,
            }
            and not self.task_key
        ):
            needed.append("task_key")
        if self.action in {AgentAction.ASK_USER, AgentAction.REQUEST_APPROVAL}:
            if not self.question:
                needed.append("question")
            if self.action == AgentAction.REQUEST_APPROVAL and not self.checkpoint_type:
                needed.append("checkpoint_type")
        if self.action == AgentAction.CREATE_ARTIFACT:
            if not self.artifact_type:
                needed.append("artifact_type")
            if not self.artifact_title:
                needed.append("artifact_title")
        if self.action == AgentAction.UPDATE_ARTIFACT and not self.artifact_id:
            needed.append("artifact_id")
        if self.action == AgentAction.MARK_BLOCKED and not self.blocked_reason:
            needed.append("blocked_reason")
        return needed

    def response_schema(self) -> dict[str, Any]:
        """JSON schema handed to the provider."""
        return self.model_json_schema()


class DecisionRejected(Exception):
    """A decision failed validation.

    ``layer`` is the important field: ``"schema"`` means the model emitted
    something malformed, ``"semantic"`` means it referenced reality
    incorrectly, ``"permission"`` means it asked for something the mode forbids.
    They call for different fixes and are reported separately.
    """

    def __init__(
        self,
        layer: Literal["schema", "semantic", "permission"],
        code: str,
        message: str,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.layer = layer
        self.code = code
        self.message = message
        self.errors = errors or []


@dataclass(frozen=True, slots=True)
class TaskView:
    """The slice of a plan task the validator needs.

    A narrow projection rather than the ORM entity, so validation stays a pure
    function and can be unit-tested without a database.
    """

    key: str
    status: str
    position: int
    depends_on: frozenset[str] = frozenset()
    acceptance_criteria: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything validation needs to judge a decision against the world."""

    run_id: UUID
    mode: AgentRunMode
    #: Keys of tasks that may be acted on right now. Anything else is rejected
    #: even if it exists in the plan: an approved plan is a graph, and jumping a
    #: blocked predecessor is the failure mode that matters most.
    executable_task_keys: frozenset[str] = frozenset()
    tasks: Mapping[str, TaskView] = field(default_factory=dict)
    #: Artifact ids already created in this run.
    artifact_ids: frozenset[str] = frozenset()
    #: Task keys whose acceptance criteria are not satisfied by their predecessors
    #: and which therefore require human approval before they are auto-approved.
    approval_required_keys: frozenset[str] = frozenset()


def parse_decision(raw: str | bytes) -> AgentDecisionOutput:
    """Layer 1: parse and schema-validate a provider response.

    Accepts raw text because providers return text. Tolerant of a fenced code
    block but nothing else: a provider that wraps JSON in prose is a provider bug,
    and silently extracting the JSON would hide it.
    """
    text = (raw.decode("utf-8") if isinstance(raw, bytes) else raw).strip()
    if text.startswith("```"):
        # Strip an optional language tag and the fence, but only if it is the
        # whole envelope. Mixed prose around a JSON object stays an error.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            text = candidate
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecisionRejected(
            "schema",
            "AGENT_DECISION_NOT_JSON",
            "The decision was not valid JSON.",
            [{"loc": ["body"], "msg": str(exc)}],
        ) from exc
    if not isinstance(data, dict):
        raise DecisionRejected(
            "schema",
            "AGENT_DECISION_NOT_OBJECT",
            "The decision must be a JSON object.",
            [{"loc": ["body"], "msg": f"got {type(data).__name__}"}],
        )
    try:
        decision = AgentDecisionOutput.model_validate(data)
    except ValidationError as exc:
        raise DecisionRejected(
            "schema",
            "AGENT_DECISION_SCHEMA",
            "The decision did not match the required structure.",
            [
                {"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ],
        ) from exc
    missing = decision.missing_for()
    if missing:
        raise DecisionRejected(
            "schema",
            "AGENT_DECISION_INCOMPLETE",
            f"The {decision.action.value} decision is missing required fields: "
            f"{', '.join(missing)}.",
            [{"loc": [m], "msg": "required for this action"} for m in missing],
        )
    return decision


def validate_semantics(decision: AgentDecisionOutput, ctx: DecisionContext) -> None:
    """Layer 2: check the decision against the run's actual state."""
    key = decision.task_key
    if key is not None:
        task = ctx.tasks.get(key)
        if task is None:
            raise DecisionRejected(
                "semantic",
                "AGENT_TASK_UNKNOWN",
                f"Task {key!r} is not part of this plan.",
                [{"loc": ["task_key"], "msg": f"unknown task {key}"}],
            )
        if (
            decision.action
            in {
                AgentAction.EXECUTE_TASK,
                AgentAction.RETRY_TASK,
                AgentAction.COMPLETE_TASK,
                AgentAction.MARK_BLOCKED,
            }
            and key not in ctx.executable_task_keys
        ):
            raise DecisionRejected(
                "semantic",
                "AGENT_TASK_NOT_EXECUTABLE",
                f"Task {key!r} cannot be acted on right now.",
                [
                    {
                        "loc": ["task_key"],
                        "msg": (
                            f"task status is {task.status}; executable tasks are "
                            f"{sorted(ctx.executable_task_keys) or 'none'}"
                        ),
                    }
                ],
            )
        if (
            decision.action == AgentAction.COMPLETE_TASK
            and task.status != AcademicTaskStatus.IN_PROGRESS.value
            and task.status != AcademicTaskStatus.COMPLETED.value
        ):
            raise DecisionRejected(
                "semantic",
                "AGENT_TASK_NOT_IN_PROGRESS",
                f"Task {key!r} cannot be completed because it is {task.status.lower()}.",
                [{"loc": ["task_key"], "msg": f"status is {task.status}"}],
            )
    if (
        decision.action == AgentAction.UPDATE_ARTIFACT
        and decision.artifact_id not in ctx.artifact_ids
    ):
        raise DecisionRejected(
            "semantic",
            "AGENT_ARTIFACT_UNKNOWN",
            "That artifact does not belong to this run.",
            [{"loc": ["artifact_id"], "msg": f"unknown artifact {decision.artifact_id}"}],
        )


def validate_permissions(decision: AgentDecisionOutput, ctx: DecisionContext) -> None:
    """Layer 3: check the decision against what this run mode allows.

    The load-bearing rule: a run may not approve its own work. ``REQUEST_APPROVAL``
    is how a model asks a student, and ``COMPLETE_TASK`` is how a task is marked
    done — but neither lets the runtime self-approve a task whose acceptance
    criteria depend on human judgement, in either mode.
    """
    if decision.action == AgentAction.REQUEST_APPROVAL:
        if decision.checkpoint_type not in {
            AgentCheckpointType.APPROVAL,
            AgentCheckpointType.REVIEW,
        }:
            raise DecisionRejected(
                "permission",
                "AGENT_APPROVAL_TYPE_INVALID",
                "An approval request must be an APPROVAL or REVIEW checkpoint.",
                [{"loc": ["checkpoint_type"], "msg": "must be APPROVAL or REVIEW"}],
            )
        return
    if decision.action == AgentAction.PAUSE_RUN and ctx.mode == AgentRunMode.AUTONOMOUS:
        raise DecisionRejected(
            "permission",
            "AGENT_PAUSE_NOT_ALLOWED",
            "An autonomous run may not pause itself; it runs to the next real wall.",
            [{"loc": ["action"], "msg": "PAUSE_RUN is a supervised-mode action"}],
        )
    if (
        decision.action == AgentAction.COMPLETE_TASK
        and decision.task_key in ctx.approval_required_keys
    ):
        raise DecisionRejected(
            "permission",
            "AGENT_SELF_APPROVAL_FORBIDDEN",
            (
                f"Task {decision.task_key!r} needs a human to confirm it. "
                "Request approval instead of completing it."
            ),
            [{"loc": ["action"], "msg": "self-approval is never permitted"}],
        )
    if decision.confidence < CONFIDENCE_FLOOR and decision.action in {
        AgentAction.EXECUTE_TASK,
        AgentAction.CREATE_ARTIFACT,
        AgentAction.UPDATE_ARTIFACT,
        AgentAction.COMPLETE_TASK,
    }:
        raise DecisionRejected(
            "permission",
            "AGENT_CONFIDENCE_TOO_LOW",
            (
                f"Confidence {decision.confidence:.2f} is below the {CONFIDENCE_FLOOR:.2f} "
                "floor for this action."
            ),
            [{"loc": ["confidence"], "msg": "ask the student instead"}],
        )


def validate(
    raw: str | bytes,
    ctx: DecisionContext,
) -> tuple[AgentDecisionOutput, AgentAction]:
    """Run all three layers. Returns the decision and the action it resolved to."""
    decision = parse_decision(raw)
    validate_semantics(decision, ctx)
    validate_permissions(decision, ctx)
    return decision, decision.action


#: Mapping from action to the execution status it implies on success, so the
#: runtime and the UI agree on what each action means without duplicating a table.
ACTION_OUTCOME: dict[AgentAction, AgentExecutionStatus] = {
    AgentAction.EXECUTE_TASK: AgentExecutionStatus.SUCCESS,
    AgentAction.RETRY_TASK: AgentExecutionStatus.FAILED,
    AgentAction.COMPLETE_TASK: AgentExecutionStatus.SUCCESS,
    AgentAction.CREATE_ARTIFACT: AgentExecutionStatus.SUCCESS,
    AgentAction.UPDATE_ARTIFACT: AgentExecutionStatus.SUCCESS,
    AgentAction.REVIEW_RESULT: AgentExecutionStatus.PARTIAL_SUCCESS,
    AgentAction.ASK_USER: AgentExecutionStatus.NEEDS_USER_INPUT,
    AgentAction.REQUEST_APPROVAL: AgentExecutionStatus.NEEDS_APPROVAL,
    AgentAction.MARK_BLOCKED: AgentExecutionStatus.BLOCKED,
    AgentAction.PAUSE_RUN: AgentExecutionStatus.SKIPPED,
}
