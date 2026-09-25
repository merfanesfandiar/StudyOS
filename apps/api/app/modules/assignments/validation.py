"""Centralized domain validation.

Pydantic validates the shape of a request. This module validates the rules that
only make sense with the rest of the specification in view - totals that must
balance, names that must be comparable, deadlines that must be timezone-aware.

Rules that need database access (parent cycles, dependency cycles) live next to
the data they protect, in ``requirements.py``.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.core.errors import AppError
from app.models import EvaluationCriterion

MAX_CRITERION_WEIGHT = Decimal("100")
CRITERION_TOTAL = Decimal("100.00")
WEIGHT_QUANTUM = Decimal("0.01")

_WHITESPACE = re.compile(r"\s+")


def ensure_utc(value: datetime | None, *, field: str = "deadline") -> datetime | None:
    """Reject naive datetimes instead of silently assuming UTC."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise AppError(
            422,
            "TIMEZONE_REQUIRED",
            f"The {field} must include a timezone offset.",
            {"field": field},
        )
    return value.astimezone(UTC)


def normalize_name(value: str) -> str:
    """Collapse internal whitespace and trim, preserving the author's casing."""
    return _WHITESPACE.sub(" ", value).strip()


def normalize_key(value: str) -> str:
    """Case-insensitive form used for duplicate detection."""
    return normalize_name(value).casefold()


def ensure_weight(value: Decimal) -> Decimal:
    """Validate a single criterion weight and quantize it to the column scale."""
    if value < 0:
        raise AppError(422, "INVALID_WEIGHT", "A criterion weight cannot be negative.")
    if value > MAX_CRITERION_WEIGHT:
        raise AppError(
            422,
            "INVALID_WEIGHT",
            "A criterion weight cannot exceed 100%.",
            {"weight": str(value)},
        )
    if value.quantize(WEIGHT_QUANTUM) != value:
        raise AppError(
            422,
            "INVALID_WEIGHT_PRECISION",
            "A criterion weight supports at most two decimal places.",
            {"weight": str(value)},
        )
    return value


def criteria_total(criteria: Sequence[EvaluationCriterion]) -> Decimal:
    return sum((criterion.weight for criterion in criteria), Decimal("0.00"))


def ensure_criteria_total(criteria: Sequence[EvaluationCriterion], *, required: bool) -> Decimal:
    """Check the grading total.

    Drafts may be mid-way through being built, so an unbalanced total is only an
    error when the specification is expected to be complete.
    """
    total = criteria_total(criteria)
    if required and total != CRITERION_TOTAL:
        raise AppError(
            422,
            "CRITERIA_TOTAL_INVALID",
            "Evaluation criteria must total exactly 100% before this assignment can be ready.",
            {"expected": 100, "actual": float(total)},
        )
    return total


def ensure_no_duplicate_titles(titles: Sequence[str], *, entity: str) -> None:
    """Reject exact duplicates that would make a specification ambiguous."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for title in titles:
        key = normalize_key(title)
        if key in seen:
            duplicates.add(normalize_name(title))
        seen.add(key)
    if duplicates:
        raise AppError(
            422,
            "DUPLICATE_ENTRY",
            f"Duplicate {entity} titles are not allowed: "
            + ", ".join(sorted(duplicates)),
            {"duplicates": sorted(duplicates)},
        )
