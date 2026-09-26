"""Lightweight specification history.

Every meaningful specification change appends an immutable row holding the
version number, a human-readable change summary and a snapshot of the whole
specification. Versions are never edited or deleted, so ``v3`` always means the
same thing. The relational tables stay the source of truth; the snapshot exists
for auditability and for diffing what a future AI run was given.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Assignment, AssignmentVersion
from app.modules.assignments.specification import specification_snapshot
from app.schemas.specification import ReadinessReport


async def current_version(assignment_id: UUID, db: AsyncSession) -> int:
    highest = await db.scalar(
        select(func.max(AssignmentVersion.version)).where(
            AssignmentVersion.assignment_id == assignment_id
        )
    )
    return highest or 0


async def create_version(
    db: AsyncSession,
    *,
    assignment: Assignment,
    created_by_id: UUID | None,
    change_summary: str,
    report: ReadinessReport,
) -> AssignmentVersion:
    """Append a version snapshot. Callers flush other changes first."""
    version = await current_version(assignment.id, db) + 1
    entry = AssignmentVersion(
        assignment_id=assignment.id,
        version=version,
        change_summary=change_summary[:500],
        snapshot=specification_snapshot(assignment, report, version),
        created_by_id=created_by_id,
    )
    db.add(entry)
    return entry


async def list_versions(
    assignment_id: UUID, db: AsyncSession, *, offset: int, limit: int
) -> tuple[Sequence[AssignmentVersion], int]:
    total = await db.scalar(
        select(func.count(AssignmentVersion.id)).where(
            AssignmentVersion.assignment_id == assignment_id
        )
    )
    result = await db.execute(
        select(AssignmentVersion)
        .where(AssignmentVersion.assignment_id == assignment_id)
        .order_by(AssignmentVersion.version.desc())
        .offset(offset)
        .limit(limit)
    )
    return tuple(result.scalars().all()), total or 0


async def get_version(assignment_id: UUID, version: int, db: AsyncSession) -> AssignmentVersion:
    entry = await db.scalar(
        select(AssignmentVersion).where(
            AssignmentVersion.assignment_id == assignment_id,
            AssignmentVersion.version == version,
        )
    )
    if entry is None:
        raise AppError(404, "VERSION_NOT_FOUND", "Specification version not found.")
    return entry
