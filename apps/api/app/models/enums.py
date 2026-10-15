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
    #: Non-negotiable. A brief that says "must be 12 pages" or "must cite five
    #: peer-reviewed sources" is this, and it is distinct from urgency: a
    #: non-negotiable constraint can still be due next week. Added because the
    #: planner already tested for ``HARD`` when deciding whether to warn about
    #: limiting constraints, so a MUST-style constraint could never raise the
    #: warning its own code path was written to raise.
    HARD = "HARD"
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
    #: Recorded before the provider call so an attempt that never completes is
    #: still attributable to a request and a tier.
    PLAN_REQUESTED = "PLAN_REQUESTED"
    PLAN_REGENERATION_REQUESTED = "PLAN_REGENERATION_REQUESTED"
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

    # Phase 5: the agent runtime lifecycle. Recorded for the same reason as the
    # planner rows: a run must be attributable to a request, a user and a plan
    # version even when it never completes.
    AGENT_RUN_CREATED = "AGENT_RUN_CREATED"
    AGENT_RUN_STARTED = "AGENT_RUN_STARTED"
    AGENT_RUN_PAUSED = "AGENT_RUN_PAUSED"
    AGENT_RUN_RESUMED = "AGENT_RUN_RESUMED"
    AGENT_RUN_CANCELLED = "AGENT_RUN_CANCELLED"
    AGENT_RUN_COMPLETED = "AGENT_RUN_COMPLETED"
    AGENT_RUN_FAILED = "AGENT_RUN_FAILED"
    AGENT_RUN_RETRIED = "AGENT_RUN_RETRIED"
    AGENT_TASK_COMPLETED = "AGENT_TASK_COMPLETED"
    AGENT_TASK_FAILED = "AGENT_TASK_FAILED"
    AGENT_TASK_BLOCKED = "AGENT_TASK_BLOCKED"
    AGENT_CHECKPOINT_CREATED = "AGENT_CHECKPOINT_CREATED"
    AGENT_CHECKPOINT_RESOLVED = "AGENT_CHECKPOINT_RESOLVED"
    AGENT_ARTIFACT_CREATED = "AGENT_ARTIFACT_CREATED"
    AGENT_ARTIFACT_REVISED = "AGENT_ARTIFACT_REVISED"


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


# ---------------------------------------------------------------------------
# Phase 5: the Professional Agent Runtime.
#
# Agent vocabulary is domain-agnostic on the same terms as the planner's. There
# is no "run_unit_tests" action or "code" executor: an action says what the
# runtime decided, and the executor says how this task kind is carried out. The
# only executor that implies an external capability is MOCK_TOOL, and even that
# runs in-process.
# ---------------------------------------------------------------------------


class AgentRunStatus(StrEnum):
    """Lifecycle of one agent run over an approved plan.

    The interesting states are the ones where the runtime is *not* moving:
    ``WAITING_FOR_USER`` is a deliberate hand-off, ``BLOCKED`` is a dependency
    or resource wall, and ``PAUSED`` is a student decision. Keeping them apart
    matters because they need different UI copy and different resume rules.
    """

    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentAction(StrEnum):
    """The closed set of decisions the runtime may take.

    A model may not invent an action. Anything outside this vocabulary is
    rejected at the schema layer before it can reach the database, which is what
    keeps "the model decided something" from meaning "the model decided anything".

    ``CALL_TOOL`` is the one action that hands control back to the runtime *before*
    the step finishes: the model names a tool from the registry and the runtime
    invokes it under ``ToolRegistry.assert_permitted``. Its result is either fed
    back into a bounded re-ask or applied directly (draft persisted, checkpoint
    opened).
    """

    EXECUTE_TASK = "EXECUTE_TASK"
    ASK_USER = "ASK_USER"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    CREATE_ARTIFACT = "CREATE_ARTIFACT"
    UPDATE_ARTIFACT = "UPDATE_ARTIFACT"
    REVIEW_RESULT = "REVIEW_RESULT"
    RETRY_TASK = "RETRY_TASK"
    MARK_BLOCKED = "MARK_BLOCKED"
    COMPLETE_TASK = "COMPLETE_TASK"
    PAUSE_RUN = "PAUSE_RUN"
    CALL_TOOL = "CALL_TOOL"


