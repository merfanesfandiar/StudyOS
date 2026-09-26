"""Deterministic academic analysis heuristics.

This is the grounding engine behind ``MockLLMProvider`` and a reusable source of
signals for specialized analyzers. It turns an analyzer input into a structured
analysis *without* a model call, so the full pipeline is reproducible in tests
and CI without credentials or network access.

It is deliberately academic and domain-agnostic. Programming is one lexicon
among many. Heuristics never solve the assignment: they classify, normalize,
flag gaps and propose work areas.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.ai.lexicon import (
    DOMAIN_KEYWORDS,
    RESOURCE_ROLE_HINTS,
    RESOURCE_TYPE_BY_EXTENSION,
    TYPE_KEYWORDS,
    VAGUE_PHRASES,
    VERIFICATION_TEMPLATES,
    WORK_AREA_TEMPLATES,
)
from app.models.enums import (
    AcademicDomain,
    AssignmentType,
    FindingSeverity,
    QuestionPriority,
    RequirementCategory,
    RequirementPriority,
    ScopeLevel,
    SourceKind,
)

STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "is",
        "are",
        "be",
        "as",
        "at",
        "from",
        "that",
        "this",
        "it",
        "its",
        "their",
        "your",
        "you",
        "must",
        "should",
        "will",
        "can",
        "may",
        "each",
        "all",
        "any",
        "write",
        "use",
        "using",
        "provide",
        "include",
        "including",
        "following",
        "work",
        "assignment",
        "student",
        "students",
        "course",
        "complete",
        "submit",
    }
)


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _pattern(phrase: str) -> str:
    escaped = re.escape(phrase)
    if phrase and phrase[0].isalnum() and phrase[-1].isalnum():
        return rf"(?<!\w){escaped}(?!\w)"
    return escaped


def _count(haystack: str, phrase: str) -> int:
    return len(re.findall(_pattern(phrase), haystack))


def _tokens(text: str | None) -> set[str]:
    return {
        token for token in re.findall(r"[a-z][a-z0-9+-]{2,}", _norm(text)) if token not in STOPWORDS
    }


def _haystack(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    assignment = payload.get("assignment", {})
    parts.extend([str(assignment.get("title") or ""), str(assignment.get("description") or "")])
    parts.append(str(payload.get("course_name") or ""))
    for group in ("requirements", "constraints", "criteria", "deliverables"):
        for item in payload.get(group, []) or []:
            parts.extend(
                [
                    str(item.get("title") or ""),
                    str(item.get("description") or ""),
                    str(item.get("value") or ""),
                    str(item.get("type") or ""),
                ]
            )
    for document in payload.get("document_texts", []) or []:
        parts.append(str(document.get("text") or ""))
    parts.append(str(payload.get("user_notes") or ""))
    return " \n ".join(part for part in parts if part)


def _match_requirements(text: str, requirements: list[dict[str, Any]]) -> list[str]:
    """Return the keys of requirements whose wording overlaps ``text``."""
    wanted = _tokens(text)
    matches: list[str] = []
    for index, requirement in enumerate(requirements, start=1):
        if wanted & _tokens(f"{requirement.get('title')} {requirement.get('description')}"):
            matches.append(f"R{index}")
    return matches


def _confidence(score: float, *, floor: float = 0.4, ceiling: float = 0.95) -> float:
    return round(min(ceiling, max(floor, 0.45 + 0.05 * score)), 2)


#: A single incidental keyword is not enough evidence for a type. Two matches
#: (or one match in the title) are required, which keeps false positives down.
MIN_TYPE_SCORE = 2
MIN_DOMAIN_SCORE = 1


def classify(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(assignment_types, academic_domains)`` with confidence."""
    haystack = _haystack(payload)
    title = _norm(payload.get("assignment", {}).get("title"))

    type_scores: dict[AssignmentType, float] = {}
    for assignment_type, keywords in TYPE_KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            score += 2.0 * _count(title, keyword)
            score += _count(haystack, keyword)
        if score >= MIN_TYPE_SCORE:
            type_scores[assignment_type] = score

    domain_scores: dict[AcademicDomain, float] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            score += 2.0 * _count(title, keyword)
            score += _count(haystack, keyword)
        if score >= MIN_DOMAIN_SCORE:
            domain_scores[domain] = score

    assigned_types = payload.get("assigned_types") or []
    assigned_domains = payload.get("assigned_domains") or []

    types: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for value in assigned_types:
        if value not in seen_types:
            types.append({"type": value, "confidence": 0.99})
            seen_types.add(value)
    for assignment_type, score in sorted(
        type_scores.items(), key=lambda item: (-item[1], item[0].value)
    ):
        if assignment_type.value in seen_types:
            continue
        types.append({"type": assignment_type.value, "confidence": _confidence(score)})
        seen_types.add(assignment_type.value)
        if len(types) >= 3:
            break
    if not types:
        types.append({"type": AssignmentType.OTHER.value, "confidence": 0.3})

    domains: list[dict[str, Any]] = []
    seen_domains: set[str] = set()
    for value in assigned_domains:
        if value not in seen_domains:
            domains.append({"domain": value, "confidence": 0.99})
            seen_domains.add(value)
    for domain, score in sorted(domain_scores.items(), key=lambda item: (-item[1], item[0].value)):
        if domain.value in seen_domains:
            continue
        domains.append({"domain": domain.value, "confidence": _confidence(score)})
        seen_domains.add(domain.value)
        if len(domains) >= 3:
            break
    if not domains:
        domains.append({"domain": AcademicDomain.OTHER.value, "confidence": 0.3})

    return types, domains


