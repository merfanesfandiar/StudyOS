// Types mirror the FastAPI OpenAPI schema. Decimals arrive as strings so a
// weight of 33.33 never drifts through a JavaScript float.

export type AssignmentStatus =
  | "DRAFT"
  | "INCOMPLETE"
  | "READY_FOR_ANALYSIS"
  | "ANALYSIS_IN_PROGRESS"
  | "ANALYZED"
  | "COMPLETED"
  | "ARCHIVED"
  | "ACTIVE";

/** Only these may be set directly; the rest need the readiness gate. */
export type ClientSettableStatus = "DRAFT" | "INCOMPLETE" | "COMPLETED" | "ARCHIVED";

export type RequirementPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type RequirementStatus = "TODO" | "IN_PROGRESS" | "BLOCKED" | "COMPLETED" | "VERIFIED";
export type RequirementType =
  | "FUNCTIONAL"
  | "TECHNICAL"
  | "DESIGN"
  | "DOCUMENTATION"
  | "CONSTRAINT"
  | "PERFORMANCE"
  | "SECURITY"
  | "TESTING"
  | "OTHER";
export type ConstraintType =
  | "TECHNOLOGY"
  | "TIME"
  | "RESOURCE"
  | "FORMAT"
  | "LANGUAGE"
  | "LIBRARY"
  | "PLATFORM"
  | "ACADEMIC"
  | "SECURITY"
  | "PERFORMANCE"
  | "OTHER";
export type ConstraintSeverity = "INFO" | "WARNING" | "IMPORTANT" | "CRITICAL";
export type DeliverableType =
  | "SOURCE_CODE"
  | "DOCUMENT"
  | "DATASET"
  | "PRESENTATION"
  | "TEST_SUITE"
  | "VIDEO"
  | "OTHER";
export type DeliverableStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "VERIFIED";
export type TechnologyCategory =
  | "LANGUAGE"
  | "FRAMEWORK"
  | "DATABASE"
  | "INFRASTRUCTURE"
  | "LIBRARY"
  | "TOOL"
  | "PROTOCOL"
  | "OTHER";
export type CheckStatus = "PASS" | "WARNING" | "FAIL";

