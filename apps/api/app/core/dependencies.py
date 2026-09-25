from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Assignment, Course, Document, User, Workspace, WorkspaceMember

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    raw_token = token or request.cookies.get(settings.cookie_name)
    if not raw_token:
        raise AppError(
            401,
            "AUTHENTICATION_REQUIRED",
            "Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(raw_token)
    user = await db.get(User, user_id)
    if user is None:
        raise AppError(401, "INVALID_TOKEN", "The authentication token is invalid.")
    return user


async def get_current_workspace(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Workspace:
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at.asc())
        .limit(1)
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise AppError(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    return workspace


async def get_owned_course(course_id: UUID, user: User, db: AsyncSession) -> Course:
    result = await db.execute(
        select(Course)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Course.workspace_id)
        .where(Course.id == course_id, WorkspaceMember.user_id == user.id)
    )
    course = result.scalar_one_or_none()
    if course is None:
        raise AppError(404, "COURSE_NOT_FOUND", "Course not found.")
    return course


async def get_owned_document(document_id: UUID, user: User, db: AsyncSession) -> Document:
    result = await db.execute(
        select(Document)
        .join(Assignment, Document.assignment_id == Assignment.id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Assignment.workspace_id)
        .where(Document.id == document_id, WorkspaceMember.user_id == user.id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise AppError(404, "DOCUMENT_NOT_FOUND", "Document not found.")
    return document
