"""Deterministic readiness analysis.

Everything in this module is pure: given the same specification it always
produces the same report, with no model call and no network access. The
completeness score is a weighted checklist result and must never be presented as
an AI confidence score.

A check is *blocking* when its failure makes the specification unusable for
analysis; failing a blocking check moves the assignment out of
``READY_FOR_ANALYSIS``. Advisory checks only lower the score.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.models import (
    Assignment,
    AssignmentRequirement,
    Deliverable,
    Document,
    EvaluationCriterion,
)
from app.models.enums import (
    AssignmentStatus,
    CompletenessCheckStatus,
    RequirementStatus,
)
from app.schemas.specification import CompletenessCheck, ReadinessReport

#: A specification at or above this score counts as complete. Readiness itself
#: never depends on it: readiness is driven by blocking checks only.
COMPLETENESS_BAR = 90

#: Below this length a description is treated as a placeholder, not a brief.
DESCRIPTION_MIN_LENGTH = 80

TOTAL_WEIGHT = 100


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _check(
    field: str,
    label: str,
    status: CompletenessCheckStatus,
    message: str,
    weight: int,
    blocking: bool,
) -> CompletenessCheck:
    return CompletenessCheck(
        field=field, label=label, status=status, message=message, weight=weight, blocking=blocking
    )


def evaluate_completeness(
    *,
    title: str,
    description: str | None,
    deadline: datetime | None,
    has_course: bool,
    requirements: Sequence[AssignmentRequirement],
    criteria: Sequence[EvaluationCriterion],
    constraint_count: int,
    deliverables: Sequence[Deliverable],
    technology_count: int,
    resources: Sequence[Document],
    now: datetime | None = None,
) -> ReadinessReport:
    """Return the deterministic completeness report for one specification."""
    moment = now or datetime.now(UTC)
    checks: list[CompletenessCheck] = []

    checks.append(
        _check(
            "title",
            "Basic information",
            CompletenessCheckStatus.PASS if title.strip() else CompletenessCheckStatus.FAIL,
            "Assignment title is present."
            if title.strip()
            else "Assignment title is missing.",
            10,
            True,
        )
    )

    body = (description or "").strip()
    if not body:
        description_status, description_message = (
            CompletenessCheckStatus.FAIL,
            "No description has been written yet.",
        )
    elif len(body) < DESCRIPTION_MIN_LENGTH:
        description_status, description_message = (
            CompletenessCheckStatus.WARNING,
            f"Description is {len(body)} characters; {DESCRIPTION_MIN_LENGTH}+ usually carries "
            "enough context for analysis.",
        )
    else:
        description_status, description_message = (
            CompletenessCheckStatus.PASS,
            "Description is present and detailed.",
        )
    checks.append(
        _check("description", "Description", description_status, description_message, 10, True)
    )

    checks.append(
        _check(
            "course",
            "Course",
            CompletenessCheckStatus.PASS if has_course else CompletenessCheckStatus.FAIL,
            "Assignment belongs to a course." if has_course else "Assignment has no course.",
            5,
            True,
        )
    )

    deadline_value = _as_utc(deadline)
    if deadline_value is None:
        checks.append(
            _check(
                "deadline",
                "Deadline",
                CompletenessCheckStatus.FAIL,
                "No deadline is set.",
                15,
                True,
            )
        )
    elif deadline_value < moment:
        checks.append(
            _check(
                "deadline",
                "Deadline",
                CompletenessCheckStatus.WARNING,
                "Deadline is in the past.",
                15,
                True,
            )
        )
    else:
        checks.append(
            _check(
                "deadline",
                "Deadline",
                CompletenessCheckStatus.PASS,
                "Deadline is set and still upcoming.",
                15,
                True,
            )
        )

    if not requirements:
        requirements_status, requirements_message = (
            CompletenessCheckStatus.FAIL,
            "No requirements yet. Add the first requirement to describe what must be built.",
        )
    else:
        requirements_status, requirements_message = (
            CompletenessCheckStatus.PASS,
            f"{len(requirements)} requirement(s) defined.",
        )
    checks.append(
        _check(
            "requirements",
            "Requirements",
            requirements_status,
            requirements_message,
            20,
            True,
        )
    )

    total_weight = sum((criterion.weight for criterion in criteria), Decimal("0.00"))
    if not criteria:
        criteria_status, criteria_message = (
            CompletenessCheckStatus.FAIL,
            "No evaluation criteria. Weight how the work will be graded.",
        )
    elif total_weight == Decimal("100.00"):
        criteria_status, criteria_message = (
            CompletenessCheckStatus.PASS,
            f"Evaluation criteria total exactly 100% across {len(criteria)} criterion/criteria.",
        )
    else:
        # A partial total is a blocking failure, not a warning: grading weights
        # that do not add up to 100 make the assignment impossible to mark.
        criteria_status, criteria_message = (
            CompletenessCheckStatus.FAIL,
            f"Evaluation criteria total {total_weight}%; they must total exactly 100% "
            "before the assignment can be marked ready.",
        )
    checks.append(
        _check(
            "evaluation_criteria",
            "Evaluation criteria",
            criteria_status,
            criteria_message,
            15,
            True,
        )
    )

    checks.append(
        _check(
            "constraints",
            "Constraints",
            (
                CompletenessCheckStatus.PASS
                if constraint_count
                else CompletenessCheckStatus.WARNING
            ),
            (
                f"{constraint_count} constraint(s) recorded."
                if constraint_count
                else (
                    "No constraints recorded. Technology or format limits are usually"
                    " worth writing down."
                )
            ),
            10,
            False,
        )
    )

    checks.append(
        _check(
            "deliverables",
            "Deliverables",
            (
                CompletenessCheckStatus.PASS
                if deliverables
                else CompletenessCheckStatus.WARNING
            ),
            (
                f"{len(deliverables)} deliverable(s) expected."
                if deliverables
                else "No deliverables listed yet."
            ),
            5,
            False,
        )
    )

    checks.append(
        _check(
            "technologies",
            "Technologies",
            CompletenessCheckStatus.PASS if technology_count else CompletenessCheckStatus.WARNING,
            (
                f"{technology_count} technology/technologies recorded."
                if technology_count
                else "No technologies recorded, so required tooling is ambiguous."
            ),
            5,
            False,
        )
    )

    checks.append(
        _check(
            "resources",
            "Resources",
            CompletenessCheckStatus.PASS if resources else CompletenessCheckStatus.WARNING,
            (
                f"{len(resources)} resource file(s) attached."
                if resources
                else "No resources attached to the brief."
            ),
            5,
            False,
        )
    )

    return build_report(checks)


def build_report(checks: Sequence[CompletenessCheck]) -> ReadinessReport:
    """Score a set of checks and decide readiness.

    A warning earns half of its weight. Readiness only depends on blocking
    checks, so optional information can never block analysis.
    """
    earned = Decimal("0")
    for check in checks:
        if check.status is CompletenessCheckStatus.PASS:
            earned += Decimal(check.weight)
        elif check.status is CompletenessCheckStatus.WARNING:
            earned += Decimal(check.weight) / 2
    score = int((earned / Decimal(TOTAL_WEIGHT) * Decimal(100)).quantize(Decimal("1")))
    score = max(0, min(100, score))

    failing = [check.field for check in checks if check.status is CompletenessCheckStatus.FAIL]
    warnings = [
        check.field for check in checks if check.status is CompletenessCheckStatus.WARNING
    ]
    blocking_failure = any(
        check.blocking for check in checks if check.status is CompletenessCheckStatus.FAIL
    )
    return ReadinessReport(
        score=score,
        is_complete=not failing and score >= COMPLETENESS_BAR,
        is_ready_for_analysis=not blocking_failure,
        completeness_bar=COMPLETENESS_BAR,
        failing_checks=failing,
        warning_checks=warnings,
        checks=list(checks),
    )


def analyze_assignment(assignment: Assignment, *, now: datetime | None = None) -> ReadinessReport:
    """Convenience wrapper that reads a loaded assignment graph."""
    return evaluate_completeness(
        title=assignment.title,
        description=assignment.description,
        deadline=assignment.deadline,
        has_course=assignment.course_id is not None,
        requirements=assignment.requirements,
        criteria=assignment.criteria,
        constraint_count=len(assignment.constraints),
        deliverables=assignment.deliverables,
        technology_count=len(assignment.technologies),
        resources=assignment.documents,
        now=now,
    )


def readiness_state(report: ReadinessReport, current: AssignmentStatus) -> AssignmentStatus:
    """Return the lifecycle state implied by a report, leaving terminals alone."""
    if current in {AssignmentStatus.COMPLETED, AssignmentStatus.ARCHIVED}:
        return current
    if report.is_ready_for_analysis:
        return AssignmentStatus.READY_FOR_ANALYSIS
    if current is AssignmentStatus.DRAFT and not report.failing_checks:
        return AssignmentStatus.DRAFT
    return AssignmentStatus.INCOMPLETE


def requirement_progress(requirements: Sequence[AssignmentRequirement]) -> tuple[int, int]:
    """Return ``(completed, total)`` where verified counts as completed."""
    total = len(requirements)
    completed = sum(
        1
        for requirement in requirements
        if requirement.status
        in {RequirementStatus.COMPLETED, RequirementStatus.VERIFIED}
    )
    return completed, total