export interface User {
  id: string;
  name: string;
  email: string;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface Course {
  id: string;
  workspace_id: string;
  name: string;
  code: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  assignment_count: number;
}

export interface CourseInput {
  name: string;
  code: string;
  description?: string | null;
}

export interface Requirement {
  id: string;
  assignment_id: string;
  code: string;
  sequence: number;
  title: string;
  description: string | null;
  priority: RequirementPriority;
  type: RequirementType;
  status: RequirementStatus;
  is_required: boolean;
  position: number;
  parent_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RequirementInput {
  title: string;
  description?: string | null;
  priority?: RequirementPriority;
  type?: RequirementType;
  status?: RequirementStatus;
  is_required?: boolean;
  position?: number;
  parent_id?: string | null;
}

export interface Dependency {
  id: string;
  requirement_id: string;
  depends_on_id: string;
  depends_on_code: string;
  depends_on_title: string;
  note: string | null;
  created_at: string;
}

export interface DependencyNode {
  id: string;
  code: string;
  title: string;
  status: RequirementStatus;
  priority: RequirementPriority;
  depth: number;
}

export interface DependencyEdge {
  requirement_id: string;
  requirement_code: string;
  depends_on_id: string;
  depends_on_code: string;
}

export interface DependencyGraph {
  nodes: DependencyNode[];
  edges: DependencyEdge[];
  execution_order: string[];
  has_cycles: boolean;
}

export interface Constraint {
  id: string;
  assignment_id: string;
  title: string;
  description: string;
  value: string | null;
  type: ConstraintType;
  severity: ConstraintSeverity;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface ConstraintInput {
  title: string;
  description: string;
  value?: string | null;
  type?: ConstraintType;
  severity?: ConstraintSeverity;
  position?: number;
}

export interface Criterion {
  id: string;
  assignment_id: string;
  title: string;
  description: string | null;
  weight: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface CriterionInput {
  title: string;
  description?: string | null;
  weight: string;
  position?: number;
}

export interface Deliverable {
  id: string;
  assignment_id: string;
  title: string;
  description: string | null;
  type: DeliverableType;
  status: DeliverableStatus;
  is_required: boolean;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface DeliverableInput {
  title: string;
  description?: string | null;
  type?: DeliverableType;
  status?: DeliverableStatus;
  is_required?: boolean;
  position?: number;
}

export interface Technology {
  id: string;
  workspace_id: string;
  name: string;
  version: string;
  category: TechnologyCategory;
  created_at: string;
}

export interface Tag {
  id: string;
  workspace_id: string;
  name: string;
  created_at: string;
}

export interface Document {
  id: string;
  assignment_id: string;
  filename: string;
  mime_type: string;
  size: number;
  created_at: string;
}

export interface AssignmentSummary {
  id: string;
  title: string;
  deadline: string | null;
  status: AssignmentStatus;
  course_id: string;
  course_name: string;
  course_code: string;
}

export interface Assignment extends AssignmentSummary {
  workspace_id: string;
  description: string | null;
  readiness_score: number;
  ready_for_analysis_at: string | null;
  created_at: string;
  updated_at: string;
  requirements: Requirement[];
  constraints: Constraint[];
  criteria: Criterion[];
  deliverables: Deliverable[];
  technologies: Technology[];
  tags: Tag[];
  documents: Document[];
  criteria_total: string;
}

export interface AssignmentListItem extends AssignmentSummary {
  description: string | null;
  readiness_score: number;
  readiness_state: AssignmentStatus;
  requirements_count: number;
  completed_requirements_count: number;
  criteria_total: string;
  deadline_state: string;
  updated_at: string;
}

export interface AssignmentInput {
  course_id: string;
  title: string;
  description?: string | null;
  deadline?: string | null;
  status?: ClientSettableStatus;
}

export interface AssignmentFilters {
  course_id?: string;
  status?: AssignmentStatus;
  readiness?: AssignmentStatus;
  search?: string;
  tag?: string;
  deadline_before?: string;
  deadline_after?: string;
  page?: number;
  page_size?: number;
  sort_by?: "title" | "deadline" | "created_at" | "updated_at" | "readiness_score";
  sort_direction?: "asc" | "desc";
}

export interface CompletenessCheck {
  field: string;
  label: string;
  status: CheckStatus;
  message: string;
  weight: number;
  blocking: boolean;
}

export interface ReadinessReport {
  score: number;
  is_complete: boolean;
  is_ready_for_analysis: boolean;
  completeness_bar: number;
  failing_checks: string[];
  warning_checks: string[];
  checks: CompletenessCheck[];
}

export interface ValidationResponse {
  is_valid: boolean;
  readiness: ReadinessReport;
  validated_at: string;
  specification_version: number;
}

export interface SpecificationSummary {
  assignment: AssignmentSummary;
  requirements_total: number;
  requirements_required: number;
  requirements_completed: number;
  requirements_verified: number;
  requirements_by_status: Record<string, number>;
  critical_requirements: number;
  constraints_total: number;
  constraints_by_severity: Record<string, number>;
  criteria_total: string;
  criteria_count: number;
  criteria_balanced: boolean;
  deliverables_total: number;
  deliverables_completed: number;
  technologies: string[];
  tags: string[];
  resources_total: number;
  readiness: AssignmentStatus;
  readiness_score: number;
  specification_version: number;
}

export interface AssignmentSpecification {
  assignment: AssignmentSummary;
  description: string | null;
  criteria_total: string;
  requirements: Requirement[];
  constraints: Constraint[];
  evaluation_criteria: Criterion[];
  deliverables: Deliverable[];
  technologies: Technology[];
  tags: Tag[];
  resources: Document[];
  readiness: ReadinessReport;
  summary: SpecificationSummary;
  specification_version: number;
  updated_at: string;
}

export interface VersionSummary {
  version: number;
  change_summary: string;
  created_at: string;
  created_by_id: string | null;
}

export interface VersionDetail extends VersionSummary {
  snapshot: Record<string, unknown>;
}

export interface ActivityEvent {
  id: string;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  change_summary: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Page {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface PageResponse<T> {
  items: T[];
  page: Page;
}

export interface Dashboard {
  upcoming_assignments: AssignmentListItem[];
  recent_assignments: AssignmentListItem[];
  courses_count: number;
  assignments_count: number;
  in_progress_assignments_count: number;
  ready_assignments_count: number;
  incomplete_assignments_count: number;
  completed_assignments_count: number;
  completion_percentage: number;
  average_readiness_score: number;
  unread_notifications_count: number;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  read_at: string | null;
  created_at: string;
}
