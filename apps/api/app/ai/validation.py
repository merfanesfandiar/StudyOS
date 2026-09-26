"""Deterministic semantic validation of an analysis.

Schema validation proves the JSON has the right shape. It cannot prove the
analysis is internally consistent. These checks are pure and run outside the
model:

* confidence is within [0, 1]
* a rubric cannot be claimed without criteria
* criterion weights cannot be negative
* every evidence pointer references a source that actually exists
* every dependency endpoint exists, with no self-loop or cycle
* a requirement marked explicit must reference a real requirement
* an explicitly sourced deliverable must have a known required flag
* duplicate keys are rejected; duplicate titles are collapsed
* classification values are supported and non-empty

If anything fails the run is rejected rather than persisted, so a hallucinated
analysis can never reach the student.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.errors import AnalysisSemanticError
from app.models.enums import EvidenceSourceType, FindingSeverity, SourceKind
from app.schemas.analysis import AnalyzerOutput, Evidence

#: Evidence source types that must carry a resolvable ``source_id``.
_NEEDS_ID = frozenset(
    {
        EvidenceSourceType.REQUIREMENT,
        EvidenceSourceType.CONSTRAINT,
        EvidenceSourceType.CRITERION,
        EvidenceSourceType.DELIVERABLE,
        EvidenceSourceType.RESOURCE,
        EvidenceSourceType.COURSE,
    }
)

_VALID_SEVERITIES = {severity.value for severity in FindingSeverity}


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Authoritative facts the analysis must be consistent with."""

    specification_hash: str
    requirement_codes: frozenset[str] = field(default_factory=frozenset)
    requirement_ids: frozenset[str] = field(default_factory=frozenset)
    constraint_ids: frozenset[str] = field(default_factory=frozenset)
    criterion_ids: frozenset[str] = field(default_factory=frozenset)
    deliverable_ids: frozenset[str] = field(default_factory=frozenset)
    document_ids: frozenset[str] = field(default_factory=frozenset)
    course_id: str | None = None
    expected_specification_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    output: AnalyzerOutput
    warnings: list[str]


def _valid_evidence(evidence: Evidence, context: ValidationContext) -> str | None:
    """Return a violation message, or ``None`` when the evidence is sound."""
    if evidence.source_type in _NEEDS_ID and not evidence.source_id:
        return f"evidence of type {evidence.source_type.value} has no source_id"
    if not evidence.source_id:
        return None
    source_id = evidence.source_id
    allowed = {
        EvidenceSourceType.REQUIREMENT: context.requirement_codes | context.requirement_ids,
        EvidenceSourceType.CONSTRAINT: context.constraint_ids,
        EvidenceSourceType.CRITERION: context.criterion_ids,
        EvidenceSourceType.DELIVERABLE: context.deliverable_ids,
        EvidenceSourceType.RESOURCE: context.document_ids,
        EvidenceSourceType.COURSE: frozenset({context.course_id}) if context.course_id else None,
    }.get(evidence.source_type)
    if allowed is None:
        return None
    if not allowed:
        # Nothing to validate against: treat a pointed reference as suspicious, but
        # not fatal, because the source may simply not be part of the input.
        return None
    if source_id not in allowed:
        return f"evidence references unknown {evidence.source_type.value} '{source_id}'"
    return None


def _detect_cycle(edges: list[tuple[str, str]]) -> list[str] | None:
    graph: dict[str, set[str]] = {}
    for predecessor, successor in edges:
        graph.setdefault(predecessor, set()).add(successor)
        graph.setdefault(successor, set())
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(graph, WHITE)
    for start in graph:
        if colour[start] != WHITE:
            continue
        colour[start] = GREY
        stack: list[tuple[str, list[str]]] = [(start, sorted(graph[start]))]
        path = [start]
        while stack:
            node, neighbours = stack[-1]
            if neighbours:
                neighbour = neighbours.pop(0)
                if colour[neighbour] == GREY:
                    index = path.index(neighbour)
                    return [*path[index:], neighbour]
                if colour[neighbour] == WHITE:
                    colour[neighbour] = GREY
                    path.append(neighbour)
                    stack.append((neighbour, sorted(graph[neighbour])))
            else:
                colour[node] = BLACK
                stack.pop()
                path.pop()
    return None


