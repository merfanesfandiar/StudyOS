import type {
  AcademicDomain,
  AssignmentStatus,
  AssignmentType,
  CheckStatus,
  ClientSettableStatus,
  ConstraintSeverity,
  ConstraintType,
  DeliverableStatus,
  EvidenceSourceType,
  DeliverableType,
  FindingSeverity,
  QuestionPriority,
  QuestionStatus,
  RequirementCategory,
  RequirementPriority,
  RequirementStatus,
  RequirementType,
  ScopeLevel,
  SourceKind,
  TechnologyCategory,
} from "./types";
import type { MessageKey } from "./i18n/messages";
import { hasMessage, type Translate } from "./i18n/translate";

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

export const CHECK_LABELS: Record<CheckStatus, MessageKey> = {
  PASS: "readiness.checkStatus.ready",
  WARNING: "readiness.checkStatus.check",
  FAIL: "readiness.checkStatus.missing",
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

/**
 * A user-facing label for a value the server chose -- a readiness field, an
 * audit event type -- looked up in the catalogue and humanized if absent.
 *
 * The humanize fallback is the point, not a cop-out. These vocabularies are the
 * backend's, and it can add a member without this file changing; rendering
 * `CONSTRAINT_DELETED` as "Constraint deleted" is wrong but readable, and far
 * better than refusing to show the row. The lookup keeps the values we do know
 * about out of the fallback path entirely.
 *
 * Returns English for anything the catalogue lacks, which is the same trade the
 * translator already makes: a Persian page with one English word beats a Persian
 * page with a raw enum value.
 */
export function labelFor(t: Translate, namespace: string, key: string): string {
  const candidate = `${namespace}.${key}`;
  return hasMessage(candidate) ? t(candidate) : humanize(key);
}

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

const ASSIGNMENT_TYPES: Record<AssignmentType, MessageKey> = {
  PROGRAMMING: "analysis.assignmentType.programming",
  PROBLEM_SET: "analysis.assignmentType.problemSet",
  MATHEMATICAL_PROOF: "analysis.assignmentType.mathematicalProof",
  ESSAY: "analysis.assignmentType.essay",
  RESEARCH: "analysis.assignmentType.research",
  LITERATURE_REVIEW: "analysis.assignmentType.literatureReview",
  LAB_REPORT: "analysis.assignmentType.labReport",
  DATA_ANALYSIS: "analysis.assignmentType.dataAnalysis",
  PRESENTATION: "analysis.assignmentType.presentation",
  READING: "analysis.assignmentType.reading",
  LANGUAGE: "analysis.assignmentType.language",
  DESIGN: "analysis.assignmentType.design",
  GROUP_PROJECT: "analysis.assignmentType.groupProject",
  REPORT: "analysis.assignmentType.report",
  OTHER: "analysis.assignmentType.other",
};

const ACADEMIC_DOMAINS: Record<AcademicDomain, MessageKey> = {
  MATHEMATICS: "analysis.domain.mathematics",
  COMPUTER_SCIENCE: "analysis.domain.computerScience",
  PHYSICS: "analysis.domain.physics",
  CHEMISTRY: "analysis.domain.chemistry",
  BIOLOGY: "analysis.domain.biology",
  ENGINEERING: "analysis.domain.engineering",
  ECONOMICS: "analysis.domain.economics",
  BUSINESS: "analysis.domain.business",
  SOCIAL_SCIENCES: "analysis.domain.socialSciences",
  HUMANITIES: "analysis.domain.humanities",
  LANGUAGES: "analysis.domain.languages",
  ART_AND_DESIGN: "analysis.domain.artAndDesign",
  OTHER: "analysis.domain.other",
};

const REQUIREMENT_CATEGORIES: Record<RequirementCategory, MessageKey> = {
  CONTENT: "analysis.category.content",
  PROCESS: "analysis.category.process",
  DELIVERABLE: "analysis.category.deliverable",
  QUALITY: "analysis.category.quality",
  FORMAT: "analysis.category.format",
  ACADEMIC: "analysis.category.academic",
  METHODOLOGY: "analysis.category.methodology",
  EVALUATION: "analysis.category.evaluation",
  PRESENTATION: "analysis.category.presentation",
  TECHNICAL: "analysis.category.technical",
  OTHER: "analysis.category.other",
};

const FINDING_SEVERITIES: Record<FindingSeverity, MessageKey> = {
  INFO: "analysis.severity.info",
  WARNING: "analysis.severity.warning",
  IMPORTANT: "analysis.severity.important",
  CRITICAL: "analysis.severity.critical",
};

/**
 * Where inside the assignment a piece of evidence came from. A different
 * vocabulary from `SourceKind`, which answers "how much do I trust this": an
 * item can be EXPLICIT in the brief and still only an INFERENCE about it, and
 * the two used to be the same lookup, so a requirement citing the title was
 * labelled untrustworthy.
 */
const EVIDENCE_SOURCES: Record<EvidenceSourceType, MessageKey> = {
  TITLE: "analysis.evidenceSource.title",
  DESCRIPTION: "analysis.evidenceSource.description",
  COURSE: "analysis.evidenceSource.course",
  REQUIREMENT: "analysis.evidenceSource.requirement",
  CONSTRAINT: "analysis.evidenceSource.constraint",
  CRITERION: "analysis.evidenceSource.criterion",
  DELIVERABLE: "analysis.evidenceSource.deliverable",
  RESOURCE: "analysis.evidenceSource.resource",
  USER_NOTE: "analysis.evidenceSource.userNote",
  INFERENCE: "analysis.evidenceSource.inference",
};

export const evidenceSourceLabel = (t: Translate, value: EvidenceSourceType | string) =>
  value && Object.hasOwn(EVIDENCE_SOURCES, value)
    ? t(EVIDENCE_SOURCES[value as EvidenceSourceType])
    : value;

const QUESTION_STATUSES: Record<QuestionStatus, MessageKey> = {
  OPEN: "analysis.questionStatus.open",
  ANSWERED: "analysis.questionStatus.answered",
  DISMISSED: "analysis.questionStatus.dismissed",
};

const QUESTION_PRIORITIES: Record<QuestionPriority, MessageKey> = {
  CRITICAL: "analysis.priority.critical",
  IMPORTANT: "analysis.priority.important",
  OPTIONAL: "analysis.priority.optional",
};

const SCOPE_LEVELS: Record<ScopeLevel, MessageKey> = {
  NOT_APPLICABLE: "analysis.scope.notApplicable",
  LOW: "analysis.scope.low",
  MEDIUM: "analysis.scope.medium",
  HIGH: "analysis.scope.high",
  UNKNOWN: "analysis.scope.unknown",
};

/**
 * Provenance, phrased the way a student needs to read it. `EXPLICIT` is the
 * only kind backed by the brief itself; the rest are the model's word.
 */
const SOURCE_KIND_LABELS: Record<SourceKind, MessageKey> = {
  EXPLICIT: "analysis.source.explicit",
  AI_INFERENCE: "analysis.source.aiInference",
  UNCERTAIN: "analysis.source.uncertain",
  MISSING: "analysis.source.missing",
};

const SOURCE_KIND_SHORT: Record<SourceKind, MessageKey> = {
  EXPLICIT: "analysis.sourceShort.explicit",
  AI_INFERENCE: "analysis.sourceShort.aiInference",
  UNCERTAIN: "analysis.sourceShort.uncertain",
  MISSING: "analysis.sourceShort.missing",
};

/**
 * Every label here falls back to the raw value rather than an empty string, so a
 * taxonomy member the backend adds before the catalogue catches up renders as
 * `NEW_MEMBER` instead of a blank. An untranslated token is a smaller defect than
 * a missing one, and it is greppable.
 */
export const assignmentTypeLabel = (t: Translate, value: AssignmentType) =>
  value ? t(ASSIGNMENT_TYPES[value] ?? "analysis.assignmentType.other") : value;
export const academicDomainLabel = (t: Translate, value: AcademicDomain) =>
  value ? t(ACADEMIC_DOMAINS[value] ?? "analysis.domain.other") : value;
export const requirementCategoryLabel = (t: Translate, value: RequirementCategory) =>
  value ? t(REQUIREMENT_CATEGORIES[value] ?? "analysis.category.other") : value;
export const findingSeverityLabel = (t: Translate, value: FindingSeverity) =>
  value ? t(FINDING_SEVERITIES[value] ?? "analysis.severity.info") : value;
export const questionStatusLabel = (t: Translate, value: QuestionStatus) =>
  value ? t(QUESTION_STATUSES[value] ?? "analysis.questionStatus.open") : value;
export const questionPriorityLabel = (t: Translate, value: QuestionPriority) =>
  value ? t(QUESTION_PRIORITIES[value] ?? "analysis.priority.optional") : value;
export const scopeLevelLabel = (t: Translate, value: ScopeLevel) =>
  value ? t(SCOPE_LEVELS[value] ?? "analysis.scope.unknown") : value;
export const sourceKindLabel = (t: Translate, value: SourceKind) =>
  value ? t(SOURCE_KIND_LABELS[value] ?? "analysis.source.uncertain") : value;
export const sourceKindShort = (t: Translate, value: SourceKind) =>
  value ? t(SOURCE_KIND_SHORT[value] ?? "analysis.sourceShort.uncertain") : value;

export const ASSIGNMENT_TYPE_OPTIONS = Object.keys(ASSIGNMENT_TYPES) as AssignmentType[];
export const ACADEMIC_DOMAIN_OPTIONS = Object.keys(ACADEMIC_DOMAINS) as AcademicDomain[];
export const REQUIREMENT_CATEGORY_OPTIONS = Object.keys(
  REQUIREMENT_CATEGORIES,
) as RequirementCategory[];

/**
 * Confidence is never certainty, so it renders as a word plus the number. The
 * thresholds are deliberately blunt: anything under 0.5 is not worth leaning on.
 */
export function confidenceLabel(t: Translate, confidence: number): string {
  if (confidence >= 0.85) return t("analysis.confidence.high");
  if (confidence >= 0.6) return t("analysis.confidence.moderate");
  if (confidence > 0) return t("analysis.confidence.low");
  return t("analysis.confidence.none");
}

export function formatConfidence(t: Translate, confidence: number): string {
  if (confidence <= 0) return t("analysis.confidenceUnreported");
  return t("analysis.confidencePct", { pct: Math.round(confidence * 100) });
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
