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

const STATUS_LABELS: Record<AssignmentStatus, string> = {
  DRAFT: "Draft",
  INCOMPLETE: "Incomplete",
  READY_FOR_ANALYSIS: "Ready for analysis",
  ANALYSIS_IN_PROGRESS: "Analysis in progress",
  ANALYZED: "Analyzed",
  COMPLETED: "Completed",
  ARCHIVED: "Archived",
  ACTIVE: "Active",
};

export function statusLabel(status: AssignmentStatus): string {
  return STATUS_LABELS[status] ?? status;
}

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

const REQUIREMENT_TYPES: Record<RequirementType, string> = {
  FUNCTIONAL: "Functional",
  TECHNICAL: "Technical",
  DESIGN: "Design",
  DOCUMENTATION: "Documentation",
  CONSTRAINT: "Constraint",
  PERFORMANCE: "Performance",
  SECURITY: "Security",
  TESTING: "Testing",
  OTHER: "Other",
};

const CONSTRAINT_TYPES: Record<ConstraintType, string> = {
  TECHNOLOGY: "Technology",
  TIME: "Time",
  RESOURCE: "Resource",
  FORMAT: "Format",
  LANGUAGE: "Language",
  LIBRARY: "Library",
  PLATFORM: "Platform",
  ACADEMIC: "Academic",
  SECURITY: "Security",
  PERFORMANCE: "Performance",
  OTHER: "Other",
};

const CONSTRAINT_SEVERITIES: Record<ConstraintSeverity, string> = {
  INFO: "Info",
  WARNING: "Warning",
  IMPORTANT: "Important",
  CRITICAL: "Critical",
};

const DELIVERABLE_TYPES: Record<DeliverableType, string> = {
  SOURCE_CODE: "Source code",
  DOCUMENT: "Document",
  DATASET: "Dataset",
  PRESENTATION: "Presentation",
  TEST_SUITE: "Test suite",
  VIDEO: "Video",
  OTHER: "Other",
};

const DELIVERABLE_STATUSES: Record<DeliverableStatus, string> = {
  PENDING: "Not started",
  IN_PROGRESS: "In progress",
  COMPLETED: "Submitted",
  VERIFIED: "Verified",
};

const REQUIREMENT_STATUSES: Record<RequirementStatus, string> = {
  TODO: "Not started",
  IN_PROGRESS: "In progress",
  BLOCKED: "Blocked",
  COMPLETED: "Completed",
  VERIFIED: "Verified",
};

const PRIORITIES: Record<RequirementPriority, string> = {
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
  CRITICAL: "Critical",
};

const TECHNOLOGY_CATEGORIES: Record<TechnologyCategory, string> = {
  LANGUAGE: "Language",
  FRAMEWORK: "Framework",
  DATABASE: "Database",
  INFRASTRUCTURE: "Infrastructure",
  LIBRARY: "Library",
  TOOL: "Tool",
  PROTOCOL: "Protocol",
  OTHER: "Other",
};

export function humanize(key: string): string {
  return key
    .toLowerCase()
    .split("_")
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" ");
}

export const requirementTypeLabel = (value: RequirementType) => REQUIREMENT_TYPES[value] ?? value;
export const constraintTypeLabel = (value: ConstraintType) => CONSTRAINT_TYPES[value] ?? value;
export const constraintSeverityLabel = (value: ConstraintSeverity) =>
  CONSTRAINT_SEVERITIES[value] ?? value;
export const deliverableTypeLabel = (value: DeliverableType) => DELIVERABLE_TYPES[value] ?? value;
export const deliverableStatusLabel = (value: DeliverableStatus) =>
  DELIVERABLE_STATUSES[value] ?? value;
export const requirementStatusLabel = (value: RequirementStatus) =>
  REQUIREMENT_STATUSES[value] ?? value;
export const priorityLabel = (value: RequirementPriority) => PRIORITIES[value] ?? value;
export const technologyCategoryLabel = (value: TechnologyCategory) =>
  TECHNOLOGY_CATEGORIES[value] ?? value;

export const REQUIREMENT_TYPE_OPTIONS = Object.keys(REQUIREMENT_TYPES) as RequirementType[];
export const CONSTRAINT_TYPE_OPTIONS = Object.keys(CONSTRAINT_TYPES) as ConstraintType[];
export const CONSTRAINT_SEVERITY_OPTIONS = Object.keys(
  CONSTRAINT_SEVERITIES,
) as ConstraintSeverity[];
export const DELIVERABLE_TYPE_OPTIONS = Object.keys(DELIVERABLE_TYPES) as DeliverableType[];
export const DELIVERABLE_STATUS_OPTIONS = Object.keys(
  DELIVERABLE_STATUSES,
) as DeliverableStatus[];
export const REQUIREMENT_STATUS_OPTIONS = Object.keys(
  REQUIREMENT_STATUSES,
) as RequirementStatus[];
export const PRIORITY_OPTIONS = Object.keys(PRIORITIES) as RequirementPriority[];
export const TECHNOLOGY_CATEGORY_OPTIONS = Object.keys(
  TECHNOLOGY_CATEGORIES,
) as TechnologyCategory[];

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
