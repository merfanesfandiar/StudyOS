import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.errors import AppError

settings = get_settings()
#: Argon2 is deliberately expensive. A module-level hasher keeps its internal
#: state (randomised salt, per-call cost parameters) in one place; every hash
#: still runs in a worker thread so that the cost does not stall the event loop
#: for the whole request queue while one login is being checked.
password_hasher = PasswordHasher()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(password_hasher.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    def _verify() -> bool:
        try:
            return password_hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    return await asyncio.to_thread(_verify)


def create_access_token(user_id: UUID) -> tuple[str, int]:
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    expires_at = datetime.now(UTC) + expires_delta
    payload = {"sub": str(user_id), "exp": expires_at, "iat": datetime.now(UTC)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256"), int(
        expires_delta.total_seconds()
    )


def decode_access_token(token: str) -> UUID:
    credentials_error = AppError(
        status_code=401,
        code="AUTHENTICATION_REQUIRED",
        message="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        subject = payload.get("sub")
        if not subject:
            raise credentials_error
        return UUID(subject)
    except (JWTError, ValueError, TypeError) as exc:
        raise credentials_error from exc
