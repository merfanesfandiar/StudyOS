from enum import StrEnum


class AssignmentStatus(StrEnum):
    """Lifecycle of an assignment specification.

    Phase 2 splits Phase 1's ``ACTIVE`` into the explicit readiness states
    ``INCOMPLETE`` and ``READY_FOR_ANALYSIS``. ``ACTIVE`` is kept as a
    deprecated alias so Phase 1 clients and rows keep working; nothing in the
    application produces it any more.
    """

    DRAFT = "DRAFT"
    INCOMPLETE = "INCOMPLETE"
    READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
    ANALYSIS_IN_PROGRESS = "ANALYSIS_IN_PROGRESS"
    ANALYZED = "ANALYZED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"
    ACTIVE = "ACTIVE"


class RequirementStatus(StrEnum):
    """Progress of one requirement. Independent from ``AssignmentStatus``."""

    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


class RequirementType(StrEnum):
    FUNCTIONAL = "FUNCTIONAL"
    TECHNICAL = "TECHICAL"
    DESIGN = "DESIGN"
    DOCUMENTATION = "DOCUMENTATION"
    CONSTRAINT = "CONSTRAINT"
    PERFORMANCE = "PERFORMANCE"
    SECURITY = "SECURITY"
    TESTING = "TESTING"
    OTHER = "OTHER"


class RequirementPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConstraintType(StrEnum):
    TECHNOLOGY = "TECHNOLOGY"
    TIME = "TIME"
    RESOURCE = "RESOURCE"
    FORMAT = "FORMAT"
    LANGUAGE = "LANGUAGE"
    LIBRARY = "LIBRARY"
    PLATFORM = "PLATFORM"
    ACADEMIC = "ACADEMIC"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"
    OTHER = "OTHER"


class ConstraintSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    IMPORTANT = "IMPORTANT"
    CRITICAL = "CRITICAL"


class DeliverableType(StrEnum):
    SOURCE_CODE = "SOURCE_CODE"
    DOCUMENT = "DOCUMENT"
    DATASET = "DATASET"
    PRESENTATION = "PRESENTATION"
    TEST_SUITE = "TEST_SUITE"
    VIDEO = "VIDEO"
    OTHER = "OTHER"


class DeliverableStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


class TechnologyCategory(StrEnum):
    LANGUAGE = "LANGUAGE"
    FRAMEWORK = "FRAMEWORK"
    DATABASE = "DATABASE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    LIBRARY = "LIBRARY"
    TOOL = "TOOL"
    PROTOCOL = "PROTOCOL"
    OTHER = "OTHER"


class CompletenessCheckStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class WorkspaceRole(StrEnum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"


class NotificationType(StrEnum):
    INFO = "INFO"
    DEADLINE = "DEADLINE"
    SYSTEM = "SYSTEM"


# ---------------------------------------------------------------------------
# Phase 3: universal academic assignment intelligence
#
# Assignment type and academic domain are deliberately separate, independent
# axes. A mathematical proof written in a computer science course is
# ``MATHEMATICAL_PROOF`` + ``COMPUTER_SCIENCE``; nothing here presumes that an
# assignment is a programming project.
# ---------------------------------------------------------------------------


class AssignmentType(StrEnum):
    """What kind of academic work an assignment asks for. Multiple allowed.

    Extensible by design: adding a value never requires changing the analysis
    model, because analyses carry the raw value and validate against this enum
    only where a supported set is required.
    """

    PROGRAMMING = "PROGRAMMING"
    PROBLEM_SET = "PROBLEM_SET"
    MATHEMATICAL_PROOF = "MATHEMATICAL_PROOF"
    ESSAY = "ESSAY"
    RESEARCH = "RESEARCH"
    LITERATURE_REVIEW = "LITERATURE_REVIEW"
    LAB_REPORT = "LAB_REPORT"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    PRESENTATION = "PRESENTATION"
    READING = "READING"
    LANGUAGE = "LANGUAGE"
    DESIGN = "DESIGN"
    GROUP_PROJECT = "GROUP_PROJECT"
    REPORT = "REPORT"
    OTHER = "OTHER"


class AcademicDomain(StrEnum):
    """The discipline an assignment belongs to. Extensible by design."""

    MATHEMATICS = "MATHEMATICS"
    COMPUTER_SCIENCE = "COMPUTER_SCIENCE"
    PHYSICS = "PHYSICS"
    CHEMISTRY = "CHEMISTRY"
    BIOLOGY = "BIOLOGY"
    ENGINEERING = "ENGINEERING"
    ECONOMICS = "ECONOMICS"
    BUSINESS = "BUSINESS"
    SOCIAL_SCIENCES = "SOCIAL_SCIENCES"
    HUMANITIES = "HUMANITIES"
    LANGUAGES = "LANGUAGES"
    ART_AND_DESIGN = "ART_AND_DESIGN"
    OTHER = "OTHER"


class RequirementCategory(StrEnum):
    """Generic, domain-agnostic category for a normalized requirement.

    ``TECHNICAL`` is allowed but is only one of many categories, so a
    programming requirement can never dominate the model.
    """

    CONTENT = "CONTENT"
    PROCESS = "PROCESS"
    DELIVERABLE = "DELIVERABLE"
    QUALITY = "QUALITY"
    FORMAT = "FORMAT"
    ACADEMIC = "ACADEMIC"
    METHODOLOGY = "METHODOLOGY"
    EVALUATION = "EVALUATION"
    PRESENTATION = "PRESENTATION"
    TECHNICAL = "TECHNICAL"
    OTHER = "OTHER"


class AnalysisRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"


class AnalysisReviewStatus(StrEnum):
    """Where a human is in reviewing one AI analysis."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ClassificationSource(StrEnum):
    AI = "AI"
    USER = "USER"


class ClassificationKind(StrEnum):
    TYPE = "TYPE"
    DOMAIN = "DOMAIN"


class FindingKind(StrEnum):
    AMBIGUITY = "AMBIGUITY"
    CONTRADICTION = "CONTRADICTION"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    ASSUMPTION = "ASSUMPTION"
    RISK = "RISK"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    IMPORTANT = "IMPORTANT"
    CRITICAL = "CRITICAL"


class QuestionPriority(StrEnum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    OPTIONAL = "OPTIONAL"


class QuestionStatus(StrEnum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    DISMISSED = "DISMISSED"


class EvidenceSourceType(StrEnum):
    """Where an AI-derived conclusion can point back to.

    ``INFERENCE`` is the honest escape hatch: a conclusion with no source is
    recorded as an inference, never dressed up as evidence from the document.
    """

    TITLE = "TITLE"
    DESCRIPTION = "DESCRIPTION"
    COURSE = "COURSE"
    REQUIREMENT = "REQUIREMENT"
    CONSTRAINT = "CONSTRAINT"
    CRITERION = "CRITERION"
    DELIVERABLE = "DELIVERABLE"
    RESOURCE = "RESOURCE"
    USER_NOTE = "USER_NOTE"
    INFERENCE = "INFERENCE"


class ScopeLevel(StrEnum):
    """A coarse, honest estimate. Never a claim of precise effort."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class SourceKind(StrEnum):
    """Provenance shown to the student: explicit vs inferred vs missing."""

    EXPLICIT = "EXPLICIT"
    AI_INFERENCE = "AI_INFERENCE"
    UNCERTAIN = "UNCERTAIN"
    MISSING = "MISSING"


class AuditEventType(StrEnum):
    USER_REGISTERED = "USER_REGISTERED"
    ASSIGNMENT_CREATED = "ASSIGNMENT_CREATED"
    ASSIGNMENT_UPDATED = "ASSIGNMENT_UPDATED"
    ASSIGNMENT_DELETED = "ASSIGNMENT_DELETED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"
    COURSE_CREATED = "COURSE_CREATED"
    COURSE_UPDATED = "COURSE_UPDATED"
    COURSE_DELETED = "COURSE_DELETED"
    REQUIREMENT_CREATED = "REQUIREMENT_CREATED"
    REQUIREMENT_UPDATED = "REQUIREMENT_UPDATED"
    REQUIREMENT_DELETED = "REQUIREMENT_DELETED"
    REQUIREMENT_COMPLETED = "REQUIREMENT_COMPLETED"
    CONSTRAINT_CREATED = "CONSTRAINT_CREATED"
    CONSTRAINT_UPDATED = "CONSTRAINT_UPDATED"
    CONSTRAINT_DELETED = "CONSTRAINT_DELETED"
    CRITERION_CREATED = "CRITERION_CREATED"
    CRITERION_UPDATED = "CRITERION_UPDATED"
    CRITERION_DELETED = "CRITERION_DELETED"
    DELIVERABLE_CREATED = "DELIVERABLE_CREATED"
    DELIVERABLE_UPDATED = "DELIVERABLE_UPDATED"
    DELIVERABLE_DELETED = "DELIVERABLE_DELETED"
    TECHNOLOGY_ADDED = "TECHNOLOGY_ADDED"
    TECHNOLOGY_REMOVED = "TECHNOLOGY_REMOVED"
    TAG_ADDED = "TAG_ADDED"
    TAG_REMOVED = "TAG_REMOVED"
    SPECIFICATION_VALIDATED = "SPECIFICATION_VALIDATED"
    SPECIFICATION_MARKED_READY = "SPECIFICATION_MARKED_READY"
    SPECIFICATION_INVALIDATED = "SPECIFICATION_INVALIDATED"
    SPECIFICATION_VERSION_CREATED = "SPECIFICATION_VERSION_CREATED"
    # Phase 3: assignment analysis lifecycle. Recorded on the audit trail so a
    # run is observable and the assignment activity feed tells the story.
    ASSIGNMENT_ANALYSIS_REQUESTED = "ASSIGNMENT_ANALYSIS_REQUESTED"
    ASSIGNMENT_ANALYSIS_STARTED = "ASSIGNMENT_ANALYSIS_STARTED"
    ASSIGNMENT_ANALYSIS_COMPLETED = "ASSIGNMENT_ANALYSIS_COMPLETED"
    ASSIGNMENT_ANALYSIS_FAILED = "ASSIGNMENT_ANALYSIS_FAILED"
    ASSIGNMENT_ANALYSIS_REVIEWED = "ASSIGNMENT_ANALYSIS_REVIEWED"
    ASSIGNMENT_ANALYSIS_REJECTED = "ASSIGNMENT_ANALYSIS_REJECTED"
    ASSIGNMENT_ANALYSIS_MARKED_STALE = "ASSIGNMENT_ANALYSIS_MARKED_STALE"
    ASSIGNMENT_CLASSIFICATION_CORRECTED = "ASSIGNMENT_CLASSIFICATION_CORRECTED"
    ASSIGNMENT_ANALYSIS_QUESTION_ANSWERED = "ASSIGNMENT_ANALYSIS_QUESTION_ANSWERED"
