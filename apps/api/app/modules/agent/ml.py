"""ML extension points, Phase 5 edition.

These interfaces exist now and are deliberately inert. The reason to add them in
Phase 5 rather than when a model is available is that *where* a predictor is
allowed to sit is an architectural decision, and retrofitting it later tends to
put it somewhere convenient rather than somewhere safe.

The rule this module encodes: **a predictor may suggest, the runtime decides.**

Concretely, a predictor can:

* return a task key it thinks should come next, as a *hint*
* return per-task risk scores, as display data
* return an estimated difficulty, for context budgeting

It cannot:

* return a task that is not executable
* override the dependency ordering
* authorise or approve anything
* change a run's status
* cause a tool to be invoked

That is enforced by *where* the result is used: :class:`MLContextFeatures` is
passed into the selection step as an advisory input and its suggestion is only
honoured if that task is already in the executable set. A predictor that
suggests a blocked task has its suggestion discarded, and the fact is recorded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from app.modules.agent.context import MLContextFeatures
from app.modules.agent.selection import TaskNode

#: Empty features returned when no predictor is registered. A named constant
#: rather than ``None`` so callers never branch on "is there a model" and
#: accidentally treat "no model" as "zero risk".
NO_PREDICTIONS: Final = MLContextFeatures()


class TaskPredictor(Protocol):
    """Ranks or scores executable tasks.

    Implementations must be pure: same tasks in, same ranking out. A predictor
    that reaches a network or a clock would make runs unreproducible, which is
    the property the runtime is built on.
    """

    name: str

    def rank(self, tasks: Sequence[TaskNode]) -> tuple[str, ...]:
        """Return task keys, best first. Only executable tasks may be named."""
        ...

    def risk(self, tasks: Sequence[TaskNode]) -> Mapping[str, float]:
        """Return a 0..1 difficulty estimate per task key."""
        ...


class PredictorRegistry:
    """Holds optional predictors. Empty by default, and that is the normal case.

    One predictor is consulted, the first registered. Multiple predictors would
    need an arbitration rule, and inventing one to support a model that does not
    exist yet is how a silent priority inversion gets shipped.
    """

    def __init__(self, predictor: TaskPredictor | None = None) -> None:
        self._predictor = predictor

    @property
    def is_empty(self) -> bool:
        return self._predictor is None

    def register(self, predictor: TaskPredictor) -> None:
        if self._predictor is not None:
            raise ValueError(
                "A predictor is already registered; resolve the arbitration rule first."
            )
        self._predictor = predictor

    def features(self, tasks: Sequence[TaskNode]) -> MLContextFeatures:
        """Ask the predictor for advice, degrading safely on any fault.

        A predictor is a heuristic, not infrastructure. If it raises, the runtime
        proceeds with no advice rather than failing the run — but the failure is
        recorded so a permanently broken predictor is visible.
        """
        if self._predictor is None:
            return NO_PREDICTIONS
        try:
            ranked = tuple(self._predictor.rank(tasks))
            risks = dict(self._predictor.risk(tasks))
        except Exception:  # noqa: BLE001 - a heuristic must never break a run
            return MLContextFeatures(model_version=f"{self._predictor.name}:error")
        return MLContextFeatures(
            suggested_task_key=ranked[0] if ranked else None,
            risk_scores=risks,
            model_version=self._predictor.name,
        )


@dataclass(frozen=True, slots=True)
class AdvisoryResult:
    """The outcome of consulting a predictor, for the event trail.

    ``applied`` is almost always the interesting field: a suggestion that was
    discarded because the task was not executable is exactly the kind of thing
    an audit needs to show.
    """

    suggestion: str | None
    applied: bool
    reason: str


def advise(
    features: MLContextFeatures,
    *,
    selection: object,
    executable: frozenset[str],
) -> AdvisoryResult:
    """Apply a predictor's suggestion only if it is legal.

    The check is membership in the executable set. That single condition is what
    guarantees a predictor cannot talk the runtime past a dependency, because the
    executable set was computed from the plan graph without reference to the
    predictor.
    """
    if features.is_empty() or features.suggested_task_key is None:
        return AdvisoryResult(None, False, "No predictor suggestion.")
    suggestion = features.suggested_task_key
    if suggestion not in executable:
        return AdvisoryResult(
            suggestion,
            False,
            f"Prediction for {suggestion!r} discarded: the task is not executable.",
        )
    chosen = getattr(selection, "task", None)
    if chosen is None or chosen.key == suggestion:
        return AdvisoryResult(suggestion, True, "Prediction matched the selected task.")
    return AdvisoryResult(
        suggestion,
        False,
        (
            f"Prediction for {suggestion!r} recorded but not applied; the graph "
            f"ordering chose {chosen.key!r}."
        ),
    )


@dataclass(frozen=True, slots=True)
class WorkerCapability:
    """Declares what a future worker may do.

    Exists so that when a real research or writing worker is added, its boundary
    is expressed once as data that can be asserted on, rather than described in a
    comment. :func:`assert_worker_is_safe` is the check a test would call.
    """

    name: str
    may_read_student_data: bool = True
    may_write_artifacts: bool = True
    may_execute_code: bool = False
    may_access_network: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "may_read_student_data": self.may_read_student_data,
            "may_write_artifacts": self.may_write_artifacts,
            "may_execute_code": self.may_execute_code,
            "may_access_network": self.may_access_network,
        }


#: Capabilities a Phase 5 worker is not permitted to declare.
UNSAFE_WORKER_CAPABILITIES: Final[tuple[str, ...]] = ("may_execute_code", "may_access_network")


def assert_worker_is_safe(capability: WorkerCapability) -> None:
    """Raise if a worker declares a capability the runtime cannot grant.

    The default for both flags is ``False`` and this refuses ``True``, which is
    the right direction: a new capability has to be argued for in review, not
    merely not-argued-against.
    """
    unsafe = [name for name in UNSAFE_WORKER_CAPABILITIES if getattr(capability, name)]
    if unsafe:
        raise ValueError(
            f"Worker {capability.name!r} declares capabilities the runtime cannot grant: {unsafe}"
        )


#: Every tool the runtime exposes, with its boundary attached. Used by the
#: capabilities endpoint and asserted in tests, so the documented boundary and
#: the implemented boundary cannot drift apart.
WORKER_CAPABILITIES: Final[tuple[WorkerCapability, ...]] = (
    WorkerCapability("read_context"),
    WorkerCapability("write_artifact"),
    WorkerCapability("request_checkpoint"),
)


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    """The invariants the runtime holds regardless of configuration.

    Exists as data so tests can assert the policy directly instead of inferring
    it from behaviour spread across five modules.
    """

    #: No capability in this runtime can execute untrusted input.
    executes_untrusted_input: bool = False
    #: The agent may not approve its own work.
    self_approval_allowed: bool = False
    #: Every state change is validated against a transition table.
    validated_transitions: bool = True
    #: Every step is persisted before it is acted on.
    durable_before_effect: bool = True
    #: Decision rationale is stored; internal reasoning is never requested.
    stores_reasoning: bool = False

    def violations(self) -> list[str]:
        """Names of invariants this runtime is violating. Always empty in Phase 5."""
        found = []
        if self.executes_untrusted_input:
            found.append("executes_untrusted_input")
        if self.self_approval_allowed:
            found.append("self_approval_allowed")
        if not self.validated_transitions:
            found.append("validated_transitions")
        if not self.durable_before_effect:
            found.append("durable_before_effect")
        if self.stores_reasoning:
            found.append("stores_reasoning")
        return found


#: The policy this runtime actually implements.
RUNTIME_POLICY: Final = RuntimePolicy()


def assert_policy(policy: RuntimePolicy = RUNTIME_POLICY) -> None:
    if violations := policy.violations():
        raise ValueError(f"Agent runtime policy violated: {violations}")


__all__ = [
    "NO_PREDICTIONS",
    "RUNTIME_POLICY",
    "UNSAFE_WORKER_CAPABILITIES",
    "WORKER_CAPABILITIES",
    "AdvisoryResult",
    "MLContextFeatures",
    "PredictorRegistry",
    "RuntimePolicy",
    "TaskPredictor",
    "WorkerCapability",
    "advise",
    "assert_policy",
    "assert_worker_is_safe",
]
