"""Assignment endpoints: listing, CRUD, readiness and deletion."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_workspace
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Assignment, User, Workspace
from app.models.enums import AssignmentStatus, AuditEventType, NotificationType
from app.modules.assignments.lifecycle import (
    ensure_client_settable,
    ensure_transition_allowed,
)
from app.modules.assignments.readiness import analyze_assignment
from app.modules.assignments.service import (
    assignment_list_item,
    assignment_response,
    get_course_in_workspace,
    list_assignments,
    load_owned_assignment,
    record_specification_change,
)
from app.schemas.assignments import (
    AssignmentCreate,
    AssignmentListItem,
    AssignmentListParams,
    AssignmentResponse,
    AssignmentUpdate,
)
from app.schemas.common import Page, PageResponse
from app.services.notifications import create_notification
from app.storage import get_storage

router = APIRouter(prefix="/api/v1/assignments", tags=["Assignments"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]

MUTABLE_FIELDS = ("title", "description", "deadline", "course_id")


@router.get(
    "",
    response_model=PageResponse[AssignmentListItem],
    summary="List assignments with filtering, sorting and pagination",
    description=(
        "Returns one page of assignments for the current workspace. Filtering happens in the "
        "database: `course_id`, `status`, `readiness`, `tag`, `deadline_after`, `deadline_before` "
        "and `search` (title, description, course name, course code and tags). Sorting accepts "
        "`deadline`, `created_at`, `updated_at`, `title` and `readiness_score`."
    ),
)
async def list_assignments_endpoint(
    params: Annotated[AssignmentListParams, Query()],
    workspace: CurrentWorkspace,
    db: Db,
) -> PageResponse[AssignmentListItem]:
    assignments, total = await list_assignments(params, workspace.id, db)
    return PageResponse[AssignmentListItem](
        items=[assignment_list_item(assignment) for assignment in assignments],
        page=Page(
            page=params.page,
            page_size=params.page_size,
            total=total,
            pages=max(1, -(-total // params.page_size)),
        ),
    )


@router.post(
    "",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an assignment draft",
)
async def create_assignment(
    payload: AssignmentCreate,
    workspace: CurrentWorkspace,
    user: CurrentUser,
    db: Db,
) -> AssignmentResponse:
    course = await get_course_in_workspace(payload.course_id, workspace.id, db)
    assignment = Assignment(
        workspace_id=workspace.id,
        course_id=course.id,
        title=payload.title.strip(),
        description=payload.description,
        deadline=payload.deadline,
        status=payload.status.value,
    )
    db.add(assignment)
    await db.flush()
    # Reload with the specification loaders so the first readiness report and
    # the version snapshot see the real state instead of triggering lazy loads.
    assignment = await load_owned_assignment(assignment.id, user.id, db)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.ASSIGNMENT_CREATED,
        entity_type="Assignment",
        entity_id=assignment.id,
        change_summary=f"Created assignment {assignment.title}",
    )
    await db.commit()
    return assignment_response(await load_owned_assignment(assignment.id, user.id, db))


@router.get("/{assignment_id}", response_model=AssignmentResponse, summary="Get an assignment")
async def get_assignment(assignment_id: UUID, user: CurrentUser, db: Db) -> AssignmentResponse:
    return assignment_response(await load_owned_assignment(assignment_id, user.id, db))


@router.patch(
    "/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Update an assignment",
    description=(
        "Editable while the specification is being built. Changing information that the "
        "readiness gate depends on automatically moves a ready assignment back to INCOMPLETE."
    ),
)
async def update_assignment(
    assignment_id: UUID,
    payload: AssignmentUpdate,
    user: CurrentUser,
    workspace: CurrentWorkspace,
    db: Db,
) -> AssignmentResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    changes = payload.model_dump(exclude_unset=True)
    changed = sorted(changes)

    if "status" in changes and changes["status"] is not None:
        target = changes["status"]
        ensure_client_settable(target)
        ensure_transition_allowed(AssignmentStatus(assignment.status), target)
        assignment.status = target.value
        changed.remove("status")
        changed.append("status")

    if changes.get("course_id") is not None:
        course = await get_course_in_workspace(changes["course_id"], workspace.id, db)
        assignment.course_id = course.id
    if changes.get("title") is not None:
        assignment.title = str(changes["title"]).strip()
    if "description" in changes:
        assignment.description = changes["description"]
    if "deadline" in changes:
        assignment.deadline = _as_utc(changes["deadline"])

    if not changed:
        return assignment_response(assignment)

    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.ASSIGNMENT_UPDATED,
        entity_type="Assignment",
        entity_id=assignment.id,
        change_summary=f"Updated {', '.join(changed)}",
        metadata={"fields": changed},
    )
    await db.commit()
    return assignment_response(await load_owned_assignment(assignment.id, user.id, db))


@router.post(
    "/{assignment_id}/readiness/mark-ready",
    response_model=AssignmentResponse,
    summary="Mark an assignment ready for analysis",
    description=(
        "Runs the deterministic completeness gate. Refuses to mark an assignment ready when a "
        "blocking check fails; the response lists exactly which checks failed."
    ),
)
async def mark_ready(assignment_id: UUID, user: CurrentUser, db: Db) -> AssignmentResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    current = AssignmentStatus(assignment.status)
    ensure_transition_allowed(current, AssignmentStatus.READY_FOR_ANALYSIS)

    report = analyze_assignment(assignment)
    if not report.is_ready_for_analysis:
        raise AppError(
            422,
            "ASSIGNMENT_NOT_READY",
            "The assignment cannot be marked ready because "
            + _first_failure(report.failing_checks),
            {
                "failing_checks": report.failing_checks,
                "warning_checks": report.warning_checks,
                "score": report.score,
            },
        )

    assignment.status = AssignmentStatus.READY_FOR_ANALYSIS.value
    assignment.ready_for_analysis_at = datetime.now(UTC)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.SPECIFICATION_MARKED_READY,
        entity_type="Assignment",
        entity_id=assignment.id,
        change_summary="Marked ready for analysis",
        metadata={"score": report.score},
    )
    await create_notification(
        db,
        user_id=user.id,
        notification_type=NotificationType.SYSTEM,
        title="Assignment ready for analysis",
        message=f"{assignment.title} passed every readiness check.",
    )
    await db.commit()
    return assignment_response(await load_owned_assignment(assignment.id, user.id, db))


@router.post(
    "/{assignment_id}/readiness/mark-incomplete",
    response_model=AssignmentResponse,
    summary="Move an assignment back to INCOMPLETE",
    description="Re-opens a ready assignment for editing without deleting anything.",
)
async def mark_incomplete(assignment_id: UUID, user: CurrentUser, db: Db) -> AssignmentResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    ensure_transition_allowed(AssignmentStatus(assignment.status), AssignmentStatus.INCOMPLETE)
    assignment.status = AssignmentStatus.INCOMPLETE.value
    assignment.ready_for_analysis_at = None
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.ASSIGNMENT_UPDATED,
        entity_type="Assignment",
        entity_id=assignment.id,
        change_summary="Re-opened for editing",
        metadata={"status": AssignmentStatus.INCOMPLETE.value},
    )
    await db.commit()
    return assignment_response(await load_owned_assignment(assignment.id, user.id, db))


@router.post(
    "/{assignment_id}/finalize",
    response_model=AssignmentResponse,
    summary="Finalize an assignment (deprecated alias)",
    description=(
        "Phase 1 endpoint, kept so existing clients keep working. It now marks the assignment "
        "READY_FOR_ANALYSIS. Prefer POST /readiness/mark-ready."
    ),
    deprecated=True,
)
async def finalize_assignment(assignment_id: UUID, user: CurrentUser, db: Db) -> AssignmentResponse:
    return await mark_ready(assignment_id, user, db)


@router.delete(
    "/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an assignment"
)
async def delete_assignment(assignment_id: UUID, user: CurrentUser, db: Db) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    storage = get_storage()
    for document in assignment.documents:
        storage.delete(document.storage_key)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.ASSIGNMENT_DELETED,
        entity_type="Assignment",
        entity_id=assignment.id,
        change_summary="Deleted assignment",
        version=False,
    )
    await db.delete(assignment)
    await db.commit()


def _first_failure(failing: list[str]) -> str:
    if not failing:
        return "a required part of the specification is missing."
    listed = ", ".join(failing[:-1])
    if len(failing) == 1:
        return f"{failing[0]} is not satisfied."
    return f"{listed} and {failing[-1]} are not satisfied."


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
