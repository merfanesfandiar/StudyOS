"""Technologies and tags.

Both are workspace-scoped catalogues: a technology is identified by its
normalised name, version and category, a tag only by its normalised name. Adding
one to an assignment therefore doubles as "create if it does not exist yet",
which keeps the editor free of a second admin screen while still never leaking a
catalogue entry between workspaces.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_current_workspace
from app.core.errors import AppError
from app.db.session import get_db
from app.models import (
    AssignmentTag,
    AssignmentTechnology,
    Tag,
    Technology,
    User,
    Workspace,
)
from app.models.enums import AuditEventType
from app.modules.assignments.service import (
    load_owned_assignment,
    record_specification_change,
)
from app.modules.assignments.specification import tag_response, technology_response
from app.modules.assignments.validation import normalize_key
from app.schemas.assignments import (
    TagCreate,
    TagResponse,
    TechnologyCreate,
    TechnologyResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Specification"])

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


# --- technologies ----------------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/technologies",
    response_model=list[TechnologyResponse],
    summary="List the technologies available in the workspace",
)
async def list_workspace_technologies(
    workspace_id: UUID, workspace: CurrentWorkspace, db: Db
) -> list[TechnologyResponse]:
    _ensure_workspace(workspace_id, workspace)
    technologies = (
        await db.scalars(
            select(Technology)
            .where(Technology.workspace_id == workspace.id)
            .order_by(Technology.name, Technology.version)
        )
    ).all()
    return [
        TechnologyResponse(
            id=item.id,
            workspace_id=item.workspace_id,
            name=item.name,
            version=item.version or None,
            category=item.category,
            created_at=item.created_at,
        )
        for item in technologies
    ]


@router.get(
    "/assignments/{assignment_id}/technologies",
    response_model=list[TechnologyResponse],
    summary="List the technologies used by the assignment",
)
async def list_assignment_technologies(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> list[TechnologyResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [technology_response(link) for link in assignment.technologies]


@router.post(
    "/assignments/{assignment_id}/technologies",
    response_model=TechnologyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a technology, creating the catalogue entry when needed",
)
async def add_technology(
    assignment_id: UUID, payload: TechnologyCreate, user: CurrentUser, db: Db
) -> TechnologyResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    normalized = normalize_key(payload.name)
    version = (payload.version or "").strip()
    technology = await db.scalar(
        select(Technology).where(
            Technology.workspace_id == assignment.workspace_id,
            Technology.normalized_name == normalized,
            Technology.version == version,
        )
    )
    if technology is None:
        technology = Technology(
            workspace_id=assignment.workspace_id,
            name=payload.name.strip(),
            normalized_name=normalized,
            version=version,
            category=payload.category.value,
        )
        db.add(technology)
        try:
            # Savepoint, not rollback: a concurrent request creating the same
            # catalogue entry must not undo the rest of this request.
            async with db.begin_nested():
                await db.flush()
        except IntegrityError as error:
            db.expunge(technology)
            technology = await db.scalar(
                select(Technology).where(
                    Technology.workspace_id == assignment.workspace_id,
                    Technology.normalized_name == normalized,
                    Technology.version == version,
                )
            )
            if technology is None:
                raise AppError(
                    409,
                    "TECHNOLOGY_CONFLICT",
                    "That technology is being created by someone else. Please retry.",
                ) from error
    existing = await db.scalar(
        select(AssignmentTechnology.assignment_id).where(
            AssignmentTechnology.assignment_id == assignment.id,
            AssignmentTechnology.technology_id == technology.id,
        )
    )
    if existing is not None:
        raise AppError(
            409,
            "TECHNOLOGY_ALREADY_LINKED",
            f"{technology.name} is already linked to this assignment.",
            {"technology_id": str(technology.id)},
        )
    link = AssignmentTechnology(assignment=assignment, technology_id=technology.id)
    db.add(link)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.TECHNOLOGY_ADDED,
        entity_type="AssignmentTechnology",
        entity_id=technology.id,
        change_summary=f"Added technology {technology.name} {technology.version}".strip(),
        metadata={"technology_id": str(technology.id), "category": technology.category},
    )
    await db.commit()
    return technology_response(link)


@router.delete(
    "/assignments/{assignment_id}/technologies/{technology_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a technology from the assignment",
    description="The workspace catalogue entry itself is kept for reuse by other assignments.",
)
async def remove_technology(
    assignment_id: UUID, technology_id: UUID, user: CurrentUser, db: Db
) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    link = await db.scalar(
        select(AssignmentTechnology).where(
            AssignmentTechnology.assignment_id == assignment.id,
            AssignmentTechnology.technology_id == technology_id,
        )
    )
    if link is None:
        raise AppError(
            404, "TECHNOLOGY_NOT_FOUND", "Technology is not attached to this assignment."
        )
    name = link.technology.name
    version = link.technology.version
    assignment.technologies.remove(link)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.TECHNOLOGY_REMOVED,
        entity_type="AssignmentTechnology",
        entity_id=technology_id,
        change_summary=f"Removed technology {name} {version}".strip(),
    )
    await db.commit()


# --- tags ------------------------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/tags",
    response_model=list[TagResponse],
    summary="List the tags available in the workspace",
)
async def list_workspace_tags(
    workspace_id: UUID, workspace: CurrentWorkspace, db: Db
) -> list[TagResponse]:
    _ensure_workspace(workspace_id, workspace)
    tags = (
        await db.scalars(select(Tag).where(Tag.workspace_id == workspace.id).order_by(Tag.name))
    ).all()
    return [
        TagResponse(
            id=item.id,
            workspace_id=item.workspace_id,
            name=item.name,
            created_at=item.created_at,
        )
        for item in tags
    ]


@router.get(
    "/assignments/{assignment_id}/tags",
    response_model=list[TagResponse],
    summary="List the tags of the assignment",
)
async def list_assignment_tags(assignment_id: UUID, user: CurrentUser, db: Db) -> list[TagResponse]:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    return [tag_response(link) for link in assignment.tags]


@router.post(
    "/assignments/{assignment_id}/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a tag, creating the catalogue entry when needed",
)
async def add_tag(
    assignment_id: UUID, payload: TagCreate, user: CurrentUser, db: Db
) -> TagResponse:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    normalized = normalize_key(payload.name)
    tag = await db.scalar(
        select(Tag).where(
            Tag.workspace_id == assignment.workspace_id,
            Tag.normalized_name == normalized,
        )
    )
    if tag is None:
        tag = Tag(
            workspace_id=assignment.workspace_id,
            name=payload.name.strip(),
            normalized_name=normalized,
        )
        db.add(tag)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError as error:
            db.expunge(tag)
            tag = await db.scalar(
                select(Tag).where(
                    Tag.workspace_id == assignment.workspace_id,
                    Tag.normalized_name == normalized,
                )
            )
            if tag is None:
                raise AppError(
                    409,
                    "TAG_CONFLICT",
                    "That tag is being created by someone else. Please retry.",
                ) from error
    existing = await db.scalar(
        select(AssignmentTag.assignment_id).where(
            AssignmentTag.assignment_id == assignment.id,
            AssignmentTag.tag_id == tag.id,
        )
    )
    if existing is not None:
        raise AppError(
            409,
            "TAG_ALREADY_LINKED",
            f"{tag.name} is already linked to this assignment.",
            {"tag_id": str(tag.id)},
        )
    link = AssignmentTag(assignment=assignment, tag_id=tag.id)
    db.add(link)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.TAG_ADDED,
        entity_type="AssignmentTag",
        entity_id=tag.id,
        change_summary=f"Added tag {tag.name}",
        metadata={"tag_id": str(tag.id)},
    )
    await db.commit()
    return tag_response(link)


@router.delete(
    "/assignments/{assignment_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a tag from the assignment",
)
async def remove_tag(assignment_id: UUID, tag_id: UUID, user: CurrentUser, db: Db) -> None:
    assignment = await load_owned_assignment(assignment_id, user.id, db)
    link = await db.scalar(
        select(AssignmentTag).where(
            AssignmentTag.assignment_id == assignment.id,
            AssignmentTag.tag_id == tag_id,
        )
    )
    if link is None:
        raise AppError(404, "TAG_NOT_FOUND", "Tag is not attached to this assignment.")
    name = link.tag.name
    assignment.tags.remove(link)
    await record_specification_change(
        db,
        assignment=assignment,
        user_id=user.id,
        event_type=AuditEventType.TAG_REMOVED,
        entity_type="AssignmentTag",
        entity_id=tag_id,
        change_summary=f"Removed tag {name}",
    )
    await db.commit()


@router.get(
    "/assignments/{assignment_id}/summary",
    summary="Compact summary of the assignment",
    description=(
        "Small payload for dashboards and list rows: counts, criteria total, technologies, tags "
        "and the current readiness verdict without sending the whole specification."
    ),
)
async def assignment_summary_endpoint(
    assignment_id: UUID, user: CurrentUser, db: Db
) -> dict[str, object]:
    from app.modules.assignments.readiness import analyze_assignment
    from app.modules.assignments.specification import build_summary
    from app.modules.assignments.versioning import current_version

    assignment = await load_owned_assignment(assignment_id, user.id, db)
    report = analyze_assignment(assignment)
    version = await current_version(assignment.id, db)
    return build_summary(assignment, report, version).model_dump(mode="json")


def _ensure_workspace(requested: UUID, workspace: Workspace) -> None:
    if requested != workspace.id:
        raise AppError(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
