"""Registry of specialized academic analyzers.

Adding a new academic specialization means adding one module here and one entry
to ``ANALYZERS``. The universal analyzer never changes.
"""

from __future__ import annotations

from app.ai.specialized.base import (
    AcademicSpecializedAnalyzer,
    SpecializationContext,
)
from app.ai.specialized.data_analysis import DataAnalysisAnalyzer
from app.ai.specialized.essay import EssayAnalyzer
from app.ai.specialized.lab import LabAnalyzer
from app.ai.specialized.mathematics import MathematicsAnalyzer
from app.ai.specialized.presentation import PresentationAnalyzer
from app.ai.specialized.programming import ProgrammingAnalyzer
from app.ai.specialized.research import ResearchAnalyzer
from app.schemas.analysis import SpecializedAnalysis

ANALYZERS: tuple[AcademicSpecializedAnalyzer, ...] = (
    MathematicsAnalyzer(),
    ResearchAnalyzer(),
    EssayAnalyzer(),
    LabAnalyzer(),
    PresentationAnalyzer(),
    DataAnalysisAnalyzer(),
    ProgrammingAnalyzer(),
)


def analyze_specializations(
    context: SpecializationContext,
) -> list[SpecializedAnalysis]:
    """Run every applicable analyzer in a deterministic order."""
    results: list[SpecializedAnalysis] = []
    for analyzer in ANALYZERS:
        detected = {item.type for item in context.analysis.assignment_types}
        if not detected.intersection(analyzer.assignment_types):
            continue
        result = analyzer.analyze(context)
        if result is not None:
            results.append(result)
    return results


__all__ = [
    "ANALYZERS",
    "AcademicSpecializedAnalyzer",
    "SpecializationContext",
    "analyze_specializations",
]
