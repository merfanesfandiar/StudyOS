"""Programming analyzer.

Programming is one specialization among many. Its fields live entirely inside
``SpecializedAnalysis.data`` and never touch the universal model. Technology is
optional: nothing is required to be a language, framework or API.
"""

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

_KNOWN_LANGUAGES = (
    "python",
    "java",
    "javascript",
    "typescript",
    "c++",
    "c#",
    "c",
    "rust",
    "go",
    "haskell",
    "r",
    "matlab",
    "sql",
)


class ProgrammingData(BaseModel):
    language_requirements: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    apis: list[str] = Field(default_factory=list)
    architecture_requirements: list[str] = Field(default_factory=list)
    testing_requirements: list[str] = Field(default_factory=list)
    performance_constraints: list[str] = Field(default_factory=list)
    environment_requirements: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)


class ProgrammingAnalyzer(AcademicSpecializedAnalyzer):
    name = "programming"
    assignment_types = (AssignmentType.PROGRAMMING,)

    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        text = analysis_text(context)
        languages = [
            language
            for language in _KNOWN_LANGUAGES
            if re.search(rf"(?<!\w){re.escape(language)}(?!\w)", text)
        ]
        frameworks: list[str] = []
        for label in ("react", "django", "flask", "spring", "express", ".net", "vue", "fastapi"):
            if label in text:
                frameworks.append(label)
        testing = mentions(text, "test", "unit test", "test suite", "coverage")
        data = ProgrammingData(
            language_requirements=(
                [f"Use {language.title()}" for language in languages]
                if languages
                else ["No language is specified; any suitable language is acceptable"]
            ),
            frameworks=frameworks,
            apis=[],
            architecture_requirements=(
                ["Follow the architecture or interfaces described in the brief"]
                if mentions(text, "architecture", "design pattern", "interface", "module")
                else []
            ),
            testing_requirements=(
                ["Provide tests that demonstrate the required behaviour"]
                if testing
                else ["Decide with the instructor whether tests are expected"]
            ),
            performance_constraints=(
                ["Respect any stated runtime or memory limits"]
                if mentions(text, "performance", "runtime", "memory", "complexity", "seconds")
                else []
            ),
            environment_requirements=(
                ["Document how to build and run the project"]
                if mentions(text, "build", "run", "environment", "dependency")
                else []
            ),
            expected_artifacts=["Source code", "Build/run instructions"],
        )
        return SpecializedAnalysis(
            analyzer=self.name,
            assignment_types=list(self.assignment_types),
            data=data.model_dump(mode="json"),
            summary="Programming work: implementation, tests and documentation.",
            confidence=0.7,
        )
