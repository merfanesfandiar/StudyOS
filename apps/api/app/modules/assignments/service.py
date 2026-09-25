"""Assignment service: loading, querying, response mapping and change orchestration.

Routers translate HTTP into these calls. Everything that has to stay consistent
whenever a specification changes - readiness score, automatic invalidation of a
ready assignment, audit trail, version history - happens in
``record_specification_change`` so no endpoint can forget it.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import (
    Assignment,
    AssignmentRequirement,
    AssignmentTag,
    AssignmentTechnology,
    Course,
    Tag,
    WorkspaceMember,
)
from app.models.enums import AssignmentStatus, AuditEventType
from app.modules.assignments.lifecycle import READINESS_STATUS_GROUPS, ensure_transition_allowed
from app.modules.assignments.readiness import (
    analyze_assignment,
    readiness_state,
    requirement_progress,
)
from app.modules.assignments.specification import (
    assignment_summary,
    constraint_response,
    criterion_response,
    deliverable_response,
    document_response,
    requirement_response,
    tag_response,
    technology_response,
)
from app.modules.assignments.validation import criteria_total
from app.modules.assignments.versioning import create_version
from app.schemas.assignments import (
    AssignmentListItem,
    AssignmentListParams,
    AssignmentResponse,
)
from app.schemas.specification import ReadinessReport
from app.services.events import record_audit

#: Every collection the specification endpoint needs. Loaded together with
#: ``selectinload`` so the detail page is a fixed number of queries, not one per
#: child collection.
SPECIFICATION_LOADERS = (
    selectinload(Assignment.course),
    selectinload(Assignment.requirements).selectinload(AssignmentRequirement.dependencies),
    selectinload(Assignment.constraints),
    selectinload(Assignment.criteria),
    selectinload(Assignment.deliverables),
    selectinload(Assignment.documents),
    selectinload(Assignment.technologies).selectinload(AssignmentTechnology.technology),
    selectinload(Assignment.tags).selectinload(AssignmentTag.tag),
)


async def load_owned_assignment(
    assignment_id: UUID, user_id: UUID, db: AsyncSession
) -> Assignment:
    """Load an assignment only if the user is a member of its workspace.

    Returns 404 rather than 403 so ids of other users' assignments cannot be
    probed.
    """
    result = await db.execute(
        select(Assignment)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Assignment.workspace_id)
        .where(Assignment.id == assignment_id, WorkspaceMember.user_id == user_id)
        .options(*SPECIFICATION_LOADERS)
        # Refresh already-loaded collections. Requests normally get a fresh
        # session, but an expire-free long-lived session would otherwise serve
        # a stale specification.
        .execution_options(populate_existing=True)
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise AppError(404, "ASSIGNMENT_NOT_FOUND", "Assignment not found.")
    return assignment


async def get_course_in_workspace(course_id: UUID, workspace_id: UUID, db: AsyncSession) -> Course:
    course = await db.scalar(
        select(Course).where(Course.id == course_id, Course.workspace_id == workspace_id)
    )
    if course is None:
        raise AppError(404, "COURSE_NOT_FOUND", "Course not found.")
    return course


def assignment_response(assignment: Assignment) -> AssignmentResponse:
    return AssignmentResponse(
        id=assignment.id,
        workspace_id=assignment.workspace_id,
        course_id=assignment.course_id,
        course_name=assignment.course.name,
        course_code=assignment.course.code,
        title=assignment.title,
        description=assignment.description,
        deadline=assignment.deadline,
        status=AssignmentStatus(assignment.status),
        readiness_score=assignment.readiness_score,
        ready_for_analysis_at=assignment.ready_for_analysis_at,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
        requirements=[requirement_response(item) for item in assignment.requirements],
        constraints=[constraint_response(item) for item in assignment.constraints],
        criteria=[criterion_response(item) for item in assignment.criteria],
        deliverables=[deliverable_response(item) for item in assignment.deliverables],
        technologies=[technology_response(item) for item in assignment.technologies],
        tags=[tag_response(item) for item in assignment.tags],
        documents=[document_response(item) for item in assignment.documents],
        criteria_total=criteria_total(assignment.criteria),
    )


def assignment_list_item(assignment: Assignment) -> AssignmentListItem:
    """Row shape for the assignment list: no nested collections, no N+1."""
    completed, total = requirement_progress(assignment.requirements)
    return AssignmentListItem(
        id=assignment.id,
        course_id=assignment.course_id,
        course_name=assignment.course.name,
        course_code=assignment.course.code,
        title=assignment.title,
        description=assignment.description,
        deadline=assignment.deadline,
        status=AssignmentStatus(assignment.status),
        readiness_score=assignment.readiness_score,
        readiness_state=AssignmentStatus(assignment.status),
        requirements_count=total,
        completed_requirements_count=completed,
        criteria_total=criteria_total(assignment.criteria),
        deadline_state=deadline_state(assignment.deadline),
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def deadline_state(deadline: datetime | None, *, now: datetime | None = None) -> str:
    """Classify a deadline for lists and dashboards without extra queries."""
    if deadline is None:
        return "UNSET"
    moment = now or datetime.now(UTC)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    delta = deadline - moment
    if delta.total_seconds() < 0:
        return "OVERDUE"
    if delta.total_seconds() <= 7 * 24 * 3600:
        return "THIS_WEEK"
    return "UPCOMING"


def _apply_filters(
    statement: Select[Any], params: AssignmentListParams, workspace_id: UUID
) -> Select[Any]:
    statement = statement.where(Assignment.workspace_id == workspace_id)
    if params.course_id is not None:
        statement = statement.where(Assignment.course_id == params.course_id)
    if params.status is not None:
        statement = statement.where(Assignment.status == params.status.value)
    if params.readiness is not None:
        # A readiness filter asks "what state is this in", and DRAFT and
        # INCOMPLETE are both "not ready yet" from the student's point of view.
        statement = statement.where(
            Assignment.status.in_(sorted(READINESS_STATUS_GROUPS[params.readiness]))
        )
    if params.deadline_before is not None:
        statement = statement.where(
            Assignment.deadline.is_not(None), Assignment.deadline <= params.deadline_before
        )
    if params.deadline_after is not None:
        statement = statement.where(
            Assignment.deadline.is_not(None), Assignment.deadline >= params.deadline_after
        )
    if params.tag:
        statement = statement.where(
            exists(
                select(AssignmentTag.assignment_id)
                .join(Tag, Tag.id == AssignmentTag.tag_id)
                .where(
                    AssignmentTag.assignment_id == Assignment.id,
                    Tag.normalized_name == params.tag.strip().casefold(),
                )
            )
        )
    if params.search:
        pattern = f"%{params.search.strip()}%"
        statement = statement.where(
            or_(
                Assignment.title.ilike(pattern),
                Assignment.description.ilike(pattern),
                Course.name.ilike(pattern),
                Course.code.ilike(pattern),
                exists(
                    select(AssignmentTag.assignment_id)
                    .join(Tag, Tag.id == AssignmentTag.tag_id)
                    .where(AssignmentTag.assignment_id == Assignment.id, Tag.name.ilike(pattern))
                ),
            )
        )
    return statement


async def list_assignments(
    params: AssignmentListParams, workspace_id: UUID, db: AsyncSession
) -> tuple[list[Assignment], int]:
    """Filter, sort and paginate assignments in the database."""
    base = select(Assignment).join(Course, Course.id == Assignment.course_id)
    count_statement = _apply_filters(
        select(func.count(Assignment.id)).join(Course, Course.id == Assignment.course_id),
        params,
        workspace_id,
    )
    total: int = await db.scalar(count_statement) or 0
    column = {
        "deadline": Assignment.deadline,
        "created_at": Assignment.created_at,
        "updated_at": Assignment.updated_at,
        "title": Assignment.title,
        "readiness_score": Assignment.readiness_score,
    }[params.sort_by]
    ordering = column.asc() if params.sort_direction == "asc" else column.desc()
    statement = (
        _apply_filters(base, params, workspace_id)
        .options(
            selectinload(Assignment.course),
            selectinload(Assignment.requirements).selectinload(
                AssignmentRequirement.dependencies
            ),
            selectinload(Assignment.criteria),
        )
        .order_by(ordering, Assignment.id)
        .offset(params.offset)
        .limit(params.limit)
    )
    result = await db.execute(statement)
    return list(result.scalars().unique().all()), total


def ensure_status_transition(assignment: Assignment, target: AssignmentStatus) -> None:
    ensure_transition_allowed(AssignmentStatus(assignment.status), target)


async def record_specification_change(
    db: AsyncSession,
    *,
    assignment: Assignment,
    user_id: UUID,
    event_type: AuditEventType,
    entity_type: str,
    entity_id: UUID | None,
    change_summary: str,
    metadata: dict[str, Any] | None = None,
    version: bool = True,
) -> ReadinessReport:
    """Single choke point for every specification mutation.

    Call this after changing the graph and before committing. It recomputes the
    readiness score, demotes a ready assignment when the change breaks the
    readiness gate, records the audit event, and appends a version snapshot.
    """
    await db.flush()
    report = analyze_assignment(assignment)
    assignment.readiness_score = report.score

    current = AssignmentStatus(assignment.status)
    if current in {AssignmentStatus.READY_FOR_ANALYSIS, AssignmentStatus.ANALYZED} and (
        not report.is_ready_for_analysis
    ):
        assignment.status = AssignmentStatus.INCOMPLETE.value
        assignment.ready_for_analysis_at = None
        await record_audit(
            db,
            user_id=user_id,
            workspace_id=assignment.workspace_id,
            assignment_id=assignment.id,
            event_type=AuditEventType.SPECIFICATION_INVALIDATED,
            entity_type="Assignment",
            entity_id=assignment.id,
            metadata={
                "reason": "The specification no longer passes the readiness gate.",
                "failing_checks": report.failing_checks,
                "previous_status": current.value,
                "triggered_by": event_type.value,
            },
        )

    await record_audit(
        db,
        user_id=user_id,
        workspace_id=assignment.workspace_id,
        assignment_id=assignment.id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        # The summary is stored on the audit row so the activity feed reads
        # like a changelog instead of a list of event codes.
        metadata={**(metadata or {}), "change_summary": change_summary},
    )

    if version:
        await create_version(
            db,
            assignment=assignment,
            created_by_id=user_id,
            change_summary=change_summary,
            report=report,
        )
    return report


def target_status_for_report(
    assignment: Assignment, report: ReadinessReport
) -> AssignmentStatus:
    return readiness_state(report, AssignmentStatus(assignment.status))


__all__ = [
    "assignment_list_item",
    "assignment_response",
    "assignment_summary",
    "deadline_state",
    "ensure_status_transition",
    "get_course_in_workspace",
    "list_assignments",
    "load_owned_assignment",
    "record_specification_change",
]