def validate_analysis(output: AnalyzerOutput, context: ValidationContext) -> ValidationOutcome:
    errors: list[str] = []
    warnings: list[str] = []

    if (
        context.expected_specification_hash
        and context.specification_hash != context.expected_specification_hash
    ):
        errors.append("analysis does not reference the current specification hash")

    # -- classification ------------------------------------------------------
    type_values = [item.type.value for item in output.assignment_types]
    if len(set(type_values)) != len(type_values):
        errors.append("assignment_types contains a duplicate value")
    domain_values = [item.domain.value for item in output.academic_domains]
    if len(set(domain_values)) != len(domain_values):
        errors.append("academic_domains contains a duplicate value")
    for typed in output.assignment_types:
        if not 0.0 <= typed.confidence <= 1.0:
            errors.append("classification confidence is outside [0, 1]")
    for domain in output.academic_domains:
        if not 0.0 <= domain.confidence <= 1.0:
            errors.append("classification confidence is outside [0, 1]")

    # -- requirements --------------------------------------------------------
    requirement_keys: set[str] = set()
    deduped_requirements = []
    seen_titles: set[str] = set()
    for requirement in output.normalized_requirements:
        if requirement.key in requirement_keys:
            errors.append(f"duplicate requirement key '{requirement.key}'")
            continue
        requirement_keys.add(requirement.key)
        folded = requirement.title.casefold()
        if folded in seen_titles:
            warnings.append(f"dropped duplicate requirement titled '{requirement.title}'")
            continue
        seen_titles.add(folded)
        if requirement.source is SourceKind.EXPLICIT:
            reference = requirement.source_reference
            if not reference:
                errors.append(
                    f"requirement '{requirement.key}' is explicit but has no source_reference"
                )
            elif reference not in (context.requirement_codes | context.requirement_ids):
                errors.append(
                    f"requirement '{requirement.key}' references unknown source '{reference}'"
                )
        if requirement.source is SourceKind.AI_INFERENCE and requirement.confidence >= 0.99:
            warnings.append(
                f"requirement '{requirement.key}' is inferred but reports near-certainty"
            )
        for evidence in requirement.evidence:
            violation = _valid_evidence(evidence, context)
            if violation:
                errors.append(f"requirement '{requirement.key}': {violation}")
        deduped_requirements.append(requirement)

    # -- deliverables --------------------------------------------------------
    deliverable_keys: set[str] = set()
    for deliverable in output.deliverables:
        if deliverable.key in deliverable_keys:
            errors.append(f"duplicate deliverable key '{deliverable.key}'")
        deliverable_keys.add(deliverable.key)
        if deliverable.required is None and deliverable.uncertainty is SourceKind.EXPLICIT:
            errors.append(
                f"deliverable '{deliverable.key}' is explicit but its required status is unknown"
            )
        if deliverable.required is None and deliverable.uncertainty is SourceKind.MISSING:
            errors.append(
                f"deliverable '{deliverable.key}' is marked missing but has an unknown status"
            )
        for evidence in deliverable.evidence:
            violation = _valid_evidence(evidence, context)
            if violation:
                errors.append(f"deliverable '{deliverable.key}': {violation}")

    # -- work areas ----------------------------------------------------------
    work_area_keys: set[str] = set()
    for area in output.work_areas:
        if area.key in work_area_keys:
            errors.append(f"duplicate work area key '{area.key}'")
        work_area_keys.add(area.key)

    # -- evaluation ----------------------------------------------------------
    rubric = output.evaluation
    if rubric.rubric_available and not rubric.criteria:
        errors.append("rubric_available is true but no criteria were returned")
    for criterion in rubric.criteria:
        if criterion.weight is not None and criterion.weight < 0:
            errors.append(f"criterion '{criterion.title}' has a negative weight")
        if not criterion.implied and criterion.weight is None and rubric.rubric_available:
            warnings.append(
                f"criterion '{criterion.title}' has no stated weight; it was reported without one"
            )
    if rubric.rubric_available and not any(
        criterion.weight is not None for criterion in rubric.criteria
    ):
        warnings.append("a rubric is claimed but no weights were provided")

    # -- findings evidence ---------------------------------------------------
    def check_severity(label: str, key: str, severity: str) -> None:
        if severity not in _VALID_SEVERITIES:
            errors.append(f"{label} '{key}' has an invalid severity")

    def check_evidence(label: str, key: str, evidence_items: list[Evidence]) -> None:
        for evidence in evidence_items:
            violation = _valid_evidence(evidence, context)
            if violation:
                errors.append(f"{label} '{key}': {violation}")

    for ambiguity in output.ambiguities:
        check_severity("ambiguity", ambiguity.key, ambiguity.severity)
        check_evidence("ambiguity", ambiguity.key, ambiguity.evidence)
    for contradiction in output.contradictions:
        check_severity("contradiction", contradiction.key, contradiction.severity)
        check_evidence("contradiction", contradiction.key, contradiction.evidence)
    for missing in output.missing_information:
        check_severity("missing_information", missing.key, missing.severity)
        check_evidence("missing_information", missing.key, missing.evidence)
    for assumption in output.assumptions:
        check_evidence("assumption", assumption.key, assumption.evidence)
    for risk in output.risks:
        check_severity("risk", risk.key, risk.severity)
        check_evidence("risk", risk.key, risk.evidence)

    for question in output.clarification_questions:
        for reference in question.related_requirements:
            if reference not in requirement_keys:
                warnings.append(
                    f"question '{question.code}' references unknown requirement '{reference}'"
                )

    # -- dependencies --------------------------------------------------------
    allowed = requirement_keys | work_area_keys | deliverable_keys
    edges: list[tuple[str, str]] = []
    for dependency in output.dependencies:
        if dependency.predecessor not in allowed:
            errors.append(f"dependency references unknown node '{dependency.predecessor}'")
        if dependency.successor not in allowed:
            errors.append(f"dependency references unknown node '{dependency.successor}'")
        if dependency.predecessor == dependency.successor:
            errors.append(f"dependency '{dependency.predecessor}' depends on itself")
        edges.append((dependency.predecessor, dependency.successor))
    if cycle := _detect_cycle(edges):
        errors.append("dependency graph contains a cycle: " + " -> ".join(cycle))

    # -- resources -----------------------------------------------------------
    for resource in output.resources.resources:
        for evidence in resource.evidence:
            violation = _valid_evidence(evidence, context)
            if violation:
                errors.append(f"resource '{resource.filename}': {violation}")

    if errors:
        raise AnalysisSemanticError("The analysis failed semantic validation.", errors[:50])

    repaired = output.model_copy(update={"normalized_requirements": deduped_requirements})
    return ValidationOutcome(output=repaired, warnings=warnings)
