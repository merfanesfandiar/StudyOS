from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User, Workspace, WorkspaceMember
from app.models.enums import AuditEventType, WorkspaceRole
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.schemas.common import error_responses
from app.services.events import record_audit

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
settings = get_settings()


def set_session_cookie(response: Response, token: str, expires_in: int) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=expires_in,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    dependencies=[Depends(rate_limit("auth"))],
    responses=error_responses(409, 422, 429),
)
async def register(
    payload: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    normalized_email = payload.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if existing is not None:
        raise AppError(
            409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists."
        )

    user = User(
        name=payload.name,
        email=normalized_email,
        password_hash=await hash_password(payload.password),
    )
    workspace = Workspace(name=f"{payload.name}'s workspace", owner=user)
    membership = WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole.OWNER.value)
    db.add_all([user, workspace, membership])
    try:
        await db.flush()
        await record_audit(
            db,
            user_id=user.id,
            workspace_id=workspace.id,
            event_type=AuditEventType.USER_REGISTERED,
            entity_type="User",
            entity_id=user.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(
            409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists."
        ) from exc

    token, expires_in = create_access_token(user.id, user.token_version)
    set_session_cookie(response, token, expires_in)
    # A token in the response body is readable by JavaScript, logged by proxies
    # and copied by XSS. The browser already has the HttpOnly cookie, so the
    # body only carries session metadata.
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in to an account",
    dependencies=[Depends(rate_limit("auth"))],
    responses=error_responses(401, 422, 429),
)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if user is None or not await verify_password(payload.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    token, expires_in = create_access_token(user.id, user.token_version)
    set_session_cookie(response, token, expires_in)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse, summary="Get the current user")
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
async def logout(
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke this user's tokens, not just the cookie holding one.

    Deleting the cookie only stops the browser that received it. A token copied
    elsewhere stays valid for the rest of its 30-minute lifetime, which is not
    what "log out" means. Bumping ``token_version`` invalidates every token
    minted before this moment; the cost is that logging out signs the user out
    of all their sessions, which is the safe default for a study account.
    """
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    response.headers["Cache-Control"] = "no-store"
