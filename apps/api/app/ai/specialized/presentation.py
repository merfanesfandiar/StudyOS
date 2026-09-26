"""Presentation analyzer: duration, audience, structure and delivery."""

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


class PresentationData(BaseModel):
    duration_minutes: int | None = None
    audience: str | None = None
    required_topics: list[str] = Field(default_factory=list)
    slide_count: int | None = None
    structure: list[str] = Field(default_factory=list)
    visual_requirements: list[str] = Field(default_factory=list)
    speaking_requirements: list[str] = Field(default_factory=list)
    qa_required: bool = False
    source_requirements: list[str] = Field(default_factory=list)


class PresentationAnalyzer(AcademicSpecializedAnalyzer):
    name = "presentation"
    assignment_types = (AssignmentType.PRESENTATION,)

    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        text = analysis_text(context)
        minutes = re.search(r"(\d{1,3})\s*(?:min|minute)", text)
        slides = re.search(r"(\d{1,3})\s*slides", text)
        topics = [question.title for question in context.analysis.normalized_requirements][:6]
        data = PresentationData(
            duration_minutes=int(minutes.group(1)) if minutes else None,
            audience=(
                "Instructor and classmates"
                if mentions(text, "class", "classmates", "peers")
                else None
            ),
            required_topics=topics,
            slide_count=int(slides.group(1)) if slides else None,
            structure=["Introduction", "Main points", "Conclusion", "Questions"],
            visual_requirements=["Slides should be legible and not overloaded with text"],
            speaking_requirements=[
                "Stay within the time limit",
                "Speak to the audience, not the slides",
            ],
            qa_required=mentions(text, "q&a", "questions", "discussion"),
            source_requirements=(
                ["Cite sources on the slides"]
                if mentions(text, "cite", "sources", "references")
                else []
            ),
        )
        return SpecializedAnalysis(
            analyzer=self.name,
            assignment_types=list(self.assignment_types),
            data=data.model_dump(mode="json"),
            summary="Presentation work: audience, structure, timing and delivery.",
            confidence=0.65,
        )
