from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.models.enums import AuditEventType


@dataclass(frozen=True)
class DomainEvent:
    name: str
    entity_type: str
    entity_id: UUID | None
    occurred_at: datetime
    metadata: dict[str, Any]


async def record_audit(
    db: AsyncSession,
    *,
    user_id: UUID | None,
    workspace_id: UUID | None,
    event_type: AuditEventType,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            workspace_id=workspace_id,
            event_type=event_type.value,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata or {},
        )
    )


def assignment_created_event(assignment_id: UUID) -> DomainEvent:
    return DomainEvent(
        name="AssignmentCreated",
        entity_type="Assignment",
        entity_id=assignment_id,
        occurred_at=datetime.now(UTC),
        metadata={},
    )