class AgentExecutorKind(StrEnum):
    """How a task kind is executed.

    One interface, several strategies. ``MOCK_TOOL`` is the deterministic
    executor the tests drive; the rest resolve to provider-backed strategies in
    Phase 5 and remain the extension point later workers plug into.
    """

    REASONING = "REASONING"
    WRITING = "WRITING"
    ANALYSIS = "ANALYSIS"
    RESEARCH = "RESEARCH"
    CALCULATION = "CALCULATION"
    PLANNING = "PLANNING"
    ARTIFACT = "ARTIFACT"
    MOCK_TOOL = "MOCK_TOOL"


class AgentExecutionStatus(StrEnum):
    """Outcome of one attempt at one task."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    SKIPPED = "SKIPPED"


class AgentArtifactType(StrEnum):
    """What an artifact holds.

    ``CODE`` exists as a type, not as a capability: the runtime may draft code
    as text without ever executing it. See ``agent-runtime.md`` for why that
    distinction is load-bearing.
    """

    TEXT = "TEXT"
    MARKDOWN = "MARKDOWN"
    REPORT = "REPORT"
    OUTLINE = "OUTLINE"
    SOLUTION = "SOLUTION"
    CALCULATION = "CALCULATION"
    PROOF_DRAFT = "PROOF_DRAFT"
    PRESENTATION = "PRESENTATION"
    RESEARCH_NOTES = "RESEARCH_NOTES"
    CODE = "CODE"
    DOCUMENT = "DOCUMENT"


class AgentArtifactStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class AgentCheckpointType(StrEnum):
    """Why the runtime stopped and handed control back to the student."""

    CLARIFICATION = "CLARIFICATION"
    APPROVAL = "APPROVAL"
    REVIEW = "REVIEW"
    DECISION = "DECISION"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    PERMISSION = "PERMISSION"


class AgentCheckpointStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AgentEventType(StrEnum):
    """The durable, user-safe activity stream.

    This is what the activity panel renders. It is deliberately *not* a reasoning
    trace: every value here is something a person can read and learn from.
    """

    RUN_CREATED = "RUN_CREATED"
    RUN_STARTED = "RUN_STARTED"
    TASK_SELECTED = "TASK_SELECTED"
    CONTEXT_BUILT = "CONTEXT_BUILT"
    MODEL_SELECTED = "MODEL_SELECTED"
    DECISION_RECORDED = "DECISION_RECORDED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_RETRIED = "TASK_RETRIED"
    TASK_BLOCKED = "TASK_BLOCKED"
    TASK_SKIPPED = "TASK_SKIPPED"
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    ARTIFACT_UPDATED = "ARTIFACT_UPDATED"
    CHECKPOINT_REQUESTED = "CHECKPOINT_REQUESTED"
    CHECKPOINT_RESOLVED = "CHECKPOINT_RESOLVED"
    RUN_PAUSED = "RUN_PAUSED"
    RUN_RESUMED = "RUN_RESUMED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"
    RUN_RECOVERED = "RUN_RECOVERED"
    WORKER_SELECTED = "WORKER_SELECTED"
    TOOL_SELECTED = "TOOL_SELECTED"
    TOOL_INVOCATION_STARTED = "TOOL_INVOCATION_STARTED"
    TOOL_INVOCATION_COMPLETED = "TOOL_INVOCATION_COMPLETED"
    TOOL_INVOCATION_FAILED = "TOOL_INVOCATION_FAILED"
    TOOL_INVOKED = "TOOL_INVOKED"
    TOOL_BLOCKED = "TOOL_BLOCKED"


class AgentFailureCategory(StrEnum):
    """Why an attempt failed, in terms the recovery policy can act on.

    Retryability is a property of the category, not of the message, so backoff
    and give-up decisions are testable without parsing English.
    """

    TRANSIENT_PROVIDER = "TRANSIENT_PROVIDER"
    RATE_LIMITED = "RATE_LIMITED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONTEXT_ERROR = "CONTEXT_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    #: The caller was not authorised at all, as distinct from being authorised but
    #: lacking a specific tool permission. Kept separate so the recovery policy can
    #: tell "you may not do this here" from "you may not do this yet".
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    #: A tool or provider did not answer within its timeout. Retryable with backoff,
    #: unlike a validation error, so it is its own category rather than a SYSTEM_ERROR.
    TIMEOUT = "TIMEOUT"
    #: A tool depended on something outside the run (a future provider) that failed.
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    #: A tool answered, but the result failed output validation or sanitisation.
    INVALID_RESULT = "INVALID_RESULT"
    #: A bounded resource (size, count, quota) was exhausted by a single call.
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    CANCELLED = "CANCELLED"


class AgentRunMode(StrEnum):
    """How much autonomy the student granted.

    ``SUPERVISED`` is the default and the only mode that may ask a checkpoint
    question mid-run. ``AUTONOMOUS`` runs to the next genuine wall.
    """

    SUPERVISED = "SUPERVISED"
    AUTONOMOUS = "AUTONOMOUS"


class AgentToolCategory(StrEnum):
    """What a tool is *for*. A grouping, never a permission grant.

    The category answers "which kind of academic work is this", so the UI can
    group the catalogue and a worker can be described as the sum of its
    categories. Whether a tool may run is decided by ``ToolPermission`` and
    ``AgentToolRisk``, not by this value: a tool in ``CODING`` is no more
    permitted than one in ``MATHEMATICS``; both are static and both are bounded.

    The vocabulary is deliberately academic and domain-neutral (``MATHEMATICS``,
    ``RESEARCH``, ``WRITING``, ``PRESENTATION``) rather than engineering-flavoured,
    so that a coding tool is one category among many and never the default shape
    of a capability. Adding a category is additive; nothing persists this value.
    """

    CORE = "CORE"
    DOCUMENT = "DOCUMENT"
    RESEARCH = "RESEARCH"
    MATHEMATICS = "MATHEMATICS"
    DATA = "DATA"
    WRITING = "WRITING"
    ANALYSIS = "ANALYSIS"
    COMPUTATION = "COMPUTATION"
    SEARCH = "SEARCH"
    PRESENTATION = "PRESENTATION"
    CODING = "CODING"
    FILE = "FILE"
    SYSTEM = "SYSTEM"
    OTHER = "OTHER"


class AgentToolRisk(StrEnum):
    """How dangerous a tool would be if its inputs were hostile.

    Risk is *enforceable*, not decoration: the runtime carries a maximum risk it
    will dispatch (:data:`~app.modules.agent.tools.MAX_TOOL_RISK`) and refuses any
    tool above it, so a ``HIGH`` or ``CRITICAL`` entry added to the catalogue is
    inert until a later phase deliberately raises the ceiling. That is what keeps
    "we will add sandboxing later" from being a comment a future tool ignores.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AgentToolAvailability(StrEnum):
    """Whether a tool may run in *this* deployment at all.

    Independent of permissions and risk. A tool can be registered, permitted and
    low-risk and still not be ``AVAILABLE``: ``REQUIRES_CONSENT`` means the
    student must opt in (the backend capability for Phase 8's consent UI),
    ``DISABLED`` means the operator turned it off, and ``UNSUPPORTED`` means the
    capability is deliberately absent from this phase. The runtime dispatches only
    ``AVAILABLE`` tools, so marking a tool anything else removes it from the model
    without deleting it from the catalogue.
    """

    AVAILABLE = "AVAILABLE"
    REQUIRES_CONSENT = "REQUIRES_CONSENT"
    DISABLED = "DISABLED"
    UNSUPPORTED = "UNSUPPORTED"