def _evidence(
    source_type: str,
    supports: str,
    *,
    source_id: str | None = None,
    location: str | None = None,
    excerpt: str | None = None,
    confidence: float = 0.6,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "location": location,
        "excerpt_reference": excerpt,
        "supports": supports,
        "confidence": confidence,
    }


def build_summary(
    payload: dict[str, Any], types: list[dict[str, Any]], domains: list[dict[str, Any]]
) -> str:
    assignment = payload.get("assignment", {})
    title = assignment.get("title") or "This assignment"
    type_labels = ", ".join(item["type"].replace("_", " ").title() for item in types)
    domain_labels = ", ".join(item["domain"].replace("_", " ").title() for item in domains)
    requirement_count = len(payload.get("requirements", []) or [])
    deliverable_titles = [item.get("title", "") for item in payload.get("deliverables", []) or []]

    sentences = [f"{title} is a {type_labels} assignment in {domain_labels}."]
    if requirement_count:
        sentences.append(
            f"It lists {requirement_count} requirement(s) that the finished work must satisfy."
        )
    if deliverable_titles:
        pretty = ", ".join(title for title in deliverable_titles[:4] if title)
        if pretty:
            sentences.append(f"Expected output includes {pretty}.")
    return " ".join(sentences)


def _requirement_category(requirement: dict[str, Any]) -> RequirementCategory:
    by_type = {
        "FUNCTIONAL": RequirementCategory.CONTENT,
        "TECHNICAL": RequirementCategory.TECHNICAL,
        "DESIGN": RequirementCategory.METHODOLOGY,
        "DOCUMENTATION": RequirementCategory.DELIVERABLE,
        "CONSTRAINT": RequirementCategory.FORMAT,
        "PERFORMANCE": RequirementCategory.QUALITY,
        "SECURITY": RequirementCategory.QUALITY,
        "TESTING": RequirementCategory.EVALUATION,
        "OTHER": RequirementCategory.OTHER,
    }
    text = _norm(f"{requirement.get('title')} {requirement.get('description')}")
    if any(word in text for word in ("cite", "citation", "source", "reference", "bibliograph")):
        return RequirementCategory.ACADEMIC
    if any(word in text for word in ("format", "page", "word limit", "font", "template")):
        return RequirementCategory.FORMAT
    if any(word in text for word in ("present", "slide", "poster")):
        return RequirementCategory.PRESENTATION
    if any(word in text for word in ("method", "methodology", "approach", "procedure")):
        return RequirementCategory.METHODOLOGY
    if any(word in text for word in ("analy", "compare", "evaluate", "discuss", "justify")):
        return RequirementCategory.CONTENT
    return by_type.get(requirement.get("type", "OTHER"), RequirementCategory.OTHER)


