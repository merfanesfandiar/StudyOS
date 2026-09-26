"""Recorded model transcripts for the golden dataset.

These exist so the evaluation is not self-referential. The runner used to ask
``MockLLMProvider`` for an answer, and ``MockLLMProvider`` runs the heuristic
engine, which meant the thing being measured and the thing doing the measuring
were the same code. Any metric tuned against that engine scored 1.0 by
construction, and no amount of rewriting the metrics could fix it: the words
being graded were the engine's own.

What is stored here is a *model-style* answer per fixture, written by hand
against the fixture's brief. The writer did not run the heuristics, so these
transcripts contain things the heuristic engine never emits:

* prose in its own words rather than assembled phrases,
* confidence values that do not follow the engine's scoring curve,
* inferences the brief never states, marked as inferences so the grounding
  check has to treat them as honest rather than as hallucinations.

Every recorded answer is internally consistent and grounded, because the golden
gate asserts a clean pass on all twelve. Detecting bad output is covered by the
mutation suite in :mod:`app.ai.evaluation.metrics`, which corrupts a good
transcript and asserts the checks notice.

The evaluation therefore measures the *pipeline* -- parsing, schema validation,
semantic validation, coverage, grounding -- against transcripts whose provenance
is independent of the code under test. It still says nothing about how a real
model would answer; that needs credentials and is deliberately not in CI.
"""

from __future__ import annotations

from typing import Any

#: Fixtures whose brief leaves a genuine gap, so the recorded answer has to mark
#: something as an inference instead of presenting it as stated. A recorded set
#: where every answer is certain would never exercise the honesty check.
#: ``tests/test_evaluation_independence.py`` asserts each of these is marked
#: inferred rather than dropped or dressed up as explicit.
INFERRED_TRANSCRIPTS: dict[str, str] = {
    "essay": "interview requirement the brief never states",
    "mathematics_problem_set": "solutions document when the brief lists no deliverable",
    "presentation": "speaker notes when the brief lists slides only",
}


# --------------------------------------------------------------------------
# Small builders. These shape the hand-written content; they do not derive it.
# --------------------------------------------------------------------------


def _evidence(
    source_type: str,
    supports: str,
    *,
    source_id: str | None = None,
    location: str | None = None,
    confidence: float = 0.85,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "location": location,
        "excerpt_reference": None,
        "supports": supports,
        "confidence": confidence,
    }


def _req(
    key: str,
    title: str,
    *,
    source: str = "EXPLICIT",
    confidence: float = 0.86,
    evidence: list[dict[str, Any]] | None = None,
    description: str | None = None,
    source_reference: str | None = None,
) -> dict[str, Any]:
    # An explicit requirement has to point at the brief row it came from, so the
    # default reference is the key itself. Inferences carry no reference.
    if source == "EXPLICIT" and source_reference is None:
        source_reference = key
    return {
        "key": key,
        "title": title,
        "description": description,
        "source": source,
        "source_reference": source_reference,
        "confidence": confidence,
        "evidence": evidence if evidence is not None else [],
    }


def _desc_evidence(excerpt: str, *, confidence: float = 0.8) -> dict[str, Any]:
    return _evidence("DESCRIPTION", excerpt, location="description", confidence=confidence)


def _work_area(
    key: str,
    title: str,
    description: str,
    *,
    related: list[str] | None = None,
    origin: str = "EXPLICIT",
    confidence: float = 0.8,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "description": description,
        "related_requirements": related or [],
        "origin": origin,
        "confidence": confidence,
    }


def _question(
    code: str, text: str, *, priority: str = "IMPORTANT", rationale: str = ""
) -> dict[str, Any]:
    return {
        "code": code,
        "question": text,
        "priority": priority,
        "rationale": rationale,
        "confidence": 0.8,
    }


def _criterion(title: str, *, related: list[str] | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "related_requirements": related or [],
        "implied": False,
        "confidence": 0.8,
    }


def _ambiguity(
    key: str, description: str, *, evidence: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "key": key,
        "description": description,
        "severity": "WARNING",
        "evidence": evidence or [],
        "confidence": 0.66,
    }


def _deliverable(
    key: str,
    title: str,
    *,
    related: list[str] | None = None,
    fmt: str = "PDF",
    uncertainty: str = "EXPLICIT",
    evidence: list[dict[str, Any]] | None = None,
    depends_on: list[str] | None = None,
    confidence: float = 0.82,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "required": True,
        "format": fmt,
        "related_requirements": related or [],
        "depends_on": depends_on or [],
        "uncertainty": uncertainty,
        "evidence": evidence or [],
        "confidence": confidence,
    }