class AgentArtifactOwnership(StrEnum):
    """Who a stored artifact belongs to.

    The distinction is a guard, not a label. An artifact the student authored or
    uploaded is ``USER_OWNED`` and a tool may not silently replace it: the
    runtime writes a new revision instead of mutating student work in place.
    ``AGENT_OWNED`` is the default for anything the runtime drafted, and
    ``SYSTEM_GENERATED`` covers runtime bookkeeping. ``IMPORTED`` marks material
    brought in from outside the workspace.
    """

    USER_OWNED = "USER_OWNED"
    AGENT_OWNED = "AGENT_OWNED"
    SYSTEM_GENERATED = "SYSTEM_GENERATED"
    IMPORTED = "IMPORTED"


class AgentWorkerKind(StrEnum):
    """The specialized academic worker serving a task.

    A worker is the connection between the domain-agnostic task vocabulary and
    a bounded set of tools: a task of type ``PROVE`` is served by the
    ``MATHEMATICS`` worker, which may use the mathematics and core tools and
    nothing else. ``REASONING`` is the fallback for any task type without a
    dedicated worker, so a plan with an unfamiliar task still gets served by a
    worker that is safe rather than by nothing.
    """

    REASONING = "REASONING"
    MATHEMATICS = "MATHEMATICS"
    DATA = "DATA"
    WRITING = "WRITING"
    RESEARCH = "RESEARCH"
    CODE = "CODE"
    PRESENTATION = "PRESENTATION"


