"""Mathematics analyzer: proof and calculation structure, never solutions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ai.specialized.base import (
    AcademicSpecializedAnalyzer,
    SpecializationContext,
    analysis_text,
    mentions,
    named_after,
)
from app.models.enums import AssignmentType, ScopeLevel
from app.schemas.analysis import SpecializedAnalysis


class MathematicsData(BaseModel):
    proof_required: bool = False
    calculation_required: bool = False
    definitions_involved: list[str] = Field(default_factory=list)
    theorems_involved: list[str] = Field(default_factory=list)
    theorem_dependencies: list[str] = Field(default_factory=list)
    symbolic_reasoning: bool = False
    expected_rigor: ScopeLevel = ScopeLevel.MEDIUM
    prerequisite_concepts: list[str] = Field(default_factory=list)
    verification_approaches: list[str] = Field(default_factory=list)


class MathematicsAnalyzer(AcademicSpecializedAnalyzer):
    name = "mathematics"
    assignment_types = (AssignmentType.MATHEMATICAL_PROOF, AssignmentType.PROBLEM_SET)

    def analyze(self, context: SpecializationContext) -> SpecializedAnalysis | None:
        text = analysis_text(context)
        proof = mentions(
            text,
            "prove",
            "proof",
            "theorem",
            "lemma",
            "show that",
            "deduce",
            "contradiction",
            "induction",
        )
        calculation = mentions(
            text, "calculate", "compute", "solve", "evaluate", "integral", "derivative", "limit"
        )
        data = MathematicsData(
            proof_required=proof,
            calculation_required=calculation,
            definitions_involved=named_after(text, "definition", "definitions"),
            theorems_involved=named_after(text, "theorem", "lemma", "proposition", "corollary"),
            theorem_dependencies=named_after(text, "using", "apply", "by"),
            symbolic_reasoning=proof or mentions(text, "algebra", "manipulat", "symbolic"),
            expected_rigor=ScopeLevel.HIGH if proof else ScopeLevel.MEDIUM,
            prerequisite_concepts=named_after(text, "assume", "given", "suppose"),
            verification_approaches=[
                "Check every case and boundary condition",
                "Confirm each step follows from a definition or a cited theorem",
                "Re-derive any intermediate claim independently",
            ],
        )
        summary = (
            "Proof-based mathematics: rigor and logical validity are the primary "
            "verification concerns."
            if proof
            else "Computational mathematics: correctness and reproducibility of each step."
        )
        return SpecializedAnalysis(
            analyzer=self.name,
            assignment_types=list(self.assignment_types),
            data=data.model_dump(mode="json"),
            summary=summary,
            confidence=0.7,
        )