def normalize_requirements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize the authoritative Phase 2 requirements, preserving traceability."""
    normalized: list[dict[str, Any]] = []
    for index, requirement in enumerate(payload.get("requirements", []) or [], start=1):
        title = requirement.get("title") or f"Requirement {index}"
        code = requirement.get("code") or f"REQ-{index:03d}"
        normalized.append(
            {
                "key": f"R{index}",
                "title": title[:300],
                "description": (requirement.get("description") or None),
                "category": _requirement_category(requirement).value,
                "priority": requirement.get("priority") or RequirementPriority.MEDIUM.value,
                "required": bool(requirement.get("is_required", True)),
                "source": SourceKind.EXPLICIT.value,
                "source_reference": code,
                "confidence": 0.99,
                "evidence": [
                    _evidence(
                        "REQUIREMENT",
                        f"Explicit requirement {code}",
                        source_id=code,
                        location=code,
                        excerpt=title[:200],
                        confidence=0.99,
                    )
                ],
            }
        )
    return normalized


def build_objectives(
    types: list[dict[str, Any]], requirements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    templates = {
        AssignmentType.MATHEMATICAL_PROOF.value: (
            "Demonstrate understanding of the underlying definitions and theorems",
            "Construct rigorous, logically valid proofs",
        ),
        AssignmentType.PROBLEM_SET.value: (
            "Apply the relevant theory to solve each problem",
            "Show correct, reproducible working",
        ),
        AssignmentType.PROGRAMMING.value: (
            "Implement the required behaviour",
            "Demonstrate correctness and provide tests",
        ),
        AssignmentType.DATA_ANALYSIS.value: (
            "Analyze the data with appropriate methods",
            "Communicate findings supported by evidence",
        ),
        AssignmentType.LAB_REPORT.value: (
            "Follow the experimental procedure and analyze measurements",
            "Discuss sources of error",
        ),
        AssignmentType.RESEARCH.value: (
            "Evaluate and compare existing work",
            "Produce a research-supported conclusion",
        ),
        AssignmentType.LITERATURE_REVIEW.value: (
            "Synthesize a body of literature",
            "Identify themes, agreements and gaps",
        ),
        AssignmentType.ESSAY.value: (
            "Develop and defend a thesis",
            "Support the argument with evidence",
        ),
        AssignmentType.PRESENTATION.value: (
            "Communicate the material clearly to an audience",
            "Cover the required topics within the time limit",
        ),
        AssignmentType.READING.value: (
            "Engage critically with the assigned text",
            "Summarize the key ideas accurately",
        ),
        AssignmentType.LANGUAGE.value: (
            "Apply the target language accurately",
            "Demonstrate grammar and vocabulary control",
        ),
        AssignmentType.DESIGN.value: (
            "Respond to the design brief",
            "Produce a coherent design artifact",
        ),
        AssignmentType.GROUP_PROJECT.value: (
            "Collaborate effectively to deliver the work",
            "Integrate individual contributions",
        ),
        AssignmentType.REPORT.value: (
            "Present the required information clearly",
            "Support conclusions with evidence",
        ),
        AssignmentType.OTHER.value: ("Understand and address the assignment requirements",),
    }
    objectives: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in types:
        for statement in templates.get(item["type"], templates[AssignmentType.OTHER.value]):
            if statement in seen:
                continue
            # Objectives are inferences, so confidence tracks the classification.
            objectives.append(
                {
                    "statement": statement,
                    "source": SourceKind.AI_INFERENCE.value,
                    "confidence": min(0.85, float(item.get("confidence", 0.5))),
                }
            )
            seen.add(statement)
    for requirement in requirements:
        statement = f"Satisfy: {requirement['title']}"
        if statement in seen:
            continue
        objectives.append(
            {
                "statement": statement[:300],
                "source": SourceKind.EXPLICIT.value,
                "confidence": 0.9,
            }
        )
        seen.add(statement)
        if len(objectives) >= 8:
            break
    return objectives


def _sources_text(payload: dict[str, Any], key: str) -> list[str]:
    values: list[str] = []
    for item in payload.get(key, []) or []:
        values.extend(
            [item.get("title") or "", item.get("description") or "", item.get("value") or ""]
        )
    for document in payload.get("document_texts", []) or []:
        values.append(document.get("text") or "")
    return values


def detect_ambiguities(
    payload: dict[str, Any], requirements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    haystack = _haystack(payload)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for phrase in VAGUE_PHRASES:
        if not _count(haystack, phrase):
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        affected = [
            requirement["key"]
            for requirement in requirements
            if phrase in _norm(f"{requirement.get('title')} {requirement.get('description')}")
        ]
        group = _sources_text(payload, "requirements")
        ambiguous = any(phrase in _norm(text) for text in group)
        results.append(
            {
                "key": f"A{len(results) + 1}",
                "description": (
                    f'The phrase "{phrase}" is used without a precise, measurable '
                    "definition, so different readers could judge it differently."
                ),
                "severity": FindingSeverity.WARNING.value,
                "affected_requirements": affected,
                "evidence": [
                    _evidence(
                        "DESCRIPTION",
                        f"Ambiguous wording: {phrase}",
                        location="description",
                        excerpt=phrase,
                        confidence=0.6,
                    )
                ],
                "suggested_clarification": (
                    f'Ask what counts as "{phrase}" and any minimum/maximum it implies.'
                ),
                "confidence": 0.6 if ambiguous else 0.45,
            }
        )
        if len(results) >= 6:
            break
    return results


_YEAR_BEFORE = re.compile(r"(?:before|prior to|no later than)\s+(19|20)\d{2}", re.I)
_YEAR_AFTER = re.compile(r"(?:after|since|from)\s+(19|20)\d{2}", re.I)
_YEAR_ANY = re.compile(r"\b(?:19|20)\d{2}\b")


def detect_contradictions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    haystack = _haystack(payload)
    results: list[dict[str, Any]] = []
    before = _YEAR_BEFORE.search(haystack)
    after = _YEAR_AFTER.search(haystack)
    if before and after:
        results.append(
            {
                "key": "C1",
                "description": (
                    "One instruction limits sources to years before a cutoff while another "
                    "asks for sources after a later year. These cannot both be satisfied."
                ),
                "conflicting_items": [before.group(0), after.group(0)],
                "severity": FindingSeverity.CRITICAL.value,
                "evidence": [
                    _evidence(
                        "DESCRIPTION",
                        "Conflicting source-date instructions",
                        location="description",
                    )
                ],
                "clarification_needed": True,
                "confidence": 0.7,
            }
        )
    elif before and _YEAR_ANY.search(haystack.replace(before.group(0), "", 1)):
        later = [
            year for year in _YEAR_ANY.findall(haystack) if int(year) > int(before.group(0)[-4:])
        ]
        if later:
            results.append(
                {
                    "key": "C1",
                    "description": (
                        "A source cutoff is stated, but the assignment also references sources "
                        "published after that cutoff."
                    ),
                    "conflicting_items": [before.group(0)],
                    "severity": FindingSeverity.IMPORTANT.value,
                    "evidence": [
                        _evidence("DESCRIPTION", "Source cutoff conflicts with referenced sources")
                    ],
                    "clarification_needed": True,
                    "confidence": 0.55,
                }
            )
    individual = any(word in haystack for word in ("individual", "on your own", "individually"))
    group = any(word in haystack for word in ("group", "team", "collaborat"))
    if individual and group:
        results.append(
            {
                "key": f"C{len(results) + 1}",
                "description": (
                    "The assignment mentions both individual work and group/team work, which "
                    "may conflict depending on what is graded individually."
                ),
                "conflicting_items": ["individual work", "group work"],
                "severity": FindingSeverity.WARNING.value,
                "evidence": [_evidence("DESCRIPTION", "Individual and group wording both present")],
                "clarification_needed": True,
                "confidence": 0.5,
            }
        )
    no_sources = any(
        phrase in haystack
        for phrase in ("no outside sources", "no external sources", "without sources")
    )
    requires_sources = any(
        phrase in haystack for phrase in ("at least", "minimum of", "cite", "sources required")
    )
    if no_sources and requires_sources:
        results.append(
            {
                "key": f"C{len(results) + 1}",
                "description": "The assignment both forbids and requires external sources.",
                "conflicting_items": ["no external sources", "required sources"],
                "severity": FindingSeverity.CRITICAL.value,
                "evidence": [_evidence("DESCRIPTION", "Source requirement contradicts source ban")],
                "clarification_needed": True,
                "confidence": 0.6,
            }
        )
    return results


def detect_missing_information(
    payload: dict[str, Any], types: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    haystack = _haystack(payload)
    type_values = {item["type"] for item in types}
    assignment = payload.get("assignment", {})

    def add(description: str, area: str, severity: str, confidence: float = 0.6) -> None:
        results.append(
            {
                "key": f"M{len(results) + 1}",
                "description": description,
                "area": area,
                "severity": severity,
                "evidence": [_evidence("INFERENCE", description)],
                "confidence": confidence,
            }
        )

    if not payload.get("criteria"):
        add(
            "No rubric or grading criteria were provided.",
            "EVALUATION",
            FindingSeverity.WARNING.value,
            0.8,
        )
    if not assignment.get("deadline"):
        add("No deadline was specified.", "PROCESS", FindingSeverity.IMPORTANT.value, 0.9)
    if not payload.get("deliverables"):
        add(
            "It is not stated what must be handed in.",
            "DELIVERABLE",
            FindingSeverity.IMPORTANT.value,
            0.7,
        )
    has_format = any(
        "format" in _norm(f"{item.get('title')} {item.get('description')} {item.get('value')}")
        or "page" in _norm(f"{item.get('title')} {item.get('description')}")
        or "word" in _norm(f"{item.get('title')} {item.get('description')}")
        for item in payload.get("constraints", []) or []
    )
    if not has_format:
        add(
            "The submission format (file type, length, layout) is not specified.",
            "FORMAT",
            FindingSeverity.WARNING.value,
        )
    if (
        AssignmentType.RESEARCH.value in type_values
        or AssignmentType.LITERATURE_REVIEW.value in type_values
    ) and not any(
        style in haystack
        for style in ("apa", "mla", "chicago", "harvard", "ieee", "citation style")
    ):
        add(
            "The required citation style is not specified.",
            "ACADEMIC",
            FindingSeverity.WARNING.value,
        )
    if AssignmentType.PRESENTATION.value in type_values and not re.search(
        r"\b\d+\s*(min|minute)", haystack
    ):
        add(
            "The presentation duration is not specified.",
            "PRESENTATION",
            FindingSeverity.WARNING.value,
        )
    if AssignmentType.DATA_ANALYSIS.value in type_values and not (payload.get("resources") or []):
        add("No dataset was attached or linked.", "RESOURCE", FindingSeverity.IMPORTANT.value, 0.7)
    if AssignmentType.LAB_REPORT.value in type_values and not (payload.get("resources") or []):
        add(
            "No lab manual or procedure document was attached.",
            "RESOURCE",
            FindingSeverity.WARNING.value,
            0.6,
        )
    return results


def detect_assumptions(
    payload: dict[str, Any], types: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    haystack = _haystack(payload)
    type_values = {item["type"] for item in types}
    results: list[dict[str, Any]] = []

    def add(statement: str, confidence: float) -> None:
        results.append(
            {
                "key": f"S{len(results) + 1}",
                "statement": statement,
                "confidence": confidence,
                "evidence": [_evidence("INFERENCE", statement, confidence=confidence)],
            }
        )

    if AssignmentType.GROUP_PROJECT.value not in type_values and not any(
        word in haystack for word in ("group", "team", "collaborat", "individual")
    ):
        add(
            "The assignment appears to be individual work because collaboration is not mentioned.",
            0.35,
        )
    if AssignmentType.PROGRAMMING.value in type_values and not any(
        language in haystack
        for language in ("python", "java", "c++", "javascript", "typescript", "rust", "go ")
    ):
        add("No implementation language is specified; any suitable language is assumed.", 0.3)
    if (AssignmentType.RESEARCH.value in type_values) and not any(
        style in haystack for style in ("apa", "mla", "chicago", "harvard", "ieee")
    ):
        add("A standard academic citation style is assumed.", 0.3)
    return results


def build_questions(
    ambiguities: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    missing_information: list[dict[str, Any]],
    *,
    include_questions: bool = True,
) -> list[dict[str, Any]]:
    if not include_questions:
        return []
    questions: list[dict[str, Any]] = []
    for item in contradictions:
        questions.append(
            {
                "code": f"Q-{len(questions) + 1:03d}",
                "priority": QuestionPriority.CRITICAL.value,
                "question": f"How should I resolve the conflict: {item['description']}",
                "rationale": "Conflicting instructions cannot both be satisfied.",
                "related_requirements": item.get("conflicting_items", []),
                "confidence": 0.8,
            }
        )
    important_areas = {"EVALUATION", "DELIVERABLE", "PROCESS", "RESOURCE"}
    for item in missing_information:
        priority = (
            QuestionPriority.CRITICAL.value
            if item["area"] in important_areas
            else QuestionPriority.IMPORTANT.value
        )
        questions.append(
            {
                "code": f"Q-{len(questions) + 1:03d}",
                "priority": priority,
                "question": f"Could you clarify: {item['description']}",
                "rationale": f"Missing information in {item['area'].lower()}.",
                "related_requirements": [],
                "confidence": 0.7,
            }
        )
    for item in ambiguities:
        questions.append(
            {
                "code": f"Q-{len(questions) + 1:03d}",
                "priority": not item.get("affected_requirements")
                and QuestionPriority.OPTIONAL.value
                or QuestionPriority.IMPORTANT.value,
                "question": item.get("suggested_clarification")
                or f"Could you clarify: {item['description']}",
                "rationale": "Ambiguous wording.",
                "related_requirements": item.get("affected_requirements", []),
                "confidence": 0.6,
            }
        )
    return questions[:10]


_DELIVERABLES_BY_TYPE: dict[str, tuple[tuple[str, str], ...]] = {
    AssignmentType.PROGRAMMING.value: (
        ("Source code", "source repository"),
        ("Written explanation", "document"),
    ),
    AssignmentType.MATHEMATICAL_PROOF.value: (("Written proof solutions", "document"),),
    AssignmentType.PROBLEM_SET.value: (("Worked solutions", "document"),),
    AssignmentType.DATA_ANALYSIS.value: (
        ("Analysis report", "document"),
        ("Analysis notebook or script", "code"),
    ),
    AssignmentType.LAB_REPORT.value: (("Lab report", "document"),),
    AssignmentType.RESEARCH.value: (("Research paper", "document"),),
    AssignmentType.LITERATURE_REVIEW.value: (("Literature review", "document"),),
    AssignmentType.ESSAY.value: (("Essay", "document"),),
    AssignmentType.PRESENTATION.value: (("Presentation slides", "presentation"),),
    AssignmentType.READING.value: (("Reading response", "document"),),
    AssignmentType.LANGUAGE.value: (("Completed exercises", "document"),),
    AssignmentType.DESIGN.value: (("Design artifact", "artifact"),),
    AssignmentType.GROUP_PROJECT.value: (("Combined submission", "document"),),
    AssignmentType.REPORT.value: (("Report", "document"),),
    AssignmentType.OTHER.value: (("Submission", "document"),),
}


def build_deliverables(
    payload: dict[str, Any], requirements: list[dict[str, Any]], types: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    authoritative = payload.get("deliverables", []) or []
    deliverables: list[dict[str, Any]] = []
    if authoritative:
        for index, item in enumerate(authoritative, start=1):
            title = item.get("title") or f"Deliverable {index}"
            deliverables.append(
                {
                    "key": f"D{index}",
                    "title": title[:300],
                    "description": item.get("description") or None,
                    "required": bool(item.get("is_required", True)),
                    "expected_content": [],
                    "format": _format_for_deliverable(item),
                    "related_requirements": _match_requirements(title, requirements),
                    "verification_needs": ["Present and complete before submission"],
                    "uncertainty": SourceKind.EXPLICIT.value,
                    "evidence": [
                        _evidence(
                            "DELIVERABLE",
                            f"Explicit deliverable: {title}",
                            source_id=str(item.get("id")) if item.get("id") else None,
                            location="deliverables",
                            excerpt=title[:200],
                            confidence=0.95,
                        )
                    ],
                    "confidence": 0.95,
                }
            )
        # inferred relationships between authoritative deliverables
        _link_deliverable_dependencies(deliverables)
        return deliverables

    seen: set[str] = set()
    for item in types:
        for title, fmt in _DELIVERABLES_BY_TYPE.get(
            item["type"], _DELIVERABLES_BY_TYPE[AssignmentType.OTHER.value]
        ):
            if title in seen:
                continue
            seen.add(title)
            deliverables.append(
                {
                    "key": f"D{len(deliverables) + 1}",
                    "title": title,
                    "description": None,
                    "required": None,
                    "expected_content": [],
                    "format": fmt,
                    "related_requirements": [requirement["key"] for requirement in requirements],
                    "verification_needs": ["Confirm with the instructor that this is expected"],
                    "uncertainty": SourceKind.AI_INFERENCE.value,
                    "evidence": [
                        _evidence(
                            "INFERENCE",
                            f"Inferred from assignment type {item['type']}",
                            confidence=0.45,
                        )
                    ],
                    "confidence": min(0.6, float(item.get("confidence", 0.5))),
                }
            )
    _link_deliverable_dependencies(deliverables)
    return deliverables


def _format_for_deliverable(item: dict[str, Any]) -> str | None:
    raw = (item.get("type") or "").upper()
    return {
        "DOCUMENT": "document",
        "SOURCE_CODE": "source code",
        "DATASET": "dataset",
        "PRESENTATION": "presentation",
        "TEST_SUITE": "test suite",
        "VIDEO": "video",
    }.get(raw)


def _link_deliverable_dependencies(deliverables: list[dict[str, Any]]) -> None:
    """Link deliverables that build on each other using a generic order.

    A later artifact that presents or documents earlier material depends on it,
    whatever the discipline: source code and datasets come first, written output
    next, and presentations/videos last. It is a soft, illustrative relationship,
    never a fabricated hard constraint.
    """
    rank = {
        "source code": 0,
        "dataset": 0,
        "test suite": 1,
        "document": 1,
        "artifact": 1,
        "presentation": 2,
        "video": 2,
    }
    ordered = sorted(
        range(len(deliverables)),
        key=lambda index: rank.get((deliverables[index].get("format") or "").lower(), 1),
    )
    for position, index in enumerate(ordered):
        current_rank = rank.get((deliverables[index].get("format") or "").lower(), 1)
        for earlier in reversed(ordered[:position]):
            earlier_rank = rank.get((deliverables[earlier].get("format") or "").lower(), 1)
            if earlier_rank < current_rank:
                deliverables[index].setdefault("depends_on", [])
                exists = deliverables[index]["depends_on"]
                if deliverables[earlier]["key"] not in exists:
                    exists.append(deliverables[earlier]["key"])
                break


def build_evaluation(
    payload: dict[str, Any], requirements: list[dict[str, Any]], types: list[dict[str, Any]]
) -> dict[str, Any]:
    criteria = payload.get("criteria", []) or []
    if criteria:
        built: list[dict[str, Any]] = []
        for item in criteria:
            weight = item.get("weight")
            built.append(
                {
                    "title": (item.get("title") or "Criterion")[:300],
                    "description": item.get("description") or None,
                    "weight": str(Decimal(str(weight))) if weight is not None else None,
                    "related_requirements": _match_requirements(
                        f"{item.get('title')} {item.get('description')}", requirements
                    ),
                    "implied": False,
                    "confidence": 0.95,
                }
            )
        return {
            "rubric_available": True,
            "criteria": built,
            "implied_quality_expectations": [],
            "missing_rubric_information": [],
            "confidence": 0.9,
        }

    expectations: list[str] = []
    for item in types[:2]:
        for title, description, _method in VERIFICATION_TEMPLATES.get(
            AssignmentType(item["type"]), VERIFICATION_TEMPLATES[AssignmentType.OTHER]
        ):
            expectations.append(f"{title}: {description}")
    return {
        "rubric_available": False,
        "criteria": [],
        "implied_quality_expectations": expectations[:6],
        "missing_rubric_information": [
            "No weighting was provided, so relative effort cannot be derived from the marking ",
            "scheme.",
        ],
        "confidence": 0.6,
    }


def build_scope(
    payload: dict[str, Any],
    types: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    deliverables: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    type_values = {item["type"] for item in types}
    requirement_count = len(requirements)
    deliverable_count = len(deliverables)

    def dim(level: ScopeLevel, rationale: str) -> dict[str, Any]:
        return {"level": level.value, "rationale": rationale}

    research = (
        ScopeLevel.HIGH
        if type_values & {AssignmentType.RESEARCH.value, AssignmentType.LITERATURE_REVIEW.value}
        else ScopeLevel.NOT_APPLICABLE
    )
    reasoning = (
        ScopeLevel.HIGH
        if type_values & {AssignmentType.MATHEMATICAL_PROOF.value, AssignmentType.PROBLEM_SET.value}
        else ScopeLevel.MEDIUM
        if type_values & {AssignmentType.PROGRAMMING.value, AssignmentType.DATA_ANALYSIS.value}
        else ScopeLevel.LOW
    )
    technical = (
        ScopeLevel.HIGH
        if AssignmentType.PROGRAMMING.value in type_values
        else ScopeLevel.MEDIUM
        if AssignmentType.DATA_ANALYSIS.value in type_values
        else ScopeLevel.NOT_APPLICABLE
    )
    writing = (
        ScopeLevel.HIGH
        if type_values
        & {
            AssignmentType.RESEARCH.value,
            AssignmentType.ESSAY.value,
            AssignmentType.LITERATURE_REVIEW.value,
            AssignmentType.LAB_REPORT.value,
            AssignmentType.REPORT.value,
        }
        else ScopeLevel.MEDIUM
        if AssignmentType.PROBLEM_SET.value in type_values
        else ScopeLevel.LOW
    )
    experimental = (
        ScopeLevel.HIGH
        if AssignmentType.LAB_REPORT.value in type_values
        else ScopeLevel.NOT_APPLICABLE
    )
    presentation = (
        ScopeLevel.HIGH
        if AssignmentType.PRESENTATION.value in type_values
        else ScopeLevel.NOT_APPLICABLE
    )
    breadth = (
        ScopeLevel.HIGH
        if requirement_count >= 8
        else ScopeLevel.MEDIUM
        if requirement_count >= 4
        else ScopeLevel.LOW
        if requirement_count
        else ScopeLevel.UNKNOWN
    )
    depth = ScopeLevel.HIGH if len(type_values) > 1 else ScopeLevel.MEDIUM
    dependency_complexity = (
        ScopeLevel.HIGH
        if len(dependencies) >= 6
        else ScopeLevel.MEDIUM
        if len(dependencies) >= 2
        else ScopeLevel.LOW
    )
    levels = [
        breadth,
        depth,
        research,
        reasoning,
        technical,
        writing,
        experimental,
        presentation,
        dependency_complexity,
    ]
    weights = {
        ScopeLevel.HIGH: 3,
        ScopeLevel.MEDIUM: 2,
        ScopeLevel.LOW: 1,
        ScopeLevel.NOT_APPLICABLE: 0,
        ScopeLevel.UNKNOWN: 0,
    }
    applicable = [level for level in levels if level is not ScopeLevel.NOT_APPLICABLE]
    score = sum(weights[level] for level in applicable) / max(1, len(applicable))
    overall = (
        ScopeLevel.HIGH if score >= 2.5 else ScopeLevel.MEDIUM if score >= 1.5 else ScopeLevel.LOW
    )
    return {
        "breadth": dim(breadth, f"{requirement_count} requirement(s) recorded."),
        "depth": dim(depth, f"{len(type_values)} assignment type(s) detected."),
        "research_intensity": dim(research, "Based on assignment type."),
        "reasoning_intensity": dim(reasoning, "Estimated from the reasoning-heavy types present."),
        "technical_complexity": dim(technical, "Technical work only applies to some assignments."),
        "writing_intensity": dim(writing, "Estimated from the writing-heavy types present."),
        "experimental_complexity": dim(
            experimental, "Lab work is not applicable to every assignment."
        ),
        "presentation_complexity": dim(
            presentation, "Presentation work is one dimension among several."
        ),
        "dependency_complexity": dim(
            dependency_complexity, f"{len(dependencies)} dependency edge(s) identified."
        ),
        "deliverable_count": deliverable_count,
        "requirement_count": requirement_count,
        "overall": overall.value,
        "confidence": 0.6,
    }


def build_work_areas(
    payload: dict[str, Any], types: list[dict[str, Any]], requirements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in types:
        for title, category in WORK_AREA_TEMPLATES.get(
            AssignmentType(item["type"]), WORK_AREA_TEMPLATES[AssignmentType.OTHER]
        ):
            if title in seen:
                continue
            seen.add(title)
            related = _match_requirements(title, requirements)
            areas.append(
                {
                    "key": f"W{len(areas) + 1}",
                    "title": title,
                    "description": None,
                    "category": category.value,
                    "related_requirements": related,
                    "depends_on": [],
                    "origin": SourceKind.EXPLICIT.value
                    if related
                    else SourceKind.AI_INFERENCE.value,
                    "confidence": 0.7 if related else min(0.65, float(item.get("confidence", 0.5))),
                }
            )
    for index, area in enumerate(areas):
        if index:
            area["depends_on"] = [areas[index - 1]["key"]]
    return areas


def build_resources(payload: dict[str, Any]) -> dict[str, Any]:
    resources = payload.get("resources", []) or []
    texts = {str(item.get("document_id")): item for item in payload.get("document_texts", []) or []}
    insights: list[dict[str, Any]] = []
    for item in resources:
        filename = item.get("filename") or "resource"
        lowered = filename.lower()
        resource_type = item.get("resource_type") or _resource_type(filename)
        role = _resource_role(lowered)
        text = (texts.get(str(item.get("id"))) or {}).get("text") or ""
        insights.append(
            {
                "document_id": str(item.get("id")) if item.get("id") else None,
                "filename": filename[:300],
                "resource_type": resource_type,
                "role": role,
                "relevant_sections": _extract_sections(text),
                "referenced_concepts": _extract_concepts(text),
                "instructions": _extract_instructions(text),
                "constraints": _extract_constraints(text),
                "terminology": [],
                "evidence": [
                    _evidence(
                        "RESOURCE",
                        f"Attached resource: {filename}",
                        source_id=str(item.get("id")) if item.get("id") else None,
                        location=filename,
                        confidence=0.7,
                    )
                ],
                "confidence": 0.7 if text else 0.5,
            }
        )
    notes: list[str] = []
    if resources and not texts:
        notes.append(
            "Resource metadata was analyzed. Document text is only sent when the deployment "
            "explicitly enables it."
        )
    return {"resources": insights, "notes": notes, "confidence": 0.6 if insights else 0.4}


def _resource_type(filename: str) -> str:
    lowered = filename.lower()
    for extension, resource_type in RESOURCE_TYPE_BY_EXTENSION.items():
        if lowered.endswith(extension):
            return resource_type
    return "OTHER"


def _resource_role(lowered_name: str) -> str:
    for hint, role in RESOURCE_ROLE_HINTS:
        if hint in lowered_name:
            return role
    return "OTHER"


def _extract_sections(text: str) -> list[str]:
    if not text:
        return []
    headings = re.findall(r"^#{1,4}\s+(.+)$", text, re.M)
    return [heading.strip()[:120] for heading in headings[:8]]


def _extract_concepts(text: str) -> list[str]:
    if not text:
        return []
    candidates = re.findall(r"\b([A-Z][a-zA-Z]{3,}(?:\s+[A-Z][a-zA-Z]{3,})?)\b", text)
    unique: list[str] = []
    for candidate in candidates:
        if candidate.lower() in STOPWORDS:
            continue
        if candidate not in unique:
            unique.append(candidate)
        if len(unique) >= 10:
            break
    return unique


def _extract_instructions(text: str) -> list[str]:
    if not text:
        return []
    lines = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"\b(must|should|required|submit|include|do not|ensure)\b", line, re.I)
    ]
    return [line[:200] for line in lines[:8]]


def _extract_constraints(text: str) -> list[str]:
    if not text:
        return []
    lines = [
        line.strip()
        for line in text.splitlines()
        if re.search(
            r"\b(max|min|maximum|minimum|at least|at most|pages?|words?|minutes?)\b", line, re.I
        )
    ]
    return [line[:200] for line in lines[:8]]


def build_dependencies(
    work_areas: list[dict[str, Any]], deliverables: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for area in work_areas:
        for predecessor in area.get("depends_on", []):
            edges.append(
                {
                    "predecessor": predecessor,
                    "successor": area["key"],
                    "kind": "WORK_AREA",
                    "reason": None,
                    "confidence": 0.6,
                }
            )
    for deliverable in deliverables:
        for predecessor in deliverable.get("depends_on", []):
            edges.append(
                {
                    "predecessor": predecessor,
                    "successor": deliverable["key"],
                    "kind": "DELIVERABLE",
                    "reason": "The later deliverable builds on the earlier one.",
                    "confidence": 0.5,
                }
            )
    return edges


def build_verification(types: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in types[:2]:
        for title, description, method in VERIFICATION_TEMPLATES.get(
            AssignmentType(item["type"]), VERIFICATION_TEMPLATES[AssignmentType.OTHER]
        ):
            if title in seen:
                continue
            seen.add(title)
            items.append(
                {
                    "title": title,
                    "description": description,
                    "method": method,
                    "applies_to": [],
                    "confidence": min(0.85, float(item.get("confidence", 0.5))),
                }
            )
    return {
        "items": items,
        "notes": [
            "This is a verification strategy, not verification. Nothing here claims the work "
            "is complete."
        ],
        "confidence": 0.65,
    }


def build_risks(
    ambiguities: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    missing_information: list[dict[str, Any]],
    payload: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []

    def add(
        description: str, severity: str, area: str, mitigation: str, confidence: float = 0.6
    ) -> None:
        risks.append(
            {
                "key": f"K{len(risks) + 1}",
                "description": description,
                "severity": severity,
                "affected_area": area,
                "evidence": [_evidence("INFERENCE", description, confidence=confidence)],
                "mitigation_hint": mitigation,
                "confidence": confidence,
            }
        )

    for _ in contradictions:
        add(
            "Conflicting requirements could make the submission non-compliant.",
            FindingSeverity.CRITICAL.value,
            "REQUIREMENTS",
            "Resolve the conflict with the instructor before starting.",
            0.8,
        )
    for item in ambiguities:
        add(
            f"Ambiguous wording: {item['description']}",
            FindingSeverity.WARNING.value,
            "REQUIREMENTS",
            "Ask for a precise definition before committing to an interpretation.",
            0.5,
        )
    for item in missing_information:
        add(
            f"Missing information in {item['area'].lower()}: {item['description']}",
            item["severity"],
            item["area"],
            "Confirm the missing detail before planning.",
            0.6,
        )
    deadline = payload.get("assignment", {}).get("deadline")
    if isinstance(deadline, str) and deadline:
        add(
            "A deadline is set; reviewing the submission at the last moment is a risk.",
            FindingSeverity.INFO.value,
            "PROCESS",
            "Reserve time to review every requirement against the finished work.",
            0.5,
        )
    if len(requirements) >= 8:
        add(
            f"{len(requirements)} independent requirements increase the chance one is missed.",
            FindingSeverity.WARNING.value,
            "SCOPE",
            "Track each requirement explicitly and check coverage at the end.",
            0.6,
        )
    return risks[:10]


def analyze(payload: dict[str, Any], *, include_questions: bool = True) -> dict[str, Any]:
    """Produce an ``AnalyzerOutput``-shaped dict from an analyzer input."""
    types, domains = classify(payload)
    requirements = normalize_requirements(payload)
    deliverables = build_deliverables(payload, requirements, types)
    ambiguities = detect_ambiguities(payload, requirements)
    contradictions = detect_contradictions(payload)
    missing_information = detect_missing_information(payload, types)
    assumptions = detect_assumptions(payload, types)
    work_areas = build_work_areas(payload, types, requirements)
    dependencies = build_dependencies(work_areas, deliverables)
    questions = build_questions(
        ambiguities, contradictions, missing_information, include_questions=include_questions
    )
    verification = build_verification(types)
    risks = build_risks(ambiguities, contradictions, missing_information, payload, requirements)
    overall_confidence = round(
        sum(float(item["confidence"]) for item in types) / max(1, len(types)), 2
    )
    return {
        "assignment_types": types,
        "academic_domains": domains,
        "summary": build_summary(payload, types, domains),
        "objectives": build_objectives(types, requirements),
        "normalized_requirements": requirements,
        "ambiguities": ambiguities,
        "contradictions": contradictions,
        "missing_information": missing_information,
        "assumptions": assumptions,
        "clarification_questions": questions,
        "deliverables": deliverables,
        "evaluation": build_evaluation(payload, requirements, types),
        "scope": build_scope(payload, types, requirements, deliverables, dependencies),
        "work_areas": work_areas,
        "resources": build_resources(payload),
        "dependencies": dependencies,
        "verification": verification,
        "risks": risks,
        "confidence": overall_confidence,
    }
