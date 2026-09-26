"""Data analysis analyzer: dataset, methods, outputs and reproducibility."""

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


class DataAnalysisData(BaseModel):
    dataset_required: bool = True
    dataset_provided: bool = False
    variables: list[str] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    statistical_methods: list[str] = Field(default_factory=list)
    visualizations: list[str] = Field(default_factory=list)
    expected_findings: bool = False
    reporting_requirements: list[str] = Field(default_factory=list)
    reproducibility_requirements: list[str] = Field(default_factory=list)


class DataAnalysisAnalyzer(AcademicSpecializedAnalyzer):
    name = "data_analysis"
    assignment_types = (AssignmentType.DATA_ANALYSIS,)

    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        text = analysis_text(context)
        methods: list[str] = []
        for label in (
            "regression",
            "correlation",
            "hypothesis test",
            "t-test",
            "anova",
            "chi-square",
            "clustering",
        ):
            if label in text:
                methods.append(label.title())
        data = DataAnalysisData(
            dataset_required=True,
            dataset_provided=bool(context.payload.get("resources")),
            variables=[],
            transformations=[
                "Handle missing values explicitly",
                "Check and document any data cleaning",
            ],
            statistical_methods=methods or ["Choose methods appropriate to the question"],
            visualizations=["Include at least one figure that supports the conclusion"],
            expected_findings=mentions(text, "findings", "conclusion", "interpret"),
            reporting_requirements=[
                "State the method and why it fits the data",
                "Report results with appropriate measures of uncertainty",
            ],
            reproducibility_requirements=[
                "Provide the code or steps needed to reproduce the analysis",
            ],
        )
        summary = "Data analysis: dataset, methods, visual outputs and reproducibility."
        return SpecializedAnalysis(
            analyzer=self.name,
            assignment_types=list(self.assignment_types),
            data=data.model_dump(mode="json"),
            summary=summary,
            confidence=0.65,
        )
