"""Deterministic golden dataset of heterogeneous academic assignments.

Twelve fixtures spanning proof, problem set, programming, research, essay, lab,
data analysis, presentation, reading, mixed research+presentation, mixed
programming+report and a group project. They exist to evaluate *structural*
correctness (types, domains, requirement/deliverable/ambiguity/dependency
detection), never exact wording.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import AcademicDomain, AssignmentType


@dataclass(frozen=True, slots=True)
class GoldenFixture:
    name: str
    payload: dict[str, Any]
    expected_types: tuple[str, ...]
    expected_domains: tuple[str, ...]
    min_requirements: int = 0
    expected_deliverable_keywords: tuple[str, ...] = ()
    expect_ambiguities: bool = False
    expect_contradictions: bool = False
    expected_dependency_kinds: tuple[str, ...] = ("WORK_AREA",)
    expect_rubric: bool = False
    #: Keywords that should appear somewhere in the normalized requirements.
    expected_requirement_keywords: tuple[str, ...] = field(default_factory=tuple)


def _assignment(
    title: str, description: str, *, deadline: str | None = "2026-12-01T17:00:00Z"
) -> dict[str, Any]:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": title,
        "description": description,
        "deadline": deadline,
        "status": "READY_FOR_ANALYSIS",
        "course_name": "Course",
        "course_code": "CRS101",
    }


def golden_fixtures() -> list[GoldenFixture]:
    fixtures: list[GoldenFixture] = []

    fixtures.append(
        GoldenFixture(
            name="mathematics_proof",
            payload=_payload(
                _assignment(
                    "Real Analysis Proof Set 4",
                    "Prove that if a sequence of continuous functions converges uniformly then the "
                    "limit is continuous. Use the definition of uniform convergence and state "
                    "which theorems you apply. Provide rigorous proofs for the three problems.",
                ),
                requirements=[
                    ("Prove Theorem 4.2 using the definition of uniform convergence", "HIGH"),
                    ("State every theorem used in the proof", "MEDIUM"),
                    ("Provide a rigorous written solution", "HIGH"),
                ],
                criteria=[("Proof correctness", "60"), ("Clarity of exposition", "40")],
                deliverables=[("Written proof solutions", "DOCUMENT")],
            ),
            expected_types=(AssignmentType.MATHEMATICAL_PROOF.value,),
            expected_domains=(AcademicDomain.MATHEMATICS.value,),
            min_requirements=3,
            expected_deliverable_keywords=("proof",),
            expected_requirement_keywords=("prove", "theorem"),
            expect_rubric=True,
        )
    )

    fixtures.append(
        GoldenFixture(
            name="mathematics_problem_set",
            payload=_payload(
                _assignment(
                    "Linear Algebra Problem Set 6",
                    "Solve the following problems on eigenvalues and diagonalization. Compute the "
                    "determinant of each matrix and show your working. Problems 1-8 are required.",
                ),
                requirements=[
                    ("Solve problems 1-8 on eigenvalues", "HIGH"),
                    ("Compute determinants showing all steps", "MEDIUM"),
                ],
                constraints=[("Submission", "Hand in a single PDF", "1 file", "FORMAT", "WARNING")],
            ),
            expected_types=(AssignmentType.PROBLEM_SET.value,),
            expected_domains=(AcademicDomain.MATHEMATICS.value,),
            min_requirements=2,
            expected_requirement_keywords=("solve",),
        )
    )

    fixtures.append(
        GoldenFixture(
            name="programming_assignment",
            payload=_payload(
                _assignment(
                    "Implement a Shortest Path Library",
                    "Implement Dijkstra and Bellman-Ford in Python. The project must include unit "
                    "tests, a build script, and a written report comparing runtime behaviour. "
                    "The algorithm must run within 2 seconds on the provided graphs.",
                ),
                requirements=[
                    ("Implement Dijkstra in Python", "CRITICAL"),
                    ("Implement Bellman-Ford", "HIGH"),
                    ("Provide unit tests", "HIGH"),
                    ("Write a comparison report", "MEDIUM"),
                ],
                criteria=[("Correctness", "50"), ("Tests", "30"), ("Report", "20")],
                deliverables=[("Source code", "SOURCE_CODE"), ("Written report", "DOCUMENT")],
                resources=[("starter-graphs.zip", "ARCHIVE")],
            ),
            expected_types=(AssignmentType.PROGRAMMING.value,),
            expected_domains=(AcademicDomain.COMPUTER_SCIENCE.value,),
            min_requirements=4,
            expected_deliverable_keywords=("code", "report"),
            expected_requirement_keywords=("implement", "test"),
            expected_dependency_kinds=("WORK_AREA", "DELIVERABLE"),
            expect_rubric=True,
        )
    )

    fixtures.append(
        GoldenFixture(
            name="research_paper",
            payload=_payload(
                _assignment(
                    "Research Paper: Fairness in Machine Learning",
                    "Write a research paper on fairness in machine learning. State a research "
                    "question, review the literature, describe your methodology, and cite at least "
                    "8 peer-reviewed sources in APA style. Conclude with recommendations.",
                ),
                requirements=[
                    ("State a clear research question", "HIGH"),
                    ("Review relevant literature", "HIGH"),
                    ("Cite at least 8 peer-reviewed sources in APA style", "CRITICAL"),
                    ("Present a methodology", "MEDIUM"),
                ],
                criteria=[("Argument", "40"), ("Use of sources", "35"), ("Writing", "25")],
                deliverables=[("Research paper", "DOCUMENT")],
            ),
            expected_types=(AssignmentType.RESEARCH.value,),
            expected_domains=(AcademicDomain.COMPUTER_SCIENCE.value,),
            min_requirements=4,
            expected_deliverable_keywords=("paper",),
            expected_requirement_keywords=("cite", "literature"),
            expect_rubric=True,
        )
    )

    fixtures.append(
        GoldenFixture(
            name="essay",
            payload=_payload(
                _assignment(
                    "Essay: The Ethics of Automation",
                    "Write an essay arguing a clear thesis about the ethics of automation. Use "
                    "appropriate academic sources, include an introduction and conclusion, and "
                    "stay within 1500 words. Provide a detailed analysis of two positions.",
                ),
                requirements=[
                    ("Develop a clear thesis", "HIGH"),
                    ("Support the argument with academic sources", "HIGH"),
                    ("Stay within 1500 words", "MEDIUM"),
                ],
                deliverables=[("Essay", "DOCUMENT")],
            ),
            expected_types=(AssignmentType.ESSAY.value,),
            expected_domains=(
                AcademicDomain.HUMANITIES.value,
                AcademicDomain.SOCIAL_SCIENCES.value,
            ),
            min_requirements=3,
            expected_deliverable_keywords=("essay",),
            expect_ambiguities=True,
            expected_requirement_keywords=("thesis",),
        )
    )

    fixtures.append(
        GoldenFixture(
            name="lab_report",
            payload=_payload(
                _assignment(
                    "Lab Report: Titration of an Unknown Acid",
                    "Follow the titration procedure in the lab manual, record all measurements, "
                    "calculate the molarity of the unknown acid, and discuss sources of error. "
                    "Include a data table and the relevant graphs. Follow the safety instructions.",
                ),
                requirements=[
                    ("Follow the titration procedure", "HIGH"),
                    ("Calculate the molarity of the unknown acid", "CRITICAL"),
                    ("Discuss sources of error", "HIGH"),
                    ("Include a data table and graphs", "MEDIUM"),
                ],
                deliverables=[("Lab report", "DOCUMENT")],
                resources=[("lab-manual-titration.pdf", "PDF")],
            ),
            expected_types=(AssignmentType.LAB_REPORT.value,),
            expected_domains=(AcademicDomain.CHEMISTRY.value,),
            min_requirements=4,
            expected_deliverable_keywords=("lab",),
            expected_requirement_keywords=("procedure", "molarity", "error"),
        )
    )

    fixtures.append(
        GoldenFixture(
            name="data_analysis",
            payload=_payload(
                _assignment(
                    "Data Analysis: Student Performance",
                    "Analyze the provided dataset of student performance. Clean the data, run a "
                    "regression, create at least three visualizations, and report your findings. "
                    "Provide the code to reproduce the analysis.",
                ),
                requirements=[
                    ("Clean the dataset", "HIGH"),
                    ("Run a regression analysis", "HIGH"),
                    ("Create visualizations", "MEDIUM"),
                    ("Provide reproducible analysis code", "MEDIUM"),
                ],
                deliverables=[
                    ("Analysis report", "DOCUMENT"),
                    ("Analysis notebook", "SOURCE_CODE"),
                ],
                resources=[("student-performance.csv", "CSV")],
            ),
            expected_types=(AssignmentType.DATA_ANALYSIS.value,),
            expected_domains=(AcademicDomain.SOCIAL_SCIENCES.value, AcademicDomain.ECONOMICS.value),
            min_requirements=4,
            expected_deliverable_keywords=("analysis",),
            expected_requirement_keywords=("data", "regression"),
        )
    )

    fixtures.append(
        GoldenFixture(
            name="presentation",
            payload=_payload(
                _assignment(
                    "Presentation: Renewable Energy Policy",
                    "Prepare a 10 minute presentation for your classmates on renewable energy "
                    "policy. Cover the current state, the main arguments, and a recommendation. "
                    "Use no more than 12 slides and be ready for questions.",
                ),
                requirements=[
                    ("Cover the current state of renewable energy policy", "HIGH"),
                    ("Present the main arguments", "HIGH"),
                    ("Recommend a policy direction", "MEDIUM"),
                ],
                deliverables=[("Presentation slides", "PRESENTATION")],
            ),
            expected_types=(AssignmentType.PRESENTATION.value,),
            expected_domains=(AcademicDomain.ECONOMICS.value, AcademicDomain.SOCIAL_SCIENCES.value),
            min_requirements=3,
            expected_deliverable_keywords=("presentation", "slide"),
            expected_requirement_keywords=("present", "recommend"),
        )
    )

    fixtures.append(
        GoldenFixture(
            name="reading_assignment",
            payload=_payload(
                _assignment(
                    "Reading Response: Chapters 3-5",
                    "Read chapters 3 to 5 of the history textbook and write a reading response "
                    "summarizing the key arguments. Annotate the text and bring three "
                    "discussion questions.",
                ),
                requirements=[
                    ("Read chapters 3-5", "HIGH"),
                    ("Write a reading response", "HIGH"),
                    ("Prepare three discussion questions", "MEDIUM"),
                ],
                deliverables=[("Reading response", "DOCUMENT")],
                resources=[("chapter-3.pdf", "PDF")],
            ),
            expected_types=(AssignmentType.READING.value,),
            expected_domains=(
                AcademicDomain.HUMANITIES.value,
                AcademicDomain.SOCIAL_SCIENCES.value,
            ),
            min_requirements=3,
            expected_requirement_keywords=("read", "response"),
        )
    )

    fixtures.append(
        GoldenFixture(
            name="research_and_presentation",
            payload=_payload(
                _assignment(
                    "Research Report and Presentation",
                    "Conduct research on urban food security and write a research paper with a "
                    "literature review and cited sources. Then present your findings to the class "
                    "in a 15 minute presentation with slides.",
                ),
                requirements=[
                    ("Write a research paper on urban food security", "HIGH"),
                    ("Review the literature", "HIGH"),
                    ("Present the findings in 15 minutes", "MEDIUM"),
                ],
                criteria=[("Paper", "60"), ("Presentation", "40")],
                deliverables=[
                    ("Research paper", "DOCUMENT"),
                    ("Presentation slides", "PRESENTATION"),
                ],
            ),
            expected_types=(AssignmentType.RESEARCH.value, AssignmentType.PRESENTATION.value),
            expected_domains=(
                AcademicDomain.SOCIAL_SCIENCES.value,
                AcademicDomain.HUMANITIES.value,
            ),
            min_requirements=3,
            expected_deliverable_keywords=("paper", "presentation"),
            expected_dependency_kinds=("WORK_AREA", "DELIVERABLE"),
            expect_rubric=True,
        )
    )

    fixtures.append(
        GoldenFixture(
            name="programming_and_report",
            payload=_payload(
                _assignment(
                    "Software Project with Technical Report",
                    "Design and implement a small web API in Java and write a technical report "
                    "documenting the architecture, testing approach and results. Include the "
                    "source code repository.",
                ),
                requirements=[
                    ("Implement a web API in Java", "HIGH"),
                    ("Document the architecture in a report", "HIGH"),
                    ("Describe the testing approach", "MEDIUM"),
                ],
                deliverables=[("Source code", "SOURCE_CODE"), ("Technical report", "DOCUMENT")],
            ),
            expected_types=(AssignmentType.PROGRAMMING.value, AssignmentType.REPORT.value),
            expected_domains=(AcademicDomain.COMPUTER_SCIENCE.value,),
            min_requirements=3,
            expected_deliverable_keywords=("code", "report"),
            expected_dependency_kinds=("WORK_AREA", "DELIVERABLE"),
        )
    )

    fixtures.append(
        GoldenFixture(
            name="group_project",
            payload=_payload(
                _assignment(
                    "Group Project: Sustainable Business Plan",
                    "Work in a team of four to develop a sustainable business plan. "
                    "Each member contributes a section and the team submits a combined report. "
                    "Present the plan to the class at the end.",
                ),
                requirements=[
                    ("Develop a sustainable business plan as a team", "HIGH"),
                    ("Contribute an individual section", "MEDIUM"),
                    ("Present the plan together", "MEDIUM"),
                ],
                deliverables=[
                    ("Combined business plan", "DOCUMENT"),
                    ("Presentation", "PRESENTATION"),
                ],
            ),
            expected_types=(AssignmentType.GROUP_PROJECT.value,),
            expected_domains=(AcademicDomain.BUSINESS.value, AcademicDomain.ECONOMICS.value),
            min_requirements=3,
            expected_deliverable_keywords=("business", "presentation"),
        )
    )

    return fixtures


def _payload(
    assignment: dict[str, Any],
    *,
    requirements: list[tuple[str, str]] | None = None,
    constraints: list[tuple[str, str, str, str, str]] | None = None,
    criteria: list[tuple[str, str]] | None = None,
    deliverables: list[tuple[str, str]] | None = None,
    resources: list[tuple[str, str]] | None = None,
    document_texts: list[str] | None = None,
    user_notes: str | None = None,
) -> dict[str, Any]:
    """Build an analyzer input payload from terse fixture data."""
    requirements = requirements or []
    constraints = constraints or []
    criteria = criteria or []
    deliverables = deliverables or []
    resources = resources or []
    document_texts = document_texts or []
    return {
        "assignment": assignment,
        "course_name": assignment.get("course_name"),
        "requirements": [
            {
                "id": f"req-{index}",
                "code": f"REQ-{index:03d}",
                "title": title,
                "description": None,
                "priority": priority,
                "type": "OTHER",
                "is_required": True,
            }
            for index, (title, priority) in enumerate(requirements, start=1)
        ],
        "constraints": [
            {
                "id": f"con-{index}",
                "title": title,
                "description": description,
                "value": value,
                "type": constraint_type,
                "severity": severity,
            }
            for index, (title, description, value, constraint_type, severity) in enumerate(
                constraints, start=1
            )
        ],
        "criteria": [
            {
                "id": f"crit-{index}",
                "title": title,
                "description": None,
                "weight": weight,
            }
            for index, (title, weight) in enumerate(criteria, start=1)
        ],
        "deliverables": [
            {
                "id": f"del-{index}",
                "title": title,
                "description": None,
                "type": deliverable_type,
                "is_required": True,
            }
            for index, (title, deliverable_type) in enumerate(deliverables, start=1)
        ],
        "resources": [
            {
                "id": f"doc-{index}",
                "filename": filename,
                "resource_type": resource_type,
                "mime_type": "application/octet-stream",
            }
            for index, (filename, resource_type) in enumerate(resources, start=1)
        ],
        "document_texts": [
            {"document_id": f"doc-{index}", "filename": "resource", "text": text}
            for index, text in enumerate(document_texts, start=1)
        ],
        "assigned_types": [],
        "assigned_domains": [],
        "user_notes": user_notes,
    }
