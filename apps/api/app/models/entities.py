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
    AcademicTaskPriority,
    AcademicTaskStatus,
    AcademicTaskType,
    AgentArtifactStatus,
    AgentArtifactType,
    AgentCheckpointStatus,
    AgentCheckpointType,
    AgentExecutionStatus,
    AgentExecutorKind,
    AgentRunMode,
    AgentRunStatus,
    AIMode,
    AnalysisReviewStatus,
    AnalysisRunStatus,
    AssignmentStatus,
    ClassificationKind,
    ClassificationSource,
    ConstraintSeverity,
    ConstraintType,
    DeliverableStatus,
    DeliverableType,
    EffortLevel,
    GuidanceLevel,
    ModelTier,
    NotificationType,
    PlanningRunStatus,
    PlanningStyle,
    PlanStatus,
    PlanTrigger,
    QuestionStatus,
    RequirementPriority,
    RequirementStatus,
    RequirementType,
    SessionLength,
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
    plans: Mapped[list[AcademicWorkPlan]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AcademicWorkPlan.version",
    )
    planning_runs: Mapped[list[PlanningRun]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="PlanningRun.started_at",
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AgentRun.created_at",
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


# ---------------------------------------------------------------------------
# Phase 4: the Academic Planning Engine.
#
# A plan is a versioned, human-approved projection of an analysis into ordered
# academic tasks. Three rules shaped these tables:
#
# 1. Plans are immutable versions. Editing a plan creates the next version rather
#    than mutating the approved one, so "what the student approved" stays
#    answerable after they change their mind.
# 2. Task-to-requirement links are rows, not embedded JSON, because traceability
#    is the feature that makes a plan trustworthy and it has to be queryable and
#    enforceable.
# 3. Task dependencies are rows rather than an array so cycle detection can run
#    in SQL and in the validator without re-parsing a blob.
# ---------------------------------------------------------------------------


class AcademicWorkPlan(TimestampMixin, Base):
    """A versioned, reviewable plan of academic work for one assignment."""

    __tablename__ = "academic_work_plans"
    __table_args__ = (
        UniqueConstraint("assignment_id", "version", name="uq_work_plan_assignment_version"),
        Index("ix_academic_work_plans_assignment_id", "assignment_id"),
        Index("ix_academic_work_plans_analysis_id", "analysis_id"),
        Index(
            "ix_academic_work_plans_assignment_status",
            "assignment_id",
            "status",
        ),
        Index("ix_academic_work_plans_plan_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    #: The analysis this plan was generated from. The FK is SET NULL rather than
    #: CASCADE on purpose: deleting an analysis must not silently delete approved
    #: student work. The plan survives and reports itself as orphaned instead.
    analysis_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignment_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Monotonic per-assignment version, 1 for the first plan. A plan is never
    #: updated in place across versions; this is the authoritative ordering.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Why this version exists. Shown to the student so a regeneration is legible
    #: rather than surprising.
    reason: Mapped[str] = mapped_column(
        String(200), nullable=False, default=PlanTrigger.GENERATED.value
    )
    trigger: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanTrigger.GENERATED.value
    )
    #: Sections the model changed relative to the previous version, as plan-relative
    #: keys such as ``tasks:3`` or ``milestones``. ``None`` means a first version.
    changed_sections: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanStatus.DRAFT.value, index=True
    )
    objectives: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: The validated plan payload: tasks, milestones, verification points, effort
    #: and risk. Kept as JSON for the same reason the analysis payload is: it is a
    #: document the model produced, it is versioned wholesale, and the queryable
    #: projections below are what the database must enforce.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    estimated_effort: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EffortLevel.UNKNOWN.value
    )
    min_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Set when the source analysis moved on. A stale plan stays readable but
    #: cannot be approved or treated as current.
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Deterministic key over assignment + analysis + planner prompt + model, so a
    #: repeated identical request does not bill twice.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    assignment: Mapped[Assignment] = relationship(back_populates="plans")
    analysis: Mapped[AssignmentAnalysis | None] = relationship(foreign_keys=[analysis_id])
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])
    tasks: Mapped[list[PlanTask]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="(PlanTask.position, PlanTask.created_at)",
    )
    task_requirements: Mapped[list[PlanTaskRequirement]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    task_deliverables: Mapped[list[PlanTaskDeliverable]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    dependencies: Mapped[list[PlanTaskDependency]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    milestones: Mapped[list[PlanMilestone]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="(PlanMilestone.position, PlanMilestone.created_at)",
    )
    runs: Mapped[list[PlanningRun]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanTask(Base):
    """One unit of academic work. Generic by design: no task assumes code."""

    __tablename__ = "plan_tasks"
    __table_args__ = (
        UniqueConstraint("plan_id", "key", name="uq_plan_task_plan_key"),
        Index("ix_plan_tasks_plan_id", "plan_id"),
        Index("ix_plan_tasks_plan_status", "plan_id", "status"),
        Index("ix_plan_tasks_type", "type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_work_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Stable plan-local key (``T1``, ``T2``). Unlike the database id this is what
    #: the model emits and what dependency edges reference, so it must survive a
    #: regeneration that preserves unrelated tasks.
    key: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AcademicTaskType.OTHER.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AcademicTaskStatus.PENDING.value
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AcademicTaskPriority.MEDIUM.value
    )
    #: Topological order within the plan. Renumbered on reorder so it always
    #: reflects the current graph rather than the original generation order.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_effort: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EffortLevel.UNKNOWN.value
    )
    min_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(300), nullable=True)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    resources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: True when the student added or edited this task. Regeneration preserves
    #: user-authored tasks and must never overwrite them.
    is_user_authored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[AcademicWorkPlan] = relationship(back_populates="tasks")
    requirement_links: Mapped[list[PlanTaskRequirement]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    deliverable_links: Mapped[list[PlanTaskDeliverable]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    predecessors: Mapped[list[PlanTaskDependency]] = relationship(
        back_populates="successor",
        cascade="all, delete-orphan",
        foreign_keys="PlanTaskDependency.successor_id",
    )
    successors: Mapped[list[PlanTaskDependency]] = relationship(
        back_populates="predecessor",
        cascade="all, delete-orphan",
        foreign_keys="PlanTaskDependency.predecessor_id",
    )
    agent_executions: Mapped[list[AgentTaskExecution]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class PlanTaskRequirement(Base):
    """Traceability edge: this task exists because of this requirement.

    The requirement key is stored as text rather than a foreign key on purpose.
    A requirement key is a planning-contract-local reference (``R3``), not a
    database id, and the same key can be a normalised requirement or a work area
    reference. The FK that matters is to the plan: dropping a plan drops its
    traceability, and dropping an analysis does not.
    """

    __tablename__ = "plan_task_requirements"
    __table_args__ = (
        UniqueConstraint("task_id", "requirement_key", name="uq_plan_task_requirement"),
        Index("ix_plan_task_requirements_plan_id", "plan_id"),
        Index("ix_plan_task_requirements_task_id", "task_id"),
        Index("ix_plan_task_requirements_key", "plan_id", "requirement_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_work_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("plan_tasks.id", ondelete="CASCADE"), nullable=False
    )
    requirement_key: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[AcademicWorkPlan] = relationship(back_populates="task_requirements")
    task: Mapped[PlanTask] = relationship(back_populates="requirement_links")


class PlanTaskDeliverable(Base):
    """Traceability edge: this task contributes to this deliverable."""

    __tablename__ = "plan_task_deliverables"
    __table_args__ = (
        UniqueConstraint("task_id", "deliverable_key", name="uq_plan_task_deliverable"),
        Index("ix_plan_task_deliverables_plan_id", "plan_id"),
        Index("ix_plan_task_deliverables_task_id", "task_id"),
        Index("ix_plan_task_deliverables_key", "plan_id", "deliverable_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_work_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("plan_tasks.id", ondelete="CASCADE"), nullable=False
    )
    deliverable_key: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[AcademicWorkPlan] = relationship(back_populates="task_deliverables")
    task: Mapped[PlanTask] = relationship(back_populates="deliverable_links")


class PlanTaskDependency(Base):
    """A directed edge ``predecessor -> successor`` in the task graph.

    Self-references are named explicitly so Alembic can round-trip them. The
    database cannot prevent a cycle across rows, so the deterministic validator
    in ``app/modules/planning/graph.py`` is the authority on that; the service
    refuses to persist a plan that has not passed it.
    """

    __tablename__ = "plan_task_dependencies"
    __table_args__ = (
        UniqueConstraint("predecessor_id", "successor_id", name="uq_plan_task_dependency"),
        Index("ix_plan_task_dependencies_plan_id", "plan_id"),
        Index("ix_plan_task_dependencies_predecessor", "predecessor_id"),
        Index("ix_plan_task_dependencies_successor", "successor_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_work_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    predecessor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plan_tasks.id", ondelete="CASCADE", name="fk_plan_dependency_predecessor"),
        nullable=False,
    )
    successor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plan_tasks.id", ondelete="CASCADE", name="fk_plan_dependency_successor"),
        nullable=False,
    )
    #: Why this ordering exists, shown to the student when they ask "why is this
    #: here first?".
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[AcademicWorkPlan] = relationship(back_populates="dependencies")
    predecessor: Mapped[PlanTask] = relationship(
        back_populates="successors", foreign_keys=[predecessor_id]
    )
    successor: Mapped[PlanTask] = relationship(
        back_populates="predecessors", foreign_keys=[successor_id]
    )


class PlanMilestone(Base):
    """A meaningful checkpoint in the plan.

    Deliberately few. A plan with thirty milestones has none, so the planner caps
    them and the UI treats them as progress markers rather than tasks.
    """

    __tablename__ = "plan_milestones"
    __table_args__ = (
        UniqueConstraint("plan_id", "key", name="uq_plan_milestone_plan_key"),
        Index("ix_plan_milestones_plan_id", "plan_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_work_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AcademicTaskStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    plan: Mapped[AcademicWorkPlan] = relationship(back_populates="milestones")


class PlanningRun(TimestampMixin, Base):
    """One execution of the planner. Telemetry only, never chain-of-thought.

    Mirrors ``AnalysisRun`` so both AI subsystems answer the same operational
    questions: which model ran, on what, for how long, at what cost, and what
    went wrong. ``routing_reason`` is a one-line explanation written for a human,
    not the router's internal scoring.
    """

    __tablename__ = "planning_runs"
    __table_args__ = (
        Index("ix_planning_runs_assignment_id", "assignment_id"),
        Index("ix_planning_runs_plan_id", "plan_id"),
        Index("ix_planning_runs_status", "status"),
        Index("ix_planning_runs_assignment_started", "assignment_id", "started_at"),
        Index("ix_planning_runs_idempotency_key", "idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=time_ordered_uuid
    )
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_work_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanningRunStatus.QUEUED.value
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    model_tier: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ModelTier.EFFICIENT.value
    )
    #: Concise, human-readable selection explanation. Never internal reasoning.
    routing_reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    routing_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    complexity: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    #: Set when this run fell back from the advanced tier to the efficient one.
    fell_back_from_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    plan: Mapped[AcademicWorkPlan | None] = relationship(back_populates="runs")
    assignment: Mapped[Assignment] = relationship(back_populates="planning_runs")
    triggered_by: Mapped[User | None] = relationship(foreign_keys=[triggered_by_id])


class PlanningPreference(Base):
    """Per-workspace planning and AI preferences.

    Workspace-scoped rather than user-scoped on purpose: a future shared workspace
    should plan consistently for everyone in it, and per-user duplication would
    make two members of the same course see different plans for the same brief.
    """

    __tablename__ = "planning_preferences"
    __table_args__ = (Index("ix_planning_preferences_workspace_id", "workspace_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    planning_style: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanningStyle.BALANCED.value
    )
    guidance_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default=GuidanceLevel.MEDIUM.value
    )
    session_length: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SessionLength.MEDIUM.value
    )
    ai_mode: Mapped[str] = mapped_column(String(20), nullable=False, default=AIMode.AUTO.value)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Phase 5: the Professional Agent Runtime.
#
# An agent run is a durable, resumable attempt to execute an approved plan. The
# runtime is deliberately incapable of unrestricted action: it has no shell, no
# browser, no outbound network and no filesystem access. What it does have is a
# complete record of what it tried, why, at what cost, and what it produced — so
# a run is auditable and restartable rather than a black box that either worked
# or did not.
#
# The tables split along three seams:
#
#   * ``agent_runs`` is the lifecycle and the only place limits are enforced.
#   * ``agent_task_executions`` is the per-attempt ledger, so a retried task
#     keeps every failed attempt instead of overwriting the last one.
#   * ``agent_events`` is the user-facing activity stream, deliberately separate
#     from ``agent_decisions`` which holds the structured rationale.
#
# Nothing here stores chain-of-thought. Decisions record an action, a reason and
# an outcome, which is what an auditor actually needs.
# ---------------------------------------------------------------------------


class AgentRun(TimestampMixin, Base):
    """One attempt to execute an approved plan.

    A run references the exact plan version it was started against. If the plan is
    later regenerated the run stays bound to the version it is working on, because
    "this task completed" is only meaningful relative to what the task said at the
    time.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_assignment_id", "assignment_id"),
        Index("ix_agent_runs_plan_id", "plan_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_assignment_status", "assignment_id", "status"),
        Index("ix_agent_runs_idempotency_key", "idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=time_ordered_uuid
    )
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    #: SET NULL, not CASCADE: deleting a plan must not delete the record of work
    #: a student already did against it.
    plan_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("academic_work_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Frozen at creation. Used to detect that the underlying plan was regenerated
    #: mid-run without re-reading the plan.
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AgentRunStatus.CREATED.value
    )
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AgentRunMode.SUPERVISED.value
    )
    #: Set once the run stops for a checkpoint or a wall, and cleared on resume.
    #: A run with no reason is indistinguishable from one that is merely slow.
    paused_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Which model served the most recent step, kept denormalised so the run
    #: summary is one row read rather than a join over executions.
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    routing_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: Hard loop budget. Exceeding it fails the run with SYSTEM_ERROR rather than
    #: looping forever; see ``AgentLimits``.
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    max_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("5.000000")
    )
    #: Accumulated estimate. Compared against ``max_cost`` before each provider
    #: call, so a runaway loop is stopped rather than discovered on the invoice.
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0.000000")
    )
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: Deterministic key over assignment + plan version + request, so a double
    #: click does not start two runs.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Monotonic counter bumped inside the run lock before every step. A step that
    #: finds its write lost means it was superseded by a concurrent writer.
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Set while a step is in flight. A run left RUNNING with a stale heartbeat
    #: after a restart is what ``AgentRecoveryService`` looks for.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggered_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    assignment: Mapped[Assignment] = relationship(back_populates="agent_runs")
    plan: Mapped[AcademicWorkPlan | None] = relationship(back_populates="agent_runs")
    triggered_by: Mapped[User | None] = relationship(foreign_keys=[triggered_by_id])
    executions: Mapped[list[AgentTaskExecution]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentTaskExecution.attempt"
    )
    artifacts: Mapped[list[AgentArtifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    checkpoints: Mapped[list[AgentCheckpoint]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list[AgentEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    decisions: Mapped[list[AgentDecision]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentTaskExecution(Base):
    """One attempt at one plan task.

    A retried task gains a new row rather than being updated in place. Losing the
    earlier attempts would lose the only evidence of *how* the work failed, which
    is what makes the failure category and backoff policy meaningful over time.
    """

    __tablename__ = "agent_task_executions"
    __table_args__ = (
        UniqueConstraint("run_id", "task_id", "attempt", name="uq_agent_execution_attempt"),
        Index("ix_agent_task_executions_run_id", "run_id"),
        Index("ix_agent_task_executions_task_id", "task_id"),
        Index("ix_agent_task_executions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plan_tasks.id", name="fk_agent_execution_task", ondelete="CASCADE"),
        nullable=False,
    )
    #: Plan-local key copied at execution time so the row is readable after the
    #: task row changes and self-describing in the activity feed.
    task_key: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 1-based. Attempt 1 is the first try; a retry is attempt 2, and so on.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AgentExecutionStatus.FAILED.value
    )
    executor: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AgentExecutorKind.REASONING.value
    )
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: What the executor produced. ``None`` for a failure that produced nothing.
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: User-safe structured rationale. Never raw model reasoning.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Recorded so the retry policy can back off based on elapsed time rather than
    #: on a wall-clock guess.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Rejected-by-validation detail when the model output failed the decision
    #: contract. Kept apart from ``error_message`` so a schema failure is
    #: distinguishable from an execution failure.
    validation_errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="executions")
    task: Mapped[PlanTask] = relationship(back_populates="agent_executions")


class AgentArtifact(TimestampMixin, Base):
    """Something the run produced, owned by the student and versioned by revision.

    ``code`` is a permitted artifact type, but it is stored as text and never
    executed by the runtime. That is the whole boundary in one column.
    """

    __tablename__ = "agent_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "task_id", "revision", name="uq_agent_artifact_revision"),
        Index("ix_agent_artifacts_run_id", "run_id"),
        Index("ix_agent_artifacts_run_type", "run_id", "artifact_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plan_tasks.id", name="fk_agent_artifact_task", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    artifact_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AgentArtifactType.TEXT.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AgentArtifactStatus.DRAFT.value
    )
    #: The body. For MARKDOWN this is the rendered source; for CODE it is text
    #: that is never run.
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Structured companion to ``content`` for results that have one: a
    #: calculation's intermediate values, a solution's steps.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: 1-based revision counter. An update supersedes rather than overwrites, so
    #: "what the run produced, then what the student asked for" stays answerable.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Free-text link to the assignment deliverable this satisfies, if any. A
    #: string, not a foreign key: the agent must not claim a deliverable is done.
    deliverable_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    run: Mapped[AgentRun] = relationship(back_populates="artifacts")
    task: Mapped[PlanTask | None] = relationship(foreign_keys=[task_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class AgentCheckpoint(TimestampMixin, Base):
    """A point where the runtime deliberately hands control back to the student.

    Created with ``question`` so the UI can ask something specific, and resolved
    with the student's own ``response``. The runtime never answers its own
    question, which is what keeps supervised mode supervised.
    """

    __tablename__ = "agent_checkpoints"
    __table_args__ = (
        Index("ix_agent_checkpoints_run_id", "run_id"),
        Index("ix_agent_checkpoints_run_status", "run_id", "status"),
        Index("ix_agent_checkpoints_task_id", "task_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plan_tasks.id", name="fk_agent_checkpoint_task", ondelete="SET NULL"),
        nullable=True,
    )
    checkpoint_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AgentCheckpointType.CLARIFICATION.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AgentCheckpointStatus.PENDING.value
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    #: Why this could not proceed without a person. Shown in the UI alongside the
    #: question so "please choose" and "you must choose" are distinguishable.
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Set when a checkpoint expires without an answer so a blocked run cannot be
    #: resumed into work the student never agreed to.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="checkpoints")
    task: Mapped[PlanTask | None] = relationship(foreign_keys=[task_id])
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])


class AgentEvent(Base):
    """The durable, user-safe activity stream for one run.

    Append-only and time-ordered so the activity panel can page it. ``summary`` is
    written for a person; the structured detail sits in ``metadata_json``. This is
    deliberately *not* a reasoning trace.
    """

    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_agent_events_run_sequence"),
        Index("ix_agent_events_run_id_created_at", "run_id", "created_at"),
        Index("ix_agent_events_run_id_sequence", "run_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=time_ordered_uuid
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    #: Per-run monotonic counter. ``created_at`` alone is not enough: several
    #: events can share a timestamp within one step.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    #: User-safe one-line description. Never raw model output.
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("plan_tasks.id", name="fk_agent_event_task", ondelete="SET NULL"),
        nullable=True,
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "agent_task_executions.id", name="fk_agent_event_execution", ondelete="SET NULL"
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[AgentRun] = relationship(back_populates="events")
    task: Mapped[PlanTask | None] = relationship(foreign_keys=[task_id])
    execution: Mapped[AgentTaskExecution | None] = relationship(foreign_keys=[execution_id])


class AgentDecision(Base):
    """A structured decision the runtime took, with its outcome.

    This is the record of *what was decided and what happened*, written by the
    runtime after validation, never by the model directly. ``action`` is
    constrained to :class:`AgentAction`, and ``validation_errors`` retains what
    was rejected so a model that keeps producing invalid output is visible rather
    than merely retried.
    """

    __tablename__ = "agent_decisions"
    __table_args__ = (
        UniqueConstraint("run_id", "iteration", name="uq_agent_decision_iteration"),
        Index("ix_agent_decisions_run_id", "run_id"),
        Index("ix_agent_decisions_action", "action"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=time_ordered_uuid
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    #: The runtime loop iteration that produced this decision. One decision per
    #: iteration is what makes the budget auditable.
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    #: Concise, structured rationale. The only explanation the runtime stores.
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: Validated action payload: task key, artifact id, question, and so on.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: What the runtime did about it. A decision with no outcome is a decision
    #: the runtime never acted on, which is worth seeing.
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[AgentRun] = relationship(back_populates="decisions")
