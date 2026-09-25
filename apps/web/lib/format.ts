import type {
  AssignmentStatus,
  CheckStatus,
  ClientSettableStatus,
  ConstraintSeverity,
  ConstraintType,
  DeliverableStatus,
  DeliverableType,
  RequirementPriority,
  RequirementStatus,
  RequirementType,
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
