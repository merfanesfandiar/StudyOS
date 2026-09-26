"""Specialized academic analyzers.

The universal analysis works without any of these. Each analyzer is optional and
runs only for the assignment types it understands, producing a namespaced
``SpecializedAnalysis`` whose ``data`` was validated by its own model. Nothing
here may leak domain assumptions into the universal core, and nothing solves the
assignment.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.models.enums import AssignmentType
from app.schemas.analysis import AnalyzerOutput, SpecializedAnalysis


@dataclass(frozen=True, slots=True)
class SpecializationContext:
    """Everything a specialized analyzer may read."""

    payload: dict[str, Any]
    analysis: AnalyzerOutput


class AcademicSpecializedAnalyzer(ABC):
    """Base class for one academic specialization.

    A subclass declares the assignment types it handles and returns a validated
    ``SpecializedAnalysis``. It is optional: the universal analysis works with
    no specialized analyzers registered at all.
    """

    name: str = "base"
    assignment_types: tuple[AssignmentType, ...] = ()

    @abstractmethod
    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        """Return a structured, domain-specific analysis, or ``None``."""
        raise NotImplementedError


def analysis_text(context: SpecializationContext) -> str:
    """Lowercased combined text of the assignment and its resources."""
    parts: list[str] = []
    assignment = context.payload.get("assignment", {})
    parts.extend([assignment.get("title") or "", assignment.get("description") or ""])
    for group in ("requirements", "constraints", "criteria", "deliverables"):
        for item in context.payload.get(group, []) or []:
            parts.extend(
                [item.get("title") or "", item.get("description") or "", item.get("value") or ""]
            )
    for document in context.payload.get("document_texts", []) or []:
        parts.append(document.get("text") or "")
    parts.append(context.payload.get("user_notes") or "")
    parts.append(context.analysis.summary)
    return "\n".join(part for part in parts if part).lower()


def mentions(text: str, *phrases: str) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) for phrase in phrases)


def applies(context: SpecializationContext, types: tuple[AssignmentType, ...]) -> bool:
    detected = {item.type for item in context.analysis.assignment_types}
    return bool(detected.intersection(types))


def named_after(text: str, *markers: str, limit: int = 6) -> list[str]:
    """Return identifiers mentioned right after a marker, e.g. "theorem 4.2"."""
    found: list[str] = []
    for marker in markers:
        pattern = rf"{re.escape(marker)}\s+([a-z0-9][a-z0-9.\-]{{0,24}})"
        for match in re.findall(pattern, text):
            if match not in found:
                found.append(match)
            if len(found) >= limit:
                return found
    return found


def any_type(context: SpecializationContext, *types: AssignmentType) -> bool:
    return applies(context, tuple(types))
