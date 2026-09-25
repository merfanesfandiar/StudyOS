from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import APIModel


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name", "code")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return " ".join(value.upper().split())


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    code: str | None = Field(default=None, min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("name", "code")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return " ".join(value.upper().split()) if value is not None else None


class CourseResponse(APIModel):
    id: UUID
    workspace_id: UUID
    name: str
    code: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    assignment_count: int = 0
