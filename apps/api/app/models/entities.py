from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.enums import (
    AnalysisReviewStatus,
    AnalysisRunStatus,
    AssignmentStatus,
    ClassificationKind,
    ClassificationSource,
    ConstraintSeverity,
    ConstraintType,
    DeliverableStatus,
    DeliverableType,
    NotificationType,
    QuestionStatus,
    RequirementPriority,
    RequirementStatus,
    RequirementType,
    TechnologyCategory,
    WorkspaceRole,
)
from app.models.identifiers import time_ordered_uuid


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_email", "email", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    owned_workspaces: Mapped[Workspace] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="user")


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    owner: Mapped[User] = relationship(back_populates="owned_workspaces", foreign_keys=[owner_id])
    memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    courses: Mapped[list[Course]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    technologies: Mapped[list[Technology]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkspaceRole.MEMBER.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Course(TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_courses_workspace_code"),
        Index("ix_courses_workspace_id", "workspace_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    workspace: Mapped[Workspace] = relationship(back_populates="courses")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="course")


class Assignment(TimestampMixin, Base):
    __tablename__ = "assignments"
    __table_args__ = (
        Index("ix_assignments_workspace_id", "workspace_id"),
        Index("ix_assignments_course_id", "course_id"),
        Index("ix_assignments_deadline", "deadline"),
        Index("ix_assignments_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AssignmentStatus.DRAFT.value, index=True
    )
    readiness_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ready_for_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Highest requirement number ever handed out. Kept on the row so a deleted
    #: REQ-004 is never handed to a different requirement, which would make old
    #: tasks, files and tests point at the wrong thing.
    requirement_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    workspace: Mapped[Workspace] = relationship(back_populates="assignments")
    course: Mapped[Course] = relationship(back_populates="assignments")
    requirements: Mapped[list[AssignmentRequirement]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="(AssignmentRequirement.position, AssignmentRequirement.sequence)",
    )
    constraints: Mapped[list[AssignmentConstraint]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="(AssignmentConstraint.position, AssignmentConstraint.created_at)",
    )
    criteria: Mapped[list[EvaluationCriterion]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="(EvaluationCriterion.position, EvaluationCriterion.created_at)",
    )
    deliverables: Mapped[list[Deliverable]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="(Deliverable.position, Deliverable.created_at)",
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", order_by="Document.created_at"
    )
    technologies: Mapped[list[AssignmentTechnology]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )
    tags: Mapped[list[AssignmentTag]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )
    versions: Mapped[list[AssignmentVersion]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AssignmentVersion.version",
    )
    analyses: Mapped[list[AssignmentAnalysis]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AssignmentAnalysis.created_at",
    )
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AnalysisRun.started_at",
    )


class AssignmentRequirement(TimestampMixin, Base):
    """One thing the finished work must accomplish.

    ``sequence`` is the stable, immutable identity behind the public
    ``REQ-001`` reference; it is assigned once and never reused, even after the
    requirement is deleted. ``position`` is the mutable display order.
    """

    __tablename__ = "assignment_requirements"
    __table_args__ = (
        UniqueConstraint("assignment_id", "sequence", name="uq_requirement_assignment_sequence"),
        Index("ix_assignment_requirements_assignment_id", "assignment_id"),
        Index("ix_assignment_requirements_status", "status"),
        Index("ix_assignment_requirements_priority", "priority"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RequirementPriority.MEDIUM.value
    )
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=RequirementType.OTHER.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RequirementStatus.TODO.value
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignment_requirements.id", name="fk_requirement_parent", ondelete="SET NULL"),
        nullable=True,
    )

    assignment: Mapped[Assignment] = relationship(back_populates="requirements")
    parent: Mapped[AssignmentRequirement | None] = relationship(
        back_populates="children", remote_side="AssignmentRequirement.id"
    )
    children: Mapped[list[AssignmentRequirement]] = relationship(back_populates="parent")
    dependencies: Mapped[list[RequirementDependency]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        foreign_keys="RequirementDependency.requirement_id",
    )
    dependents: Mapped[list[RequirementDependency]] = relationship(
        back_populates="depends_on",
        cascade="all, delete-orphan",
        foreign_keys="RequirementDependency.depends_on_id",
    )


class RequirementDependency(Base):
    """``requirement`` needs ``depends_on`` to exist first.

    A row means: "the requirement cannot start before its dependency is done".
    """

    __tablename__ = "requirement_dependencies"
    __table_args__ = (
        UniqueConstraint("requirement_id", "depends_on_id", name="uq_requirement_dependency_pair"),
        Index("ix_requirement_dependencies_requirement_id", "requirement_id"),
        Index("ix_requirement_dependencies_depends_on_id", "depends_on_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignment_requirements.id", ondelete="CASCADE"),
        nullable=False,
    )
    depends_on_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignment_requirements.id", ondelete="CASCADE"),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    assignment: Mapped[Assignment] = relationship()
    requirement: Mapped[AssignmentRequirement] = relationship(
        back_populates="dependencies", foreign_keys=[requirement_id]
    )
    depends_on: Mapped[AssignmentRequirement] = relationship(
        back_populates="dependents", foreign_keys=[depends_on_id]
    )


class AssignmentConstraint(TimestampMixin, Base):
    __tablename__ = "assignment_constraints"
    __table_args__ = (
        Index("ix_assignment_constraints_assignment_id", "assignment_id"),
        Index("ix_assignment_constraints_position", "position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ConstraintType.OTHER.value
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConstraintSeverity.WARNING.value
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    assignment: Mapped[Assignment] = relationship(back_populates="constraints")


class EvaluationCriterion(TimestampMixin, Base):
    __tablename__ = "evaluation_criteria"
    __table_args__ = (
        Index("ix_evaluation_criteria_assignment_id", "assignment_id"),
        Index("ix_evaluation_criteria_position", "position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    assignment: Mapped[Assignment] = relationship(back_populates="criteria")


class Deliverable(TimestampMixin, Base):
    """Something the student has to hand in."""

    __tablename__ = "deliverables"
    __table_args__ = (
        Index("ix_deliverables_assignment_id", "assignment_id"),
        Index("ix_deliverables_status", "status"),
        Index("ix_deliverables_position", "position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DeliverableType.DOCUMENT.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DeliverableStatus.PENDING.value
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    assignment: Mapped[Assignment] = relationship(back_populates="deliverables")


class Technology(TimestampMixin, Base):
    """Workspace-scoped technology, reused across assignments.

    Deliberately not a global marketplace: technologies are normalised inside a
    workspace so assignment specifications stay portable without StudyOS owning a
    public technology database.
    """

    __tablename__ = "technologies"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "normalized_name", "version", name="uq_technology_workspace_identity"
        ),
        Index("ix_technologies_workspace_id", "workspace_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TechnologyCategory.OTHER.value
    )

    workspace: Mapped[Workspace] = relationship(back_populates="technologies")
    assignments: Mapped[list[AssignmentTechnology]] = relationship(
        back_populates="technology", cascade="all, delete-orphan"
    )


class AssignmentTechnology(Base):
    __tablename__ = "assignment_technologies"
    __table_args__ = (
        UniqueConstraint("assignment_id", "technology_id", name="uq_assignment_technology"),
        Index("ix_assignment_technologies_assignment_id", "assignment_id"),
    )

    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True
    )
    technology_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("technologies.id", ondelete="CASCADE"), primary_key=True
    )

    assignment: Mapped[Assignment] = relationship(back_populates="technologies")
    technology: Mapped[Technology] = relationship(back_populates="assignments")


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("workspace_id", "normalized_name", name="uq_tag_workspace_name"),
        Index("ix_tags_workspace_id", "workspace_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(60), nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="tags")
    assignments: Mapped[list[AssignmentTag]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )


class AssignmentTag(Base):
    __tablename__ = "assignment_tags"
    __table_args__ = (
        UniqueConstraint("assignment_id", "tag_id", name="uq_assignment_tag"),
        Index("ix_assignment_tags_assignment_id", "assignment_id"),
        Index("ix_assignment_tags_tag_id", "tag_id"),
    )

    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    assignment: Mapped[Assignment] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship(back_populates="assignments")


class AssignmentVersion(Base):
    """Immutable point-in-time snapshot of one specification state.

    The relational tables remain the source of truth. This is an audit trail:
    rows are never mutated and are only read to show history or to diff what
    changed, so storing the snapshot as JSON is deliberate.
    """

    __tablename__ = "assignment_versions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "version", name="uq_assignment_version"),
        Index("ix_assignment_versions_assignment_id", "assignment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(500), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    assignment: Mapped[Assignment] = relationship(back_populates="versions")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        Index("ix_documents_assignment_id", "assignment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    assignment: Mapped[Assignment] = relationship(back_populates="documents")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=NotificationType.INFO.value
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="notifications")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_audit_logs_assignment_id", "assignment_id"),
    )

    # A time-ordered id keeps the assignment activity feed stable: several audit
    # rows can share one timestamp, and a random uuid would reshuffle the page.
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=time_ordered_uuid
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    assignment_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignments.id", name="fk_audit_logs_assignment_id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User | None] = relationship(back_populates="audit_logs")


# ---------------------------------------------------------------------------
# Phase 3: universal academic assignment intelligence
#
# An analysis is an *AI interpretation*, never authoritative data. It is stored
# as one immutable JSON snapshot plus a small set of mutable review fields, so a
# student can accept, reject, edit or answer questions without the model ever
# rewriting the assignment's requirements, deadline, rubric or constraints.
# ---------------------------------------------------------------------------


class AssignmentAnalysis(TimestampMixin, Base):
    __tablename__ = "assignment_analyses"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "idempotency_key", name="uq_analysis_assignment_idempotency"
        ),
        Index("ix_assignment_analyses_assignment_id", "assignment_id"),
        Index(
            "ix_assignment_analyses_assignment_stale",
            "assignment_id",
            "is_stale",
        ),
        Index(
            "ix_assignment_analyses_assignment_revision",
            "assignment_id",
            "revision",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    #: Schema/contract version of the assigned analysis, bumped when the shape of
    #: the payload changes incompatibly.
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Monotonic per-assignment counter, 1 for the first analysis. ``created_at`` is
    #: not unique enough to order by: the database clock has one-second resolution on
    #: SQLite, so two analyses in the same second tie and "newest" becomes arbitrary.
    #: This is the authoritative ordering for "the latest analysis".
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The immutable specification version this analysis was computed against.
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Stable hash of the analyzer input, so the same input can be recognised.
    specification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Deterministic key over assignment + spec + prompt + provider + model.
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AnalysisReviewStatus.PENDING.value, index=True
    )
    #: The validated AI analysis. Immutable: never overwritten by a user edit.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: Human corrections layered on top. ``None`` means the student has not
    #: changed anything. Authoritative assignment data is never touched here.
    edited_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignment: Mapped[Assignment] = relationship(back_populates="analyses")
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])
    runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    questions: Mapped[list[AnalysisQuestion]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="(AnalysisQuestion.position, AnalysisQuestion.created_at)",
    )
    classifications: Mapped[list[AnalysisClassification]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="(AnalysisClassification.kind, AnalysisClassification.position)",
    )


class AnalysisRun(TimestampMixin, Base):
    """One execution of the analyzer. Telemetry only, never chain-of-thought."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_assignment_id", "assignment_id"),
        Index("ix_analysis_runs_status", "status"),
        Index("ix_analysis_runs_assignment_started", "assignment_id", "started_at"),
        Index("ix_analysis_runs_idempotency_key", "idempotency_key"),
    )

    #: Time-ordered so the run list is stable when several runs share a second.
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=time_ordered_uuid
    )
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignment_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AnalysisRunStatus.QUEUED.value
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    assignment: Mapped[Assignment] = relationship(back_populates="analysis_runs")
    analysis: Mapped[AssignmentAnalysis | None] = relationship(back_populates="runs")
    triggered_by: Mapped[User | None] = relationship(foreign_keys=[triggered_by_id])


class AnalysisQuestion(TimestampMixin, Base):
    """A clarification question the student can ask their instructor."""

    __tablename__ = "analysis_questions"
    __table_args__ = (
        UniqueConstraint("analysis_id", "code", name="uq_analysis_question_code"),
        Index("ix_analysis_questions_analysis_id", "analysis_id"),
        Index("ix_analysis_questions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignment_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Stable ``Q-001`` reference within one analysis.
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=QuestionStatus.OPEN.value
    )
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    analysis: Mapped[AssignmentAnalysis] = relationship(back_populates="questions")
    answered_by: Mapped[User | None] = relationship(foreign_keys=[answered_by_id])


class AnalysisClassification(TimestampMixin, Base):
    """One classified assignment type or academic domain, AI- or user-assigned.

    A user correction is stored as a new ``USER`` row and the AI's ``AI`` rows
    remain, so a classification can always be audited rather than silently
    overwritten.
    """

    __tablename__ = "analysis_classifications"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "kind", "value", "source", name="uq_analysis_classification"
        ),
        Index("ix_analysis_classifications_analysis_id", "analysis_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignment_analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ClassificationKind.TYPE.value
    )
    value: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default=ClassificationSource.AI.value
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    analysis: Mapped[AssignmentAnalysis] = relationship(back_populates="classifications")
