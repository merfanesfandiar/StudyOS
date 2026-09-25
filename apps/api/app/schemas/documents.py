from datetime import datetime
from uuid import UUID

from app.schemas.common import APIModel


class DocumentResponse(APIModel):
    id: UUID
    assignment_id: UUID
    filename: str
    mime_type: str
    size: int
    created_at: datetime
