"""Lab analyzer: procedure, measurements, error analysis and report structure."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ai.specialized.base import (
    AcademicSpecializedAnalyzer,
    SpecializationContext,
    analysis_text,
    mentions,
)
from app.models.enums import AssignmentType
from app.schemas.analysis import SpecializedAnalysis


class LabData(BaseModel):
    experiment: str | None = None
    procedure_required: bool = False
    required_measurements: list[str] = Field(default_factory=list)
    independent_variables: list[str] = Field(default_factory=list)
    dependent_variables: list[str] = Field(default_factory=list)
    expected_calculations: list[str] = Field(default_factory=list)
    error_analysis_required: bool = False
    required_graphs_or_tables: list[str] = Field(default_factory=list)
    report_sections: list[str] = Field(default_factory=list)
    safety_requirements: list[str] = Field(default_factory=list)


class LabAnalyzer(AcademicSpecializedAnalyzer):
    name = "lab"
    assignment_types = (AssignmentType.LAB_REPORT,)

    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        text = analysis_text(context)
        data = LabData(
            experiment=None,
            procedure_required=mentions(text, "procedure", "protocol", "steps", "method"),
            required_measurements=["Repeat each measurement to check consistency"],
            independent_variables=[],
            dependent_variables=[],
            expected_calculations=["Derive the reported quantities from the raw measurements"],
            error_analysis_required=mentions(
                text, "error analysis", "uncertainty", "sources of error"
            ),
            required_graphs_or_tables=["Include a data table of raw measurements"],
            report_sections=[
                "Aim",
                "Method",
                "Results",
                "Discussion",
                "Conclusion",
            ],
            safety_requirements=(
                ["Follow the stated safety instructions"]
                if mentions(text, "safety", "hazard", "ppe")
                else []
            ),
        )
        return SpecializedAnalysis(
            analyzer=self.name,
            assignment_types=list(self.assignment_types),
            data=data.model_dump(mode="json"),
            summary="Lab work: procedure, measurements, calculations and error analysis.",
            confidence=0.65,
        )
