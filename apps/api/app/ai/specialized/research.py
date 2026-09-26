"""Research analyzer: question, sources, method and argument structure."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.ai.specialized.base import (
    AcademicSpecializedAnalyzer,
    SpecializationContext,
    analysis_text,
    mentions,
)
from app.models.enums import AssignmentType
from app.schemas.analysis import SpecializedAnalysis

_STYLES = {
    "apa": "APA",
    "mla": "MLA",
    "chicago": "Chicago",
    "harvard": "Harvard",
    "ieee": "IEEE",
    "vancouver": "Vancouver",
}


class ResearchData(BaseModel):
    research_question_stated: bool = False
    topic: str | None = None
    expected_source_types: list[str] = Field(default_factory=list)
    literature_requirements: list[str] = Field(default_factory=list)
    methodology_required: bool = False
    argument_requirements: list[str] = Field(default_factory=list)
    citation_requirements: list[str] = Field(default_factory=list)
    citation_style: str | None = None
    minimum_sources: int | None = None
    evidence_requirements: list[str] = Field(default_factory=list)
    expected_conclusion: bool = False


class ResearchAnalyzer(AcademicSpecializedAnalyzer):
    name = "research"
    assignment_types = (AssignmentType.RESEARCH, AssignmentType.LITERATURE_REVIEW)

    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        text = analysis_text(context)
        style = next((name for key, name in _STYLES.items() if key in text), None)
        minimum = None
        found = re.search(
            r"(?:at least|minimum of|minimum)\s+(\d+)\s+(?:peer-reviewed\s+)?sources", text
        )
        if found:
            minimum = int(found.group(1))
        peer_reviewed = "peer-reviewed" in text or "peer reviewed" in text
        data = ResearchData(
            research_question_stated=mentions(
                text, "research question", "research objective", "thesis", "hypothesis"
            ),
            topic=context.analysis.assignment_types[0].type.value
            if context.analysis.assignment_types
            else None,
            expected_source_types=(
                ["peer-reviewed articles"] if peer_reviewed else ["academic sources"]
            ),
            literature_requirements=[
                "Engage with existing work rather than only primary material",
                "Synthesize sources instead of listing them",
            ],
            methodology_required=mentions(text, "methodology", "method", "approach", "framework"),
            argument_requirements=[
                "State a clear position",
                "Support each claim with evidence",
                "Address at least one counter-argument where relevant",
            ],
            citation_requirements=(
                [f"Use {style} style"] if style else ["Use a consistent academic citation style"]
            ),
            citation_style=style,
            minimum_sources=minimum,
            evidence_requirements=[
                "Ground claims in cited sources",
                "Distinguish evidence from interpretation",
            ],
            expected_conclusion=mentions(text, "conclusion", "conclude", "recommend"),
        )
        summary = "Research work: question, sources, method and argument-evidence consistency."
        return SpecializedAnalysis(
            analyzer=self.name,
            assignment_types=list(self.assignment_types),
            data=data.model_dump(mode="json"),
            summary=summary,
            confidence=0.7,
        )
