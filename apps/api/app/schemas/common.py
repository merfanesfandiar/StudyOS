from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "ASSIGNMENT_NOT_FOUND",
                    "message": "Assignment not found.",
                    "details": None,
                }
            }
        }
    )

    error: ErrorBody


class MessageResponse(BaseModel):
    message: str


class PageParams(BaseModel):
    """Shared pagination inputs.

    ``page`` is 1-based. ``page_size`` is capped so a single request cannot ask
    the database for an unbounded result set.
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class PageResponse[T](BaseModel):
    """Envelope returned by every paginated list endpoint."""

    items: list[T]
    page: Page
