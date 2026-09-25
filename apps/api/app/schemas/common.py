from pydantic import BaseModel, ConfigDict


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
