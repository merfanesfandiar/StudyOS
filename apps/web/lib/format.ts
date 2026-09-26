import type {
  AcademicDomain,
  AssignmentStatus,
  AssignmentType,
  CheckStatus,
  ClientSettableStatus,
  ConstraintSeverity,
  ConstraintType,
  DeliverableStatus,
  DeliverableType,
  FindingSeverity,
  QuestionPriority,
  RequirementCategory,
  RequirementPriority,
  RequirementStatus,
  RequirementType,
  ScopeLevel,
  SourceKind,
  TechnologyCategory,
} from "./types";
import type { MessageKey } from "./i18n/messages";
import type { Translate } from "./i18n/translate";

export function formatDate(value: string | null | undefined): string {
  if (!value) return "No deadline";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateOnly(value: string | null | undefined): string {
  if (!value) return "No deadline";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

/**
 * A status value to the key that labels it, rather than to a display string.
 *
 * The display strings used to live here, which meant every caller got English
 * regardless of the reader's language and this module had to be told which
 * locale to use. Returning the key instead lets the caller's translator resolve
 * it, and keeps one mapping of enum to label.
 */
const STATUS_KEYS: Record<AssignmentStatus, MessageKey> = {
  DRAFT: "status.draft",
  INCOMPLETE: "filters.incomplete",
  READY_FOR_ANALYSIS: "status.ready_for_analysis",
  ANALYSIS_IN_PROGRESS: "status.analysisInProgress",
  ANALYZED: "filters.analyzed",
  COMPLETED: "status.completed",
  ARCHIVED: "status.archived",
  ACTIVE: "status.active",
};

export function statusKey(status: AssignmentStatus): MessageKey {
  return STATUS_KEYS[status] ?? ("status.unknown" as MessageKey);
}

/** Translate a status, falling back to the raw value for an unknown enum member. */
export function statusLabel(t: Translate, status: AssignmentStatus): string {
  const key = STATUS_KEYS[status];
  return key ? t(key) : status;
}

/**
 * Requirement statuses are a separate enum from assignment statuses, with
 * `TODO` and `VERIFIED` having no assignment equivalent. They get their own map
 * rather than being squeezed into `STATUS_KEYS`, so a future member of either
 * union fails to compile instead of silently rendering as the other kind of
 * label.
 */
/** Only these states may be set from the UI; the rest need the readiness gate. */
export const CLIENT_SETTABLE_STATUSES: readonly ClientSettableStatus[] = [
  "DRAFT",
  "INCOMPLETE",
  "COMPLETED",
  "ARCHIVED",
];

export const CHECK_LABELS: Record<CheckStatus, string> = {
  PASS: "Ready",
  WARNING: "Check",
  FAIL: "Missing",
};

const REQUIREMENT_TYPES_KEYS: Record<RequirementType, MessageKey> = {
  FUNCTIONAL: "enum.requirementType.functional",
  TECHNICAL: "enum.requirementType.technical",
  DESIGN: "enum.requirementType.design",
  DOCUMENTATION: "enum.requirementType.documentation",
  CONSTRAINT: "enum.requirementType.constraint",
  PERFORMANCE: "enum.requirementType.performance",
  SECURITY: "enum.requirementType.security",
  TESTING: "enum.requirementType.testing",
  OTHER: "enum.requirementType.other",
};

const CONSTRAINT_TYPES_KEYS: Record<ConstraintType, MessageKey> = {
  TECHNOLOGY: "enum.constraintType.technology",
  TIME: "enum.constraintType.time",
  RESOURCE: "enum.constraintType.resource",
  FORMAT: "enum.constraintType.format",
  LANGUAGE: "enum.constraintType.language",
  LIBRARY: "enum.constraintType.library",
  PLATFORM: "enum.constraintType.platform",
  ACADEMIC: "enum.constraintType.academic",
  SECURITY: "enum.constraintType.security",
  PERFORMANCE: "enum.constraintType.performance",
  OTHER: "enum.constraintType.other",
};

const CONSTRAINT_SEVERITIES_KEYS: Record<ConstraintSeverity, MessageKey> = {
  INFO: "enum.constraintSeverity.info",
  WARNING: "enum.constraintSeverity.warning",
  IMPORTANT: "enum.constraintSeverity.important",
  CRITICAL: "enum.constraintSeverity.critical",
};

const DELIVERABLE_TYPES_KEYS: Record<DeliverableType, MessageKey> = {
  SOURCE_CODE: "enum.deliverableType.sourceCode",
  DOCUMENT: "enum.deliverableType.document",
  DATASET: "enum.deliverableType.dataset",
  PRESENTATION: "enum.deliverableType.presentation",
  TEST_SUITE: "enum.deliverableType.testSuite",
  VIDEO: "enum.deliverableType.video",
  OTHER: "enum.deliverableType.other",
};

const DELIVERABLE_STATUSES_KEYS: Record<DeliverableStatus, MessageKey> = {
  PENDING: "enum.deliverableStatus.pending",
  IN_PROGRESS: "enum.deliverableStatus.inProgress",
  COMPLETED: "enum.deliverableStatus.completed",
  VERIFIED: "enum.deliverableStatus.verified",
};

const REQUIREMENT_STATUSES_KEYS: Record<RequirementStatus, MessageKey> = {
  TODO: "enum.requirementStatus.todo",
  IN_PROGRESS: "enum.requirementStatus.inProgress",
  BLOCKED: "enum.requirementStatus.blocked",
  COMPLETED: "enum.requirementStatus.completed",
  VERIFIED: "enum.requirementStatus.verified",
};

const PRIORITIES_KEYS: Record<RequirementPriority, MessageKey> = {
  LOW: "enum.requirementPriority.low",
  MEDIUM: "enum.requirementPriority.medium",
  HIGH: "enum.requirementPriority.high",
  CRITICAL: "enum.requirementPriority.critical",
};

const TECHNOLOGY_CATEGORIES_KEYS: Record<TechnologyCategory, MessageKey> = {
  LANGUAGE: "enum.technologyCategory.language",
  FRAMEWORK: "enum.technologyCategory.framework",
  DATABASE: "enum.technologyCategory.database",
  INFRASTRUCTURE: "enum.technologyCategory.infrastructure",
  LIBRARY: "enum.technologyCategory.library",
  TOOL: "enum.technologyCategory.tool",
  PROTOCOL: "enum.technologyCategory.protocol",
  OTHER: "enum.technologyCategory.other",
};

export function humanize(key: string): string {
  return key
    .toLowerCase()
    .split("_")
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" ");
}

export function requirementTypeLabel(t: Translate, value: RequirementType): string {
  return t(REQUIREMENT_TYPES_KEYS[value]) || value;
}
export function constraintTypeLabel(t: Translate, value: ConstraintType): string {
  return t(CONSTRAINT_TYPES_KEYS[value]) || value;
}
export function constraintSeverityLabel(t: Translate, value: ConstraintSeverity): string {
  return t(CONSTRAINT_SEVERITIES_KEYS[value]) || value;
}
export function deliverableTypeLabel(t: Translate, value: DeliverableType): string {
  return t(DELIVERABLE_TYPES_KEYS[value]) || value;
}
export function deliverableStatusLabel(t: Translate, value: DeliverableStatus): string {
  return t(DELIVERABLE_STATUSES_KEYS[value]) || value;
}
/** Catalogue-backed, like `statusLabel`, for the same reason. */
export function requirementStatusLabel(t: Translate, value: RequirementStatus): string {
  return t(REQUIREMENT_STATUSES_KEYS[value]) || value;
}
export function priorityLabel(t: Translate, value: RequirementPriority): string {
  return t(PRIORITIES_KEYS[value]) || value;
}
export function technologyCategoryLabel(t: Translate, value: TechnologyCategory): string {
  return t(TECHNOLOGY_CATEGORIES_KEYS[value]) || value;
}

export const REQUIREMENT_TYPE_OPTIONS = Object.keys(REQUIREMENT_TYPES_KEYS) as RequirementType[];
export const CONSTRAINT_TYPE_OPTIONS = Object.keys(CONSTRAINT_TYPES_KEYS) as ConstraintType[];
export const CONSTRAINT_SEVERITY_OPTIONS = Object.keys(CONSTRAINT_SEVERITIES_KEYS) as ConstraintSeverity[];
export const DELIVERABLE_TYPE_OPTIONS = Object.keys(DELIVERABLE_TYPES_KEYS) as DeliverableType[];
export const DELIVERABLE_STATUS_OPTIONS = Object.keys(DELIVERABLE_STATUSES_KEYS) as DeliverableStatus[];
export const REQUIREMENT_STATUS_OPTIONS = Object.keys(REQUIREMENT_STATUSES_KEYS) as RequirementStatus[];
export const PRIORITY_OPTIONS = Object.keys(PRIORITIES_KEYS) as RequirementPriority[];
export const TECHNOLOGY_CATEGORY_OPTIONS = Object.keys(TECHNOLOGY_CATEGORIES_KEYS) as TechnologyCategory[];

// ---------------------------------------------------------------------------
// Phase 3 analysis taxonomy
// ---------------------------------------------------------------------------

const ASSIGNMENT_TYPES: Record<AssignmentType, string> = {
  PROGRAMMING: "Programming",
  PROBLEM_SET: "Problem set",
  MATHEMATICAL_PROOF: "Mathematical proof",
  ESSAY: "Essay",
  RESEARCH: "Research",
  LITERATURE_REVIEW: "Literature review",
  LAB_REPORT: "Lab report",
  DATA_ANALYSIS: "Data analysis",
  PRESENTATION: "Presentation",
  READING: "Reading",
  LANGUAGE: "Language work",
  DESIGN: "Design",
  GROUP_PROJECT: "Group project",
  REPORT: "Report",
  OTHER: "Other",
};

const ACADEMIC_DOMAINS: Record<AcademicDomain, string> = {
  MATHEMATICS: "Mathematics",
  COMPUTER_SCIENCE: "Computer science",
  PHYSICS: "Physics",
  CHEMISTRY: "Chemistry",
  BIOLOGY: "Biology",
  ENGINEERING: "Engineering",
  ECONOMICS: "Economics",
  BUSINESS: "Business",
  SOCIAL_SCIENCES: "Social sciences",
  HUMANITIES: "Humanities",
  LANGUAGES: "Languages",
  ART_AND_DESIGN: "Art and design",
  OTHER: "Other",
};

const REQUIREMENT_CATEGORIES: Record<RequirementCategory, string> = {
  CONTENT: "Content",
  PROCESS: "Process",
  DELIVERABLE: "Deliverable",
  QUALITY: "Quality",
  FORMAT: "Format",
  ACADEMIC: "Academic",
  METHODOLOGY: "Methodology",
  EVALUATION: "Evaluation",
  PRESENTATION: "Presentation",
  TECHNICAL: "Technical",
  OTHER: "Other",
};

const FINDING_SEVERITIES: Record<FindingSeverity, string> = {
  INFO: "Info",
  WARNING: "Warning",
  IMPORTANT: "Important",
  CRITICAL: "Critical",
};

const QUESTION_PRIORITIES: Record<QuestionPriority, string> = {
  CRITICAL: "Critical",
  IMPORTANT: "Important",
  OPTIONAL: "Optional",
};

const SCOPE_LEVELS: Record<ScopeLevel, string> = {
  NOT_APPLICABLE: "Not applicable",
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
  UNKNOWN: "Unknown",
};

/**
 * Provenance, phrased the way a student needs to read it. `EXPLICIT` is the
 * only kind backed by the brief itself; the rest are the model's word.
 */
const SOURCE_KIND_LABELS: Record<SourceKind, string> = {
  EXPLICIT: "Stated in the brief",
  AI_INFERENCE: "Inferred by AI",
  UNCERTAIN: "Uncertain",
  MISSING: "Not stated",
};

const SOURCE_KIND_SHORT: Record<SourceKind, string> = {
  EXPLICIT: "Explicit",
  AI_INFERENCE: "AI inference",
  UNCERTAIN: "Uncertain",
  MISSING: "Missing",
};

export const assignmentTypeLabel = (value: AssignmentType) => ASSIGNMENT_TYPES[value] ?? value;
export const academicDomainLabel = (value: AcademicDomain) => ACADEMIC_DOMAINS[value] ?? value;
export const requirementCategoryLabel = (value: RequirementCategory) =>
  REQUIREMENT_CATEGORIES[value] ?? value;
export const findingSeverityLabel = (value: FindingSeverity) =>
  FINDING_SEVERITIES[value] ?? value;
export const questionPriorityLabel = (value: QuestionPriority) =>
  QUESTION_PRIORITIES[value] ?? value;
export const scopeLevelLabel = (value: ScopeLevel) => SCOPE_LEVELS[value] ?? value;
export const sourceKindLabel = (value: SourceKind) => SOURCE_KIND_LABELS[value] ?? value;
export const sourceKindShort = (value: SourceKind) => SOURCE_KIND_SHORT[value] ?? value;

export const ASSIGNMENT_TYPE_OPTIONS = Object.keys(ASSIGNMENT_TYPES) as AssignmentType[];
export const ACADEMIC_DOMAIN_OPTIONS = Object.keys(ACADEMIC_DOMAINS) as AcademicDomain[];
export const REQUIREMENT_CATEGORY_OPTIONS = Object.keys(
  REQUIREMENT_CATEGORIES,
) as RequirementCategory[];

/**
 * Confidence is never certainty, so it renders as a word plus the number. The
 * thresholds are deliberately blunt: anything under 0.5 is not worth leaning on.
 */
export function confidenceLabel(confidence: number): string {
  if (confidence >= 0.85) return "High";
  if (confidence >= 0.6) return "Moderate";
  if (confidence > 0) return "Low";
  return "Not reported";
}

export function formatConfidence(confidence: number): string {
  if (confidence <= 0) return "confidence not reported";
  return `${Math.round(confidence * 100)}% confidence`;
}

/** Only the stated provenance is safe to plan against. */
export function isExplicit(source: SourceKind): boolean {
  return source === "EXPLICIT";
}

/** Weights arrive as decimal strings; show them with a percent sign. */
export function formatWeight(value: string | number): string {
  const text = String(value);
  // Only trim zeros that follow a decimal point, so "100" stays "100".
  const trimmed = text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
  return `${trimmed}%`;
}

export function toLocalDateTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function toUtcDateTime(value: string): string | null {
  if (!value) return null;
  return new Date(value).toISOString();
}
