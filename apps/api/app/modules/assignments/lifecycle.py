"""Assignment status machine.

The state an assignment is in is a promise about its specification, so it is
never set straight from a request body. ``READY_FOR_ANALYSIS`` is only reachable
through the readiness gate in ``readiness.py``, and the two analysis states are
reserved for the future AI layer. A client can still move an assignment back to
draft, mark it complete, or archive it.
"""

from app.core.errors import AppError
from app.models.enums import AssignmentStatus

#: States a client may request directly through ``PATCH /assignments/{id}``.
CLIENT_SETTABLE: frozenset[AssignmentStatus] = frozenset(
    {
        AssignmentStatus.DRAFT,
        AssignmentStatus.INCOMPLETE,
        AssignmentStatus.COMPLETED,
        AssignmentStatus.ARCHIVED,
    }
)

#: Explicit transition table. Backwards moves are allowed on purpose: a ready
#: assignment that the student reopens goes back to being a specification under
#: construction, not a dead end.
ALLOWED_TRANSITIONS: dict[AssignmentStatus, frozenset[AssignmentStatus]] = {
    AssignmentStatus.DRAFT: frozenset(
        {
            AssignmentStatus.DRAFT,
            AssignmentStatus.INCOMPLETE,
            AssignmentStatus.READY_FOR_ANALYSIS,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.ARCHIVED,
        }
    ),
    AssignmentStatus.INCOMPLETE: frozenset(
        {
            AssignmentStatus.INCOMPLETE,
            AssignmentStatus.DRAFT,
            AssignmentStatus.READY_FOR_ANALYSIS,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.ARCHIVED,
        }
    ),
    AssignmentStatus.READY_FOR_ANALYSIS: frozenset(
        {
            AssignmentStatus.READY_FOR_ANALYSIS,
            AssignmentStatus.DRAFT,
            AssignmentStatus.INCOMPLETE,
            AssignmentStatus.ANALYSIS_IN_PROGRESS,
            AssignmentStatus.ANALYZED,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.ARCHIVED,
        }
    ),
    AssignmentStatus.ANALYSIS_IN_PROGRESS: frozenset(
        {
            AssignmentStatus.ANALYSIS_IN_PROGRESS,
            AssignmentStatus.READY_FOR_ANALYSIS,
            AssignmentStatus.INCOMPLETE,
            AssignmentStatus.ANALYZED,
            AssignmentStatus.ARCHIVED,
        }
    ),
    AssignmentStatus.ANALYZED: frozenset(
        {
            AssignmentStatus.ANALYZED,
            AssignmentStatus.READY_FOR_ANALYSIS,
            AssignmentStatus.INCOMPLETE,
            AssignmentStatus.ARCHIVED,
        }
    ),
    AssignmentStatus.COMPLETED: frozenset(
        {
            AssignmentStatus.COMPLETED,
            AssignmentStatus.DRAFT,
            AssignmentStatus.INCOMPLETE,
            AssignmentStatus.ARCHIVED,
        }
    ),
    AssignmentStatus.ARCHIVED: frozenset({AssignmentStatus.DRAFT}),
    # Phase 1 wrote ACTIVE for exactly the state now called READY_FOR_ANALYSIS.
    # Kept so historical rows keep resolving to a real enum member.
    AssignmentStatus.ACTIVE: frozenset(
        {
            AssignmentStatus.ACTIVE,
            AssignmentStatus.DRAFT,
            AssignmentStatus.INCOMPLETE,
            AssignmentStatus.READY_FOR_ANALYSIS,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.ARCHIVED,
        }
    ),
}

#: States that represent the specification still being built.
SPECIFICATION_STATES: frozenset[AssignmentStatus] = frozenset(
    {
        AssignmentStatus.DRAFT,
        AssignmentStatus.INCOMPLETE,
        AssignmentStatus.READY_FOR_ANALYSIS,
        AssignmentStatus.ANALYSIS_IN_PROGRESS,
        AssignmentStatus.ANALYZED,
        AssignmentStatus.ACTIVE,
    }
)

#: States the future AI layer is expected to move an assignment into.
AI_OWNED_STATES: frozenset[AssignmentStatus] = frozenset(
    {AssignmentStatus.ANALYSIS_IN_PROGRESS, AssignmentStatus.ANALYZED}
)


#: Which stored states answer to each readiness filter value. ``DRAFT`` and
#: ``INCOMPLETE`` are both "not ready yet", and the legacy ``ACTIVE`` state
#: answers to ``READY_FOR_ANALYSIS`` so historical rows stay findable.
READINESS_STATUS_GROUPS: dict[AssignmentStatus, frozenset[str]] = {
    AssignmentStatus.DRAFT: frozenset({AssignmentStatus.DRAFT.value}),
    AssignmentStatus.INCOMPLETE: frozenset(
        {AssignmentStatus.DRAFT.value, AssignmentStatus.INCOMPLETE.value}
    ),
    AssignmentStatus.READY_FOR_ANALYSIS: frozenset(
        {
            AssignmentStatus.READY_FOR_ANALYSIS.value,
            AssignmentStatus.ACTIVE.value,
        }
    ),
    AssignmentStatus.ANALYSIS_IN_PROGRESS: frozenset(
        {AssignmentStatus.ANALYSIS_IN_PROGRESS.value}
    ),
    AssignmentStatus.ANALYZED: frozenset({AssignmentStatus.ANALYZED.value}),
    AssignmentStatus.COMPLETED: frozenset({AssignmentStatus.COMPLETED.value}),
    AssignmentStatus.ARCHIVED: frozenset({AssignmentStatus.ARCHIVED.value}),
}


def ensure_client_settable(target: AssignmentStatus) -> None:
    if target not in CLIENT_SETTABLE:
        raise AppError(
            422,
            "STATUS_NOT_CLIENT_SETTABLE",
            f"{target} cannot be set directly. Use the readiness endpoints to move an assignment "
            "through analysis.",
            {"requested": target.value, "allowed": sorted(item.value for item in CLIENT_SETTABLE)},
        )


def ensure_transition_allowed(current: AssignmentStatus, target: AssignmentStatus) -> None:
    if target in ALLOWED_TRANSITIONS.get(current, frozenset()):
        return
    raise AppError(
        422,
        "INVALID_STATUS_TRANSITION",
        f"An assignment cannot move from {current} to {target}.",
        {"from": current.value, "to": target.value},
    )
