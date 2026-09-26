"""Essay analyzer: thesis, structure and evidence requirements."""

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

_STYLES = ("apa", "mla", "chicago", "harvard")


class EssayData(BaseModel):
    thesis_expected: bool = False
    structure: list[str] = Field(default_factory=list)
    argument_requirements: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    citation_requirements: list[str] = Field(default_factory=list)
    citation_style: str | None = None
    word_limit: int | None = None
    page_limit: int | None = None
    style_requirements: list[str] = Field(default_factory=list)
    revision_needs: list[str] = Field(default_factory=list)


class EssayAnalyzer(AcademicSpecializedAnalyzer):
    name = "essay"
    assignment_types = (AssignmentType.ESSAY,)

    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        text = analysis_text(context)
        words = re.search(r"(\d{3,5})\s*words", text)
        pages = re.search(r"(\d{1,3})\s*(?:pages|page)", text)
        style = next((value.upper() for value in _STYLES if value in text), None)
        data = EssayData(
            thesis_expected=mentions(text, "thesis", "argument", "position", "claim"),
            structure=[
                "Introduction with a clear thesis",
                "Body paragraphs each advancing one point",
                "Conclusion that follows from the argument",
            ],
            argument_requirements=[
                "One central argument sustained throughout",
                "Logical progression between paragraphs",
            ],
            evidence_requirements=[
                "Support claims with evidence or examples",
                "Explain how each piece of evidence supports the point",
            ],
            citation_requirements=(
                [f"Use {style} style"] if style else ["Cite sources consistently where required"]
            ),
            citation_style=style,
            word_limit=int(words.group(1)) if words else None,
            page_limit=int(pages.group(1)) if pages else None,
            style_requirements=["Formal academic register"],
            revision_needs=[
                "Proofread for grammar and clarity",
                "Check the argument answers the prompt",
            ],
        )
        return SpecializedAnalysis(
            analyzer=self.name,
            assignment_types=list(self.assignment_types),
            data=data.model_dump(mode="json"),
            summary="Essay work: thesis, structured argument and evidence.",
            confidence=0.65,
        )
