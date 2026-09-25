import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import APIModel


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Alex Student",
                "email": "student@studyos.dev",
                "password": "Studyos123",
            }
        }
    )

    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Name must contain at least two non-whitespace characters")
        return normalized

    @field_validator("password")
    @classmethod
    def enforce_password_policy(cls, value: str) -> str:
        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must contain an uppercase letter")
        if not re.search(r"[a-z]", value):
            raise ValueError("Password must contain a lowercase letter")
        if not re.search(r"[0-9]", value):
            raise ValueError("Password must contain a number")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "student@studyos.dev", "password": "Studyos123"}}
    )

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(APIModel):
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "id": "6f1c1f7e-0f6d-4a2a-9d1a-4a2f7b1c9d33",
                "name": "Alex Student",
                "email": "student@studyos.dev",
                "created_at": "2026-01-05T09:15:00Z",
                "updated_at": "2026-01-05T09:15:00Z",
            }
        },
    )

    id: UUID
    name: str
    email: EmailStr
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
