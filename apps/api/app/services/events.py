from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.models.enums import AuditEventType


async def record_audit(
    db: AsyncSession,
    *,
    user_id: UUID | None,
    workspace_id: UUID | None,
    event_type: AuditEventType,
    entity_type: str,
    entity_id: UUID | None,
    assignment_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an audit row.

    Callers pass metadata explicitly and only values that are safe to persist:
    never a password, token, secret or file content. ``assignment_id`` is set
    for specification events so the assignment activity feed is a single query.
    """
    db.add(
        AuditLog(
            user_id=user_id,
            workspace_id=workspace_id,
            assignment_id=assignment_id,
            event_type=event_type.value,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata or {},
        )
    )
