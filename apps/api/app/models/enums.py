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

    # Phase 4: planning lifecycle. Recorded so a plan's history is answerable
    # without reading the run table, and so the assignment activity feed can tell
    # the student who changed what.
    PLAN_GENERATED = "PLAN_GENERATED"
    PLAN_GENERATION_FAILED = "PLAN_GENERATION_FAILED"
    PLAN_REGENERATED = "PLAN_REGENERATED"
    PLAN_EDITED = "PLAN_EDITED"
    PLAN_TASK_UPDATED = "PLAN_TASK_UPDATED"
    PLAN_TASK_ADDED = "PLAN_TASK_ADDED"
    PLAN_TASK_DELETED = "PLAN_TASK_DELETED"
    PLAN_TASKS_REORDERED = "PLAN_TASKS_REORDERED"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_MARKED_STALE = "PLAN_MARKED_STALE"
    PLAN_PREFERENCES_UPDATED = "PLAN_PREFERENCES_UPDATED"


# ---------------------------------------------------------------------------
# Phase 4: the Academic Planning Engine.
#
# Planning vocabulary is deliberately academic-domain-agnostic. There is no
# "write_unit_test" or "run_experiment" task type: the same task graph has to
# serve a proof, a literature review and a programming project. Domain-specific
# wording is carried by the task title, description and acceptance criteria,
# which is where it belongs.
# ---------------------------------------------------------------------------


class PlanStatus(StrEnum):
    """Lifecycle of an academic work plan.

    A plan only becomes authoritative at ``APPROVED``. ``STALE`` is not a
    terminal verdict: it means the analysis the plan was built from has moved on,
    so the plan is still readable but must not be worked from until it is
    regenerated or re-approved against the current analysis.
    """

    DRAFT = "DRAFT"
    GENERATING = "GENERATING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"
    STALE = "STALE"


class AcademicTaskType(StrEnum):
    """What kind of academic work a task represents.

    Extensible on purpose. An unrecognised value from a future provider must
    degrade to ``OTHER`` rather than fail a run, so the stored column is a
    plain string and this enum is the vocabulary, not a database constraint.
    """

    READ = "READ"
    RESEARCH = "RESEARCH"
    UNDERSTAND = "UNDERSTAND"
    ANALYZE = "ANALYZE"
    SOLVE = "SOLVE"
    PROVE = "PROVE"
    WRITE = "WRITE"
    IMPLEMENT = "IMPLEMENT"
    EXPERIMENT = "EXPERIMENT"
    COLLECT_DATA = "COLLECT_DATA"
    ANALYZE_DATA = "ANALYZE_DATA"
    DESIGN = "DESIGN"
    REVIEW = "REVIEW"
    REVISE = "REVISE"
    PRACTICE = "PRACTICE"
    PRESENT = "PRESENT"
    VERIFY = "VERIFY"
    SUBMIT = "SUBMIT"
    OTHER = "OTHER"


class AcademicTaskStatus(StrEnum):
    """Student-owned progress on a single task.

    ``BLOCKED`` exists because "I cannot start this because a prerequisite is
    unfinished" is the single most common real state in a plan, and hiding it
    behind "not started" makes a dependency graph useless in practice.
    """

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class AcademicTaskPriority(StrEnum):
    """How urgently a task matters within the plan.

    Distinct from the assignment's own requirement priority. A task can be
    critical to the plan while addressing a low-priority requirement, and vice
    versa, so conflating them would lose real information.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EffortLevel(StrEnum):
    """Coarse effort band. Never a guarantee.

    The minute range on a task is an AI estimate and is labelled as one
    everywhere it surfaces. ``UNKNOWN`` is a real value rather than a zero:
    pretending an unknown estimate is small would quietly corrupt the schedule
    risk check.
    """

    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"
    UNKNOWN = "UNKNOWN"


class PlanningStyle(StrEnum):
    """How much structure the student wants generated.

    A presentation preference. It changes how the planner decomposes work, never
    which requirements are authoritative.
    """

    MINIMAL = "MINIMAL"
    BALANCED = "BALANCED"
    DETAILED = "DETAILED"


class GuidanceLevel(StrEnum):
    """How much explanation the planner attaches to each task."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SessionLength(StrEnum):
    """Preferred working-session length, used to size task chunks."""

    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    LONG = "LONG"


class AIMode(StrEnum):
    """The student's model-quality preference.

    ``AUTO`` delegates the choice to the router. The other three bias it. None of
    them can bypass validation, safety checks or human approval, which is why
    this is a preference and not a switch.
    """

    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP = "DEEP"
    AUTO = "AUTO"


class ModelTier(StrEnum):
    """Which of the two configured models a request was routed to.

    Named by capability, never by provider. The product must not leak vendor or
    model names into the domain layer or the default UI.
    """

    EFFICIENT = "EFFICIENT"
    ADVANCED = "ADVANCED"


class ComplexityLevel(StrEnum):
    """Normalised complexity of an assignment for routing and plan shaping."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class PlanningRunStatus(StrEnum):
    """Lifecycle of a single plan generation attempt.

    Mirrors ``AnalysisRunStatus`` so the two AI subsystems are auditable the
    same way: what was asked, which model answered, what it cost, and what
    failed.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PlanTrigger(StrEnum):
    """Why a plan version exists."""

    GENERATED = "GENERATED"
    REGENERATED = "REGENERATED"
    EDITED = "EDITED"
    APPROVED = "APPROVED"