def _edge(predecessor: str, successor: str, kind: str, reason: str) -> dict[str, Any]:
    return {
        "predecessor": predecessor,
        "successor": successor,
        "kind": kind,
        "reason": reason,
        "confidence": 0.78,
    }


def _base(
    *,
    summary: str,
    types: list[tuple[str, float]],
    domains: list[tuple[str, float]],
    confidence: float,
) -> dict[str, Any]:
    return {
        "assignment_types": [{"type": name, "confidence": value} for name, value in types],
        "academic_domains": [{"domain": name, "confidence": value} for name, value in domains],
        "summary": summary,
        "objectives": [],
        "normalized_requirements": [],
        "ambiguities": [],
        "contradictions": [],
        "missing_information": [],
        "assumptions": [],
        "clarification_questions": [],
        "deliverables": [],
        "evaluation": {"rubric_available": False, "criteria": []},
        "scope": {"overall": "MEDIUM"},
        "work_areas": [],
        "resources": {"resources": [], "notes": []},
        "dependencies": [],
        "verification": {"items": [], "notes": []},
        "risks": [],
        "confidence": confidence,
    }


def _transcripts() -> dict[str, dict[str, Any]]:
    """Every recorded transcript, written against the briefs in the dataset.

    Requirement keys, criterion titles and deliverable ids referenced below are
    the ones those fixtures actually contain, so the transcripts are internally
    consistent and still not machine-generated.
    """
    items: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ proof
    proof = _base(
        summary=(
            "Three proofs about uniform convergence of sequences of continuous "
            "functions. Each has to be built from the definition rather than cited, "
            "and every borrowed theorem has to be named."
        ),
        types=[("MATHEMATICAL_PROOF", 0.88)],
        domains=[("MATHEMATICS", 0.93)],
        confidence=0.81,
    )
    proof["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Prove Theorem 4.2 using the definition of uniform convergence.",
            confidence=0.9,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Use the definition of uniform convergence.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.9,
                )
            ],
        ),
        _req(
            "REQ-002",
            "State every theorem used in the proof.",
            confidence=0.87,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "State every theorem used in the proof.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.87,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Provide a rigorous written solution.",
            confidence=0.85,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Provide a rigorous written solution.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.85,
                )
            ],
        ),
    ]
    proof["deliverables"] = [
        {
            "key": "del-1",
            "title": "A written proof for each of the three problems.",
            "required": True,
            "format": "PDF",
            "related_requirements": ["REQ-001", "REQ-002", "REQ-003"],
            "uncertainty": "EXPLICIT",
            "evidence": [
                _evidence(
                    "DELIVERABLE",
                    "Written proof solutions is the listed deliverable.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.85,
                )
            ],
            "confidence": 0.85,
        }
    ]
    proof["evaluation"]["rubric_available"] = True
    proof["evaluation"]["criteria"] = [
        _criterion("Proof correctness", related=["REQ-001"]),
        _criterion("Clarity of exposition", related=["REQ-003"]),
    ]
    proof["work_areas"] = [
        _work_area(
            "wa-1",
            "Work from the definition",
            "Rewrite the target statement in epsilon-delta form before using any theorem.",
            related=["REQ-001", "REQ-002"],
            confidence=0.82,
        )
    ]
    proof["ambiguities"] = [
        _ambiguity(
            "amb-1",
            "The brief says rigorous but never says whether theorems already proved in "
            "the course may be cited by name.",
            evidence=[_desc_evidence("Provide rigorous proofs for the three problems.")],
        )
    ]
    proof["clarification_questions"] = [
        _question(
            "CL-001",
            "May theorems already proved in the course be cited by name, or must each "
            "one be re-proven?",
            rationale="The answer changes how much work each proof is.",
        )
    ]
    proof["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "The epsilon-delta rewrite has to come first."),
        _edge("wa-1", "del-1", "DELIVERABLE", "The proof is assembled from that rewrite."),
    ]
    items["mathematics_proof"] = proof

    # ------------------------------------------------------------ problem set
    problems = _base(
        summary=(
            "A problem set on eigenvalues and diagonalization. Answers are worked, "
            "not just stated, and a matrix that is not diagonalizable has to be "
            "identified as such."
        ),
        types=[("PROBLEM_SET", 0.84)],
        domains=[("MATHEMATICS", 0.9)],
        confidence=0.78,
    )
    problems["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Solve the eigenvalue problems for the matrices given.",
            confidence=0.86,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Solve the following problems on eigenvalues.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.86,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Compute the determinants, showing every step of the working.",
            confidence=0.85,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Compute determinants showing all steps.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.85,
                )
            ],
        ),
    ]
    problems["work_areas"] = [
        _work_area(
            "wa-1",
            "Characteristic polynomials",
            "Compute characteristic polynomials, then read the eigenvalues off them.",
            related=["REQ-001"],
            confidence=0.8,
        ),
        _work_area(
            "wa-2",
            "Diagonalizability tests",
            "Compare geometric against algebraic multiplicity to decide each case.",
            related=["REQ-002"],
            confidence=0.78,
        ),
    ]
    problems["deliverables"] = [
        # The brief lists no deliverable at all, so the solutions document is an
        # inference. It is marked as one and cites nothing, so the grounding check
        # treats it as honest rather than as an invented requirement.
        _deliverable(
            "del-1",
            "Worked solutions for every problem, with the diagonalizability verdicts stated.",
            related=["REQ-001", "REQ-002"],
            uncertainty="AI_INFERENCE",
            evidence=[],
        )
    ]
    problems["dependencies"] = [
        _edge(
            "REQ-001", "wa-1", "WORK_AREA", "Characteristic polynomials come before anything else."
        ),
        _edge("wa-1", "wa-2", "WORK_AREA", "Eigenvalues are needed to test diagonalizability."),
        _edge("wa-2", "del-1", "DELIVERABLE", "The verdicts go into the written solutions."),
    ]
    items["mathematics_problem_set"] = problems

    # ------------------------------------------------------------- programming
    programming = _base(
        summary=(
            "A Python project implementing two shortest-path algorithms. Correct "
            "output on the supplied graphs matters more than speed, and the tests "
            "have to cover the disconnected case."
        ),
        types=[("PROGRAMMING", 0.91)],
        domains=[("COMPUTER_SCIENCE", 0.92)],
        confidence=0.83,
    )
    programming["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Implement Dijkstra's algorithm for graphs with non-negative weights.",
            confidence=0.92,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Implement Dijkstra in Python.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.92,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Implement Bellman-Ford so that graphs with negative edges are handled.",
            confidence=0.92,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "and Bellman-Ford.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.92,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Provide unit tests covering both implementations.",
            confidence=0.88,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Include unit tests in the project.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.88,
                )
            ],
        ),
        _req(
            "REQ-004",
            "Write a comparison report on the two algorithms.",
            confidence=0.8,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Include a written report comparing them.",
                    source_id="REQ-004",
                    location="requirements.REQ-004",
                    confidence=0.8,
                )
            ],
        ),
    ]
    programming["work_areas"] = [
        _work_area(
            "wa-1",
            "Graph representation",
            "Pick an adjacency structure and a distance table that can express unreachable nodes.",
            related=["REQ-001", "REQ-002", "REQ-003"],
            origin="AI_INFERENCE",
            confidence=0.72,
        ),
        _work_area(
            "wa-2",
            "Test suite",
            "Cover a disconnected graph, a single-node graph and a negative-weight cycle.",
            related=["REQ-004"],
            origin="AI_INFERENCE",
            confidence=0.7,
        ),
    ]
    programming["evaluation"]["rubric_available"] = True
    programming["evaluation"]["criteria"] = [_criterion("Correctness on the provided graphs")]
    programming["deliverables"] = [
        _deliverable(
            "del-code",
            "Source code for both algorithms, runnable as submitted.",
            related=["REQ-001", "REQ-002"],
            fmt="ZIP",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the source code as an archive.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.84,
                )
            ],
        ),
        _deliverable(
            "del-report",
            "A short report stating how each algorithm was tested.",
            related=["REQ-004"],
            fmt="PDF",
            depends_on=["del-code"],
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Include a report on testing.",
                    source_id="del-2",
                    location="deliverables.del-2",
                    confidence=0.78,
                )
            ],
        ),
    ]
    programming["dependencies"] = [
        _edge(
            "REQ-001",
            "wa-1",
            "WORK_AREA",
            "The representation has to exist before either algorithm runs.",
        ),
        _edge(
            "wa-1",
            "wa-2",
            "WORK_AREA",
            "Tests exercise the implementation through the representation.",
        ),
        _edge("wa-2", "del-code", "DELIVERABLE", "The test suite ships with the code."),
        _edge(
            "del-code", "del-report", "DELIVERABLE", "The report describes how the code was tested."
        ),
    ]
    items["programming_assignment"] = programming

    # ---------------------------------------------------------- research paper
    research = _base(
        summary=(
            "A research paper on fairness in machine learning. The literature has "
            "to be surveyed properly and every claim needs a citation, including "
            "the empirical ones."
        ),
        types=[("RESEARCH", 0.89)],
        domains=[("COMPUTER_SCIENCE", 0.79)],
        confidence=0.77,
    )
    research["normalized_requirements"] = [
        _req(
            "REQ-001",
            "State a clear research question about fairness in machine learning.",
            confidence=0.87,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "State a clear research question.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.87,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Review the relevant literature on the question.",
            confidence=0.86,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Review relevant literature.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.86,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Cite at least 8 peer-reviewed sources in APA style.",
            confidence=0.89,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Cite at least 8 peer-reviewed sources in APA style.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.89,
                )
            ],
        ),
        _req(
            "REQ-004",
            "Present a methodology for the study.",
            confidence=0.84,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Present a methodology.",
                    source_id="REQ-004",
                    location="requirements.REQ-004",
                    confidence=0.84,
                )
            ],
        ),
    ]
    research["work_areas"] = [
        _work_area(
            "wa-1",
            "Literature survey",
            "Group the literature by which fairness definition each author assumes.",
            related=["REQ-001"],
            confidence=0.8,
        ),
        _work_area(
            "wa-2",
            "Metric comparison",
            "Run both metrics on one dataset and report the gap between them.",
            related=["REQ-002", "REQ-004"],
            confidence=0.78,
        ),
    ]
    research["ambiguities"] = [
        _ambiguity(
            "amb-1",
            "Fairness is left undefined, and the field has at least six incompatible "
            "definitions of the word.",
            evidence=[_desc_evidence("fairness in machine learning", confidence=0.7)],
        )
    ]
    research["clarification_questions"] = [
        _question(
            "CL-001",
            "Which fairness definition should the paper adopt, or is surveying several the point?",
            rationale="The choice determines the entire literature section.",
        )
    ]
    research["evaluation"]["rubric_available"] = True
    research["evaluation"]["criteria"] = [
        _criterion("Methodology is stated and reproducible", related=["REQ-004"]),
        _criterion("Source quality matches the citation requirement", related=["REQ-003"]),
    ]
    research["deliverables"] = [
        _deliverable(
            "del-paper",
            "A written research paper with citations and measured figures.",
            related=["REQ-001", "REQ-002", "REQ-003", "REQ-004"],
            fmt="PDF",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the paper as a PDF.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.85,
                )
            ],
        ),
    ]
    research["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "The survey is read before anything is written."),
        _edge("wa-1", "wa-2", "WORK_AREA", "The comparison needs the surveyed definitions."),
        _edge("wa-2", "del-paper", "DELIVERABLE", "Both feed into the paper."),
    ]
    items["research_paper"] = research

    # -------------------------------------------------------------------- essay
    essay = _base(
        summary=(
            "An argumentative essay on the ethics of automated grading. A thesis "
            "has to be argued rather than asserted, and the counter-argument has to "
            "be treated fairly."
        ),
        types=[("ESSAY", 0.9)],
        domains=[("HUMANITIES", 0.72), ("SOCIAL_SCIENCES", 0.68)],
        confidence=0.7,
    )
    essay["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Develop a clear thesis about the ethics of automated grading.",
            confidence=0.88,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Develop a clear thesis.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.88,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Support the argument with academic sources.",
            confidence=0.84,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Support the argument with academic sources.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.84,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Stay within 1500 words.",
            confidence=0.83,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Stay within 1500 words.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.83,
                )
            ],
        ),
        # An inference the brief does not state. It is marked as inferred and it
        # still cites a real source row, so honest inference is not penalised.
        _req(
            "REQ-004",
            "Include at least one primary interview the student conducted themselves.",
            source="AI_INFERENCE",
            confidence=0.55,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "The reading list mentions interview-based coursework.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.55,
                )
            ],
        ),
    ]
    essay["work_areas"] = [
        _work_area(
            "wa-1",
            "Thesis and outline",
            "Fix the thesis in one sentence, then order sections so the argument builds.",
            related=["REQ-001"],
            confidence=0.8,
        ),
        _work_area(
            "wa-2",
            "Counter-argument section",
            "State the objection in its strongest form before rebutting it.",
            related=["REQ-002"],
            confidence=0.78,
        ),
    ]
    essay["deliverables"] = [
        _deliverable(
            "del-essay",
            "The finished essay, inside the word limit.",
            related=["REQ-001", "REQ-002", "REQ-003"],
            fmt="DOCX",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the essay itself.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.83,
                )
            ],
        ),
    ]
    essay["ambiguities"] = [
        _ambiguity(
            "AMB-001",
            "Whether the word limit counts references is not stated. "
            "Question for the student: do in-text citations and the reference list "
            "count towards the 1500 words?",
            evidence=[
                _desc_evidence(
                    "The essay brief gives a word limit but says nothing about references."
                )
            ],
        )
    ]
    essay["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "The thesis comes before the outline."),
        _edge("wa-1", "wa-2", "WORK_AREA", "The counter-argument section is written last."),
        _edge("wa-2", "del-essay", "DELIVERABLE", "The sections are assembled into the essay."),
    ]
    items["essay"] = essay

    # -------------------------------------------------------------- lab report
    lab = _base(
        summary=(
            "A titration lab report following the manual's procedure. Every reading "
            "goes in a table, and the discussion has to account for whatever error "
            "was actually observed."
        ),
        types=[("LAB_REPORT", 0.92)],
        domains=[("CHEMISTRY", 0.94)],
        confidence=0.84,
    )
    lab["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Follow the titration procedure in the lab manual without deviating from it.",
            confidence=0.9,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Follow the titration procedure in the lab manual.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.9,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Calculate the molarity of the unknown acid.",
            confidence=0.89,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Calculate the molarity of the unknown acid.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.89,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Discuss sources of error in the determination.",
            confidence=0.86,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Discuss sources of error.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.86,
                )
            ],
        ),
        _req(
            "REQ-004",
            "Include a data table and graphs in the report.",
            confidence=0.85,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Include a data table and graphs.",
                    source_id="REQ-004",
                    location="requirements.REQ-004",
                    confidence=0.85,
                )
            ],
        ),
    ]
    lab["work_areas"] = [
        _work_area(
            "wa-1",
            "Measurement and recording",
            "Run the titrations and log each endpoint as it is read.",
            related=["REQ-001", "REQ-002"],
            confidence=0.85,
        ),
        _work_area(
            "wa-2",
            "Error analysis",
            "Compare observed against expected titre and attribute the gap.",
            related=["REQ-003", "REQ-004"],
            confidence=0.8,
        ),
    ]
    lab["evaluation"]["rubric_available"] = True
    lab["evaluation"]["criteria"] = [_criterion("Accuracy of recorded data", related=["REQ-002"])]
    lab["deliverables"] = [
        _deliverable(
            "del-lab",
            "The lab report, with the raw data sheet attached.",
            related=["REQ-001", "REQ-002", "REQ-003", "REQ-004"],
            fmt="PDF",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the report and the raw data sheet.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.85,
                )
            ],
        ),
    ]
    lab["dependencies"] = [
        _edge(
            "REQ-001",
            "wa-1",
            "WORK_AREA",
            "The readings cannot be recorded before the titrations run.",
        ),
        _edge("wa-1", "wa-2", "WORK_AREA", "Error analysis needs the recorded readings."),
        _edge("wa-2", "del-lab", "DELIVERABLE", "The analysis is written into the report."),
    ]
    items["lab_report"] = lab

    # ----------------------------------------------------------- data analysis
    data = _base(
        summary=(
            "An analysis of a student performance dataset. The cleaning decisions "
            "have to be documented because they change the results, and the "
            "correlation has to be reported without implying causation."
        ),
        types=[("DATA_ANALYSIS", 0.87)],
        domains=[("SOCIAL_SCIENCES", 0.71), ("ECONOMICS", 0.64)],
        confidence=0.76,
    )
    data["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Clean the dataset and record every cleaning decision that was made.",
            confidence=0.89,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Clean the data first.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.89,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Run a regression analysis on the cleaned data.",
            confidence=0.88,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Run a regression analysis.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.88,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Create visualizations of the results.",
            confidence=0.85,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Create visualizations.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.85,
                )
            ],
        ),
        _req(
            "REQ-004",
            "Provide reproducible analysis code.",
            confidence=0.83,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Provide reproducible analysis code.",
                    source_id="REQ-004",
                    location="requirements.REQ-004",
                    confidence=0.83,
                )
            ],
        ),
    ]
    data["work_areas"] = [
        _work_area(
            "wa-1",
            "Cleaning log",
            "Keep a table of each row dropped or imputed, and why.",
            related=["REQ-001"],
            confidence=0.82,
        ),
        _work_area(
            "wa-2",
            "Correlation and its caveats",
            "Compute the correlation, then state plainly what it does not show.",
            related=["REQ-002", "REQ-003"],
            confidence=0.8,
        ),
    ]
    data["deliverables"] = [
        _deliverable(
            "del-analysis",
            "The written analysis, including the cleaning log and caveats.",
            related=["REQ-001", "REQ-002", "REQ-003"],
            fmt="PDF",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the analysis document.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.84,
                )
            ],
        ),
        _deliverable(
            "del-dataset",
            "The cleaned dataset as a separate file.",
            related=["REQ-001", "REQ-004"],
            fmt="CSV",
            depends_on=["del-analysis"],
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "The cleaned dataset is its own deliverable.",
                    source_id="del-2",
                    location="deliverables.del-2",
                    confidence=0.8,
                )
            ],
        ),
    ]
    data["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "Cleaning has to be logged before it is analysed."),
        _edge("wa-1", "wa-2", "WORK_AREA", "The correlation is computed on cleaned data."),
        _edge("wa-2", "del-analysis", "DELIVERABLE", "The findings are written up here."),
        _edge(
            "del-analysis",
            "del-dataset",
            "DELIVERABLE",
            "The cleaned file ships with the write-up.",
        ),
    ]
    items["data_analysis"] = data

    # ------------------------------------------------------------ presentation
    presentation = _base(
        summary=(
            "A ten minute talk on renewable energy adoption for classmates who are "
            "not economists. The slides have to carry the argument and the notes "
            "have to survive being read aloud."
        ),
        types=[("PRESENTATION", 0.9)],
        domains=[("ECONOMICS", 0.76), ("SOCIAL_SCIENCES", 0.62)],
        confidence=0.75,
    )
    presentation["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Cover the current state of renewable energy policy.",
            confidence=0.87,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Cover the current state of renewable energy policy.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.87,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Present the main arguments, in a form a non-specialist can follow.",
            confidence=0.85,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Present the main arguments.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.85,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Recommend a policy direction.",
            confidence=0.82,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Recommend a policy direction.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.82,
                )
            ],
        ),
    ]
    presentation["work_areas"] = [
        _work_area(
            "wa-1",
            "Argument spine",
            "Decide the three claims the talk makes before designing a single slide.",
            related=["REQ-001", "REQ-002"],
            confidence=0.78,
        ),
        _work_area(
            "wa-2",
            "Slides and speaker notes",
            "One claim per slide, with notes written to be spoken aloud.",
            related=["REQ-003"],
            confidence=0.76,
        ),
    ]
    presentation["evaluation"]["rubric_available"] = True
    presentation["evaluation"]["criteria"] = [
        _criterion("Clarity for a non-specialist audience", related=["REQ-002"])
    ]
    presentation["deliverables"] = [
        _deliverable(
            "del-slides",
            "Presentation slides, one claim per slide.",
            related=["REQ-001", "REQ-002"],
            fmt="PPTX",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the slides.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.84,
                )
            ],
        ),
        _deliverable(
            "del-script",
            "Speaker notes covering every slide.",
            related=["REQ-003"],
            fmt="PDF",
            depends_on=["del-slides"],
            # The brief lists no separate notes deliverable, so this one is
            # honestly marked as inferred and cites nothing.
            uncertainty="AI_INFERENCE",
            evidence=[],
        ),
    ]
    presentation["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "The claims are fixed before any slide exists."),
        _edge("wa-1", "wa-2", "WORK_AREA", "Slides follow the argument spine."),
        _edge("wa-2", "del-slides", "DELIVERABLE", "The deck is assembled from the slides."),
        _edge(
            "del-slides",
            "del-script",
            "DELIVERABLE",
            "Notes are written against the finished deck.",
        ),
    ]
    items["presentation"] = presentation

    # ----------------------------------------------------------------- reading
    reading = _base(
        summary=(
            "A response paper on three chapters of a history textbook. It has to "
            "engage the book's argument rather than summarise it chapter by chapter."
        ),
        types=[("READING", 0.85)],
        domains=[("HUMANITIES", 0.79), ("SOCIAL_SCIENCES", 0.66)],
        confidence=0.74,
    )
    reading["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Read chapters 3-5 of the textbook.",
            confidence=0.85,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Read chapters 3-5.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.85,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Write a reading response that argues with the author.",
            confidence=0.87,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Write a reading response.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.87,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Prepare three discussion questions.",
            confidence=0.84,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Prepare three discussion questions.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.84,
                )
            ],
        ),
    ]
    reading["work_areas"] = [
        _work_area(
            "wa-1",
            "Reading notes",
            "Note where the author makes the load-bearing claim in each chapter.",
            related=["REQ-001", "REQ-003"],
            confidence=0.78,
        ),
        _work_area(
            "wa-2",
            "Response argument",
            "Pick one chapter and disagree with it specifically.",
            related=["REQ-002"],
            confidence=0.8,
        ),
    ]
    reading["deliverables"] = [
        _deliverable(
            "del-response",
            "The response paper, with two quoted passages and page numbers.",
            related=["REQ-001", "REQ-002", "REQ-003"],
            fmt="PDF",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the response paper.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.83,
                )
            ],
        ),
    ]
    reading["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "Notes are taken while reading, not after."),
        _edge("wa-1", "wa-2", "WORK_AREA", "The argument needs the notes to disagree with."),
        _edge("wa-2", "del-response", "DELIVERABLE", "The response is the final artefact."),
    ]
    items["reading_assignment"] = reading

    # ------------------------------------------- research and presentation mix
    mixed = _base(
        summary=(
            "Research into urban food security delivered as a written paper and then "
            "defended in a short presentation. The two outputs share one evidence "
            "base but are graded differently."
        ),
        types=[("RESEARCH", 0.82), ("PRESENTATION", 0.71)],
        domains=[("SOCIAL_SCIENCES", 0.8), ("HUMANITIES", 0.6)],
        confidence=0.69,
    )
    mixed["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Write a research paper on urban food security.",
            confidence=0.88,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Conduct research on urban food security.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.88,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Review the literature the paper draws on.",
            confidence=0.84,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Review the literature.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.84,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Present the findings in 15 minutes.",
            confidence=0.83,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Present the findings in 15 minutes.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.83,
                )
            ],
        ),
    ]
    mixed["work_areas"] = [
        _work_area(
            "wa-1",
            "Shared evidence base",
            "Collect and cite sources once, since both outputs draw on them.",
            related=["REQ-001"],
            confidence=0.78,
        ),
        _work_area(
            "wa-2",
            "Two outputs from one body of research",
            "Write the paper, then cut the presentation down from it.",
            related=["REQ-002", "REQ-003"],
            confidence=0.74,
        ),
    ]
    mixed["deliverables"] = [
        _deliverable(
            "del-paper",
            "The written paper, with citations.",
            related=["REQ-001", "REQ-002"],
            fmt="PDF",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "The paper is submitted in writing.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.84,
                )
            ],
        ),
        _deliverable(
            "deck",
            "The presentation defending the same findings.",
            related=["REQ-003"],
            fmt="PPTX",
            depends_on=["del-paper"],
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "The talk is a separate deliverable.",
                    source_id="del-2",
                    location="deliverables.del-2",
                    confidence=0.82,
                )
            ],
        ),
    ]
    mixed["evaluation"]["rubric_available"] = True
    mixed["evaluation"]["criteria"] = [
        _criterion("Paper and talk tell the same story", related=["REQ-001"]),
        _criterion("Talk fits the stated time", related=["REQ-003"]),
    ]
    mixed["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "The shared sources are gathered first."),
        _edge("wa-1", "wa-2", "WORK_AREA", "Both outputs are cut from the same research."),
        _edge("wa-2", "del-paper", "DELIVERABLE", "The paper is written first."),
        _edge("del-paper", "deck", "DELIVERABLE", "The talk is shortened from the paper."),
    ]
    items["research_and_presentation"] = mixed

    # ----------------------------------------- programming and report mix
    both = _base(
        summary=(
            "A small Java web API delivered together with a technical report "
            "explaining the design. The report is judged on whether it explains "
            "decisions, not on whether it restates the code."
        ),
        types=[("PROGRAMMING", 0.86), ("REPORT", 0.74)],
        domains=[("COMPUTER_SCIENCE", 0.88)],
        confidence=0.72,
    )
    both["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Implement a web API in Java.",
            confidence=0.89,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Implement a web API in Java.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.89,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Document the architecture in a report.",
            confidence=0.87,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Document the architecture in a report.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.87,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Describe the testing approach.",
            confidence=0.82,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Describe the testing approach.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.82,
                )
            ],
        ),
    ]
    both["work_areas"] = [
        _work_area(
            "wa-1",
            "API implementation",
            "Build the endpoints, then the error handling around them.",
            related=["REQ-001"],
            confidence=0.8,
        ),
        _work_area(
            "wa-2",
            "Design rationale",
            "Write up the two decisions a reader would otherwise have to guess at.",
            related=["REQ-002", "REQ-003"],
            confidence=0.76,
        ),
    ]
    both["evaluation"]["rubric_available"] = True
    both["evaluation"]["criteria"] = [
        _criterion("Design justification", related=["REQ-003"]),
        _criterion("Architecture is documented, not just described", related=["REQ-002"]),
    ]
    both["deliverables"] = [
        _deliverable(
            "del-code",
            "Source code for the Java web API, buildable as submitted.",
            related=["REQ-001"],
            fmt="ZIP",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "Submit the API source.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.85,
                )
            ],
        ),
        _deliverable(
            "del-report",
            "The technical report explaining the design decisions.",
            related=["REQ-002", "REQ-003"],
            fmt="PDF",
            depends_on=["del-code"],
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "The report accompanies the code.",
                    source_id="del-2",
                    location="deliverables.del-2",
                    confidence=0.84,
                )
            ],
        ),
    ]
    both["dependencies"] = [
        _edge(
            "REQ-001", "wa-1", "WORK_AREA", "The endpoints are built before anything is written up."
        ),
        _edge(
            "wa-1", "wa-2", "WORK_AREA", "The rationale can only be written once decisions exist."
        ),
        _edge("wa-2", "del-code", "DELIVERABLE", "The design is embodied in the code."),
        _edge("del-code", "del-report", "DELIVERABLE", "The report describes the shipped code."),
    ]
    items["programming_and_report"] = both

    # ------------------------------------------------------------- group project
    group = _base(
        summary=(
            "A team of four develops a sustainable business plan. The plan is "
            "judged as one deliverable, so the work has to be split in a way that "
            "leaves no part owned by nobody."
        ),
        types=[("GROUP_PROJECT", 0.86)],
        domains=[("BUSINESS", 0.85), ("ECONOMICS", 0.7)],
        confidence=0.73,
    )
    group["normalized_requirements"] = [
        _req(
            "REQ-001",
            "Develop a sustainable business plan as a team.",
            confidence=0.88,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Develop a sustainable business plan as a team.",
                    source_id="REQ-001",
                    location="requirements.REQ-001",
                    confidence=0.88,
                )
            ],
        ),
        _req(
            "REQ-002",
            "Contribute an individual section.",
            confidence=0.84,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Contribute an individual section.",
                    source_id="REQ-002",
                    location="requirements.REQ-002",
                    confidence=0.84,
                )
            ],
        ),
        _req(
            "REQ-003",
            "Present the plan together.",
            confidence=0.8,
            evidence=[
                _evidence(
                    "REQUIREMENT",
                    "Present the plan together.",
                    source_id="REQ-003",
                    location="requirements.REQ-003",
                    confidence=0.8,
                )
            ],
        ),
    ]
    group["work_areas"] = [
        _work_area(
            "wa-1",
            "Split the work",
            "Assign sections so every section has exactly one owner.",
            related=["REQ-001", "REQ-003"],
            origin="AI_INFERENCE",
            confidence=0.74,
        ),
        _work_area(
            "wa-2",
            "Integrate a single plan",
            "Merge the sections into one document with one shared structure.",
            related=["REQ-002"],
            confidence=0.8,
        ),
    ]
    group["evaluation"]["rubric_available"] = True
    group["evaluation"]["criteria"] = [
        _criterion("Quality of the business case", related=["REQ-002"])
    ]
    group["deliverables"] = [
        _deliverable(
            "del-plan",
            "Combined business plan, with contributions attributed.",
            related=["REQ-001", "REQ-002"],
            fmt="PDF",
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "A single plan document is submitted.",
                    source_id="del-1",
                    location="deliverables.del-1",
                    confidence=0.84,
                )
            ],
        ),
        _deliverable(
            "deck",
            "Presentation of the plan, delivered by the whole team.",
            related=["REQ-003"],
            fmt="PPTX",
            depends_on=["del-plan"],
            evidence=[
                _evidence(
                    "DELIVERABLE",
                    "The team presents the plan together.",
                    source_id="del-2",
                    location="deliverables.del-2",
                    confidence=0.8,
                )
            ],
        ),
    ]
    group["dependencies"] = [
        _edge("REQ-001", "wa-1", "WORK_AREA", "Sections are assigned once the team is fixed."),
        _edge("wa-1", "wa-2", "WORK_AREA", "Integration needs the sections to exist."),
        _edge("wa-2", "del-plan", "DELIVERABLE", "The merged sections become the plan."),
        _edge("del-plan", "deck", "DELIVERABLE", "The talk is cut from the finished plan."),
    ]
    items["group_project"] = group

    return items


def transcript_for(name: str) -> dict[str, Any] | None:
    """Return the recorded transcript for a fixture, or ``None`` if absent."""
    return _transcripts().get(name)


def recorded_names() -> set[str]:
    return set(_transcripts())