class AgentToolInvocationStatus(StrEnum):
    """Outcome of one recorded tool call.

    ``BLOCKED`` is recorded when the runtime refused the call (unregistered
    tool, permission missing, tool refused the arguments) — the run's observability
    keeps the attempt even though no work happened, so "why did this step fail"
    is answerable from the invocation log alone.
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class AgentToolStatus(StrEnum):
    """The structured status of a single tool result.

    Richer than ``ok``/``not ok`` because the runtime reacts differently to each.
    ``PARTIAL_SUCCESS`` advances with a warning. ``NEEDS_USER_INPUT`` is a request
    for a human, not a failure. ``RATE_LIMITED`` and ``UNAVAILABLE`` are
    retryable-later conditions the policy can back off from, and ``FAILED`` is
    the honest end state. The status is what a tool *returns*; how the invocation
    is recorded (``AgentToolInvocationStatus``) is derived from it.
    """

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def is_ok(self) -> bool:
        """True only for the statuses that produced a usable result."""
        return self in {AgentToolStatus.SUCCESS, AgentToolStatus.PARTIAL_SUCCESS}


# ---------------------------------------------------------------------------
# Phase 7: secure execution environment.
#
# The execution plane runs untrusted academic workloads (code, data analysis,
# numerical experiments) in isolated environments. These enums are the durable
# vocabulary the orchestrator, the sandbox backends and the API share, so a job's
# lifecycle, its isolation backend and its failure class are one shape everywhere
# rather than a string invented at each layer.
# ---------------------------------------------------------------------------


class ExecutionType(StrEnum):
    """Which approved runtime a job asks for.

    Deliberately not ``PYTHON``-only: the coding specialisation is one academic
    capability among many. A ``DATA_ANALYSIS`` or ``NUMERICAL_COMPUTATION`` job
    runs in the same isolated plane as a compiled one. The value selects an
    ``ExecutionAdapter``; a client may never name a host executable directly.
    """

    PYTHON = "PYTHON"
    JAVA = "JAVA"
    CPP = "CPP"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    NUMERICAL_COMPUTATION = "NUMERICAL_COMPUTATION"
    TEST_EXECUTION = "TEST_EXECUTION"
    BUILD = "BUILD"
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    OTHER = "OTHER"


class ExecutionResourceProfile(StrEnum):
    """A named, bounded resource policy. A profile is a ceiling, not an entitlement."""

    LIGHT_COMPUTATION = "LIGHT_COMPUTATION"
    STANDARD_CODE_EXECUTION = "STANDARD_CODE_EXECUTION"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    TEST_EXECUTION = "TEST_EXECUTION"
    BUILD_EXECUTION = "BUILD_EXECUTION"


class ExecutionJobStatus(StrEnum):
    """The lifecycle of one execution job.

    Kept explicit and persisted rather than implied by timestamps, because the
    distinctions the security model depends on — "queued" vs "running",
    "succeeded" vs "cleaned up" — are exactly the ones a boolean would erase.
    Terminal states are ``SUCCEEDED``, ``FAILED``, ``TIMED_OUT``, ``CANCELLED``,
    ``RESOURCE_LIMIT_EXCEEDED`` and ``REJECTED``. ``CLEANUP_PENDING`` is *not*
    terminal: a job can be complete while its environment is still being reclaimed.
    """

    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    COLLECTING_RESULTS = "COLLECTING_RESULTS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    CLEANUP_PENDING = "CLEANUP_PENDING"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ExecutionJobStatus.SUCCEEDED,
            ExecutionJobStatus.FAILED,
            ExecutionJobStatus.TIMED_OUT,
            ExecutionJobStatus.CANCELLED,
            ExecutionJobStatus.RESOURCE_LIMIT_EXCEEDED,
            ExecutionJobStatus.REJECTED,
        }


class ExecutionAttemptStatus(StrEnum):
    """The outcome of one attempt at a job."""

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExecutionCleanupStatus(StrEnum):
    """Whether the environment was reclaimed, tracked apart from the job result.

    A job that produced correct output but whose sandbox could not be destroyed
    is not a success with a footnote; it is an operationally significant state.
    Modelling cleanup separately is what stops "the process exited" from being
    reported as "the environment is gone".
    """

    PENDING = "PENDING"
    CLEANED = "CLEANED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionBackendKind(StrEnum):
    """The isolation mechanism a job was dispatched to.

    ``DISABLED`` is the safe default: with no backend configured, jobs are
    rejected rather than run on the host. ``DOCKER`` is the hardened rootless
    container path. The value is recorded so an operator can tell which boundary a
    given job actually ran behind.
    """

    DISABLED = "DISABLED"
    DOCKER = "DOCKER"
    MOCK = "MOCK"


class ExecutionFailureClass(StrEnum):
    """Why an execution failed, split by *where* the failure fell.

    The distinction drives retry policy: an infrastructure failure may be retried,
    user code may not be retried blindly (it may repeat side effects), and a
    timeout or resource exhaustion is a policy outcome rather than a bug.
    """

    INVALID_REQUEST = "INVALID_REQUEST"
    POLICY_REJECTED = "POLICY_REJECTED"
    ENVIRONMENT_UNAVAILABLE = "ENVIRONMENT_UNAVAILABLE"
    STARTUP_FAILED = "STARTUP_FAILED"
    COMPILE_FAILED = "COMPILE_FAILED"
    USER_CODE_FAILED = "USER_CODE_FAILED"
    TIMEOUT = "TIMEOUT"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    CANCELLED = "CANCELLED"


class ExecutionArtifactKind(StrEnum):
    """What a produced file is, so the UI can render it and retention can apply.

    ``SOURCE`` is input the student or agent supplied; the rest are produced by
    the run. ``RESULT`` is the primary structured output, ``CHART`` and
    ``DATA_OUTPUT`` are the common academic products, and ``SUMMARY`` is the
    runtime's own bounded narrative.
    """

    SOURCE = "SOURCE"
    RESULT = "RESULT"
    DATA_OUTPUT = "DATA_OUTPUT"
    CHART = "CHART"
    TEST_REPORT = "TEST_REPORT"
    DIAGNOSTICS = "DIAGNOSTICS"
    LOG = "LOG"
    SUMMARY = "SUMMARY"
    GENERATED_FILE = "GENERATED_FILE"
    OTHER = "OTHER"


class ExecutionEventType(StrEnum):
    """Security-relevant execution telemetry (§30).

    Stored on the append-only ``execution_events`` stream. These are operational
    and security events, never raw source or secrets; a normal compiler error is
    an ``EXECUTION_FAILED``, not a ``POLICY_VIOLATION_DETECTED``.
    """

    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    EXECUTION_REJECTED = "EXECUTION_REJECTED"
    EXECUTION_QUEUED = "EXECUTION_QUEUED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_TIMED_OUT = "EXECUTION_TIMED_OUT"
    EXECUTION_RESOURCE_LIMIT_EXCEEDED = "EXECUTION_RESOURCE_LIMIT_EXCEEDED"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    SANDBOX_CREATED = "SANDBOX_CREATED"
    SANDBOX_DESTROYED = "SANDBOX_DESTROYED"
    SANDBOX_CLEANUP_FAILED = "SANDBOX_CLEANUP_FAILED"
    POLICY_VIOLATION_DETECTED = "POLICY_VIOLATION_DETECTED"
