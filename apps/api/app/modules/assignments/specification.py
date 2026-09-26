"""Assembly of the assignment specification.

This module turns a loaded assignment graph into the three shapes the product
needs: the full specification (the future AI contract), a compact summary for
dashards and cards, and the requirement dependency graph. All of it is
deterministic and derived, never stored twice.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.models import (
    Assignment,
    AssignmentConstraint,
    AssignmentRequirement,
    AssignmentTag,
    AssignmentTechnology,
    Deliverable,
    Document,
    EvaluationCriterion,
    RequirementDependency,
)
from app.models.enums import (
    AssignmentStatus,
    DeliverableStatus,
    RequirementPriority,
    RequirementStatus,
    TechnologyCategory,
)
from app.models.identifiers import requirement_code
from app.modules.assignments.readiness import requirement_progress
from app.modules.assignments.requirements import (
    dependency_graph,
    execution_order,
    max_depth,
)
from app.modules.assignments.validation import criteria_total
from app.schemas.assignments import (
    AssignmentSummary,
    ConstraintResponse,
    CriterionResponse,
    DeliverableResponse,
    DependencyResponse,
    RequirementResponse,
    TagResponse,
    TechnologyResponse,
)
from app.schemas.documents import DocumentResponse
from app.schemas.specification import (
    AssignmentSpecificationResponse,
    DependencyEdge,
    DependencyGraph,
    DependencyNode,
    ReadinessReport,
    SpecificationSummary,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def requirement_response(requirement: AssignmentRequirement) -> RequirementResponse:
    return RequirementResponse(
        id=requirement.id,
        assignment_id=requirement.assignment_id,
        code=requirement_code(requirement.sequence),
        sequence=requirement.sequence,
        title=requirement.title,
        description=requirement.description,
        priority=RequirementPriority(requirement.priority),
        type=requirement.type,
        status=RequirementStatus(requirement.status),
        is_required=requirement.is_required,
        position=requirement.position,
        parent_id=requirement.parent_id,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


def constraint_response(constraint: AssignmentConstraint) -> ConstraintResponse:
    return ConstraintResponse.model_validate(constraint)


def criterion_response(criterion: EvaluationCriterion) -> CriterionResponse:
    return CriterionResponse.model_validate(criterion)


def deliverable_response(deliverable: Deliverable) -> DeliverableResponse:
    return DeliverableResponse.model_validate(deliverable)


def technology_response(link: AssignmentTechnology) -> TechnologyResponse:
    technology = link.technology
    return TechnologyResponse(
        id=technology.id,
        workspace_id=technology.workspace_id,
        name=technology.name,
        version=technology.version or None,
        category=TechnologyCategory(technology.category),
        created_at=technology.created_at,
    )


def tag_response(link: AssignmentTag) -> TagResponse:
    return TagResponse.model_validate(link.tag)


def document_response(document: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(document)


def dependency_response(
    dependency: RequirementDependency, codes: dict[UUID, str], titles: dict[UUID, str]
) -> DependencyResponse:
    return DependencyResponse(
        id=dependency.id,
        requirement_id=dependency.requirement_id,
        depends_on_id=dependency.depends_on_id,
        depends_on_code=codes.get(dependency.depends_on_id, ""),
        depends_on_title=titles.get(dependency.depends_on_id, ""),
        note=dependency.note,
        created_at=dependency.created_at,
    )


def assignment_summary(assignment: Assignment) -> AssignmentSummary:
    return AssignmentSummary(
        id=assignment.id,
        title=assignment.title,
        deadline=_utc(assignment.deadline),
        status=AssignmentStatus(assignment.status),
        course_id=assignment.course_id,
        course_name=assignment.course.name,
        course_code=assignment.course.code,
    )


def _sorted_counts(pairs: dict[str, int]) -> dict[str, int]:
    return {key: pairs[key] for key in sorted(pairs)}


def build_summary(
    assignment: Assignment, report: ReadinessReport, version: int
) -> SpecificationSummary:
    """Build the deterministic system summary. Not AI-generated prose."""
    requirements = assignment.requirements
    by_status: dict[str, int] = {}
    for requirement in requirements:
        by_status[requirement.status] = by_status.get(requirement.status, 0) + 1
    by_severity: dict[str, int] = {}
    for constraint in assignment.constraints:
        by_severity[constraint.severity] = by_severity.get(constraint.severity, 0) + 1

    total = criteria_total(assignment.criteria)
    completed, _ = requirement_progress(requirements)
    return SpecificationSummary(
        assignment=assignment_summary(assignment),
        requirements_total=len(requirements),
        requirements_required=sum(1 for item in requirements if item.is_required),
        requirements_completed=completed,
        requirements_verified=sum(
            1 for item in requirements if item.status == RequirementStatus.VERIFIED
        ),
        requirements_by_status=_sorted_counts(by_status),
        critical_requirements=sum(
            1 for item in requirements if item.priority == RequirementPriority.CRITICAL
        ),
        constraints_total=len(assignment.constraints),
        constraints_by_severity=_sorted_counts(by_severity),
        criteria_total=total,
        criteria_count=len(assignment.criteria),
        criteria_balanced=total == Decimal("100.00"),
        deliverables_total=len(assignment.deliverables),
        deliverables_completed=sum(
            1
            for item in assignment.deliverables
            if item.status in {DeliverableStatus.COMPLETED, DeliverableStatus.VERIFIED}
        ),
        technologies=[
            " ".join(filter(None, [link.technology.name, link.technology.version]))
            for link in sorted(
                assignment.technologies,
                key=lambda link: (link.technology.name.lower(), link.technology.version),
            )
        ],
        tags=sorted(link.tag.name for link in assignment.tags),
        resources_total=len(assignment.documents),
        readiness=AssignmentStatus(assignment.status),
        readiness_score=report.score,
        specification_version=version,
    )


def build_specification(
    assignment: Assignment, report: ReadinessReport, version: int
) -> AssignmentSpecificationResponse:
    return AssignmentSpecificationResponse(
        assignment=assignment_summary(assignment),
        description=assignment.description,
        criteria_total=criteria_total(assignment.criteria),
        requirements=[requirement_response(item) for item in assignment.requirements],
        constraints=[constraint_response(item) for item in assignment.constraints],
        evaluation_criteria=[criterion_response(item) for item in assignment.criteria],
        deliverables=[deliverable_response(item) for item in assignment.deliverables],
        technologies=[technology_response(link) for link in assignment.technologies],
        tags=[tag_response(link) for link in assignment.tags],
        resources=[document_response(item) for item in assignment.documents],
        readiness=report,
        summary=build_summary(assignment, report, version),
        specification_version=version,
        updated_at=_utc(assignment.updated_at) or datetime.now(UTC),
    )


def build_dependency_graph(requirements: Sequence[AssignmentRequirement]) -> DependencyGraph:
    """Return the acyclic dependency graph with a safe execution order."""
    graph = dependency_graph(requirements)
    depths = max_depth(graph)
    codes = {item.id: requirement_code(item.sequence) for item in requirements}
    rank = {item.id: item.sequence for item in requirements}
    nodes = [
        DependencyNode(
            id=item.id,
            code=requirement_code(item.sequence),
            title=item.title,
            status=RequirementStatus(item.status),
            priority=item.priority,
            depth=depths.get(item.id, 0),
        )
        for item in sorted(requirements, key=lambda value: value.sequence)
    ]
    edges = [
        DependencyEdge(
            requirement_id=item.id,
            requirement_code=requirement_code(item.sequence),
            depends_on_id=dependency.depends_on_id,
            depends_on_code=codes.get(dependency.depends_on_id, ""),
        )
        for item in sorted(requirements, key=lambda value: value.sequence)
        for dependency in sorted(item.dependencies, key=lambda value: str(value.depends_on_id))
    ]
    return DependencyGraph(
        nodes=nodes,
        edges=edges,
        execution_order=[codes[node] for node in execution_order(graph, rank) if node in codes],
        has_cycles=False,
    )


def specification_snapshot(
    assignment: Assignment, report: ReadinessReport, version: int
) -> dict[str, Any]:
    """Serialisable copy of the specification, stored in version history.

    The snapshot deliberately reuses the response shapes so history and the live
    specification cannot drift apart in meaning.
    """
    return build_specification(assignment, report, version).model_dump(mode="json")
