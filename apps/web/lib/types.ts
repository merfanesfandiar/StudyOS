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

// ---------------------------------------------------------------------------
// Phase 3: universal academic assignment analysis
//
// Type and domain are independent, multi-valued axes, and every finding carries
// its provenance. The UI must never render an AI inference as if the brief had
// stated it, so `source`/`SourceKind` is not optional anywhere it matters.
// ---------------------------------------------------------------------------

export type AssignmentType =
  | "PROGRAMMING"
  | "PROBLEM_SET"
  | "MATHEMATICAL_PROOF"
  | "ESSAY"
  | "RESEARCH"
  | "LITERATURE_REVIEW"
  | "LAB_REPORT"
  | "DATA_ANALYSIS"
  | "PRESENTATION"
  | "READING"
  | "LANGUAGE"
  | "DESIGN"
  | "GROUP_PROJECT"
  | "REPORT"
  | "OTHER";

export type AcademicDomain =
  | "MATHEMATICS"
  | "COMPUTER_SCIENCE"
  | "PHYSICS"
  | "CHEMISTRY"
  | "BIOLOGY"
  | "ENGINEERING"
  | "ECONOMICS"
  | "BUSINESS"
  | "SOCIAL_SCIENCES"
  | "HUMANITIES"
  | "LANGUAGES"
  | "ART_AND_DESIGN"
  | "OTHER";

/** Generic requirement category. TECHNICAL exists but must never dominate. */
export type RequirementCategory =
  | "CONTENT"
  | "PROCESS"
  | "DELIVERABLE"
  | "QUALITY"
  | "FORMAT"
  | "ACADEMIC"
  | "METHODOLOGY"
  | "EVALUATION"
  | "PRESENTATION"
  | "TECHNICAL"
  | "OTHER";

/** EXPLICIT is in the brief; everything else is the model's interpretation. */
export type SourceKind = "EXPLICIT" | "AI_INFERENCE" | "UNCERTAIN" | "MISSING";

export type ClassificationSource = "AI" | "USER";
export type AnalysisReviewStatus = "PENDING" | "ACCEPTED" | "REJECTED";
export type AnalysisRunStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED"
  | "STALE";
export type FindingSeverity = "INFO" | "WARNING" | "IMPORTANT" | "CRITICAL";
export type QuestionPriority = "CRITICAL" | "IMPORTANT" | "OPTIONAL";
export type QuestionStatus = "OPEN" | "ANSWERED" | "DISMISSED";
export type EvidenceSourceType =
  | "TITLE"
  | "DESCRIPTION"
  | "COURSE"
  | "REQUIREMENT"
  | "CONSTRAINT"
  | "CRITERION"
  | "DELIVERABLE"
  | "RESOURCE"
  | "USER_NOTE"
  | "INFERENCE";
export type ScopeLevel = "NOT_APPLICABLE" | "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";

export interface Evidence {
  source_type: EvidenceSourceType;
  source_id: string | null;
  location: string | null;
  excerpt_reference: string | null;
  supports: string;
  confidence: number;
}

export interface ClassifiedType {
  type: AssignmentType;
  confidence: number;
  source: ClassificationSource;
  rationale: string | null;
}

export interface ClassifiedDomain {
  domain: AcademicDomain;
  confidence: number;
  source: ClassificationSource;
  rationale: string | null;
}

export interface Objective {
  statement: string;
  source: SourceKind;
  confidence: number;
}

export interface NormalizedRequirement {
  /** Stable key inside one analysis (R1). Not the authoritative REQ code. */
  key: string;
  title: string;
  description: string | null;
  category: RequirementCategory;
  priority: RequirementPriority;
  required: boolean;
  source: SourceKind;
  source_reference: string | null;
  confidence: number;
  evidence: Evidence[];
}

export interface Ambiguity {
  key: string;
  description: string;
  severity: FindingSeverity;
  affected_requirements: string[];
  evidence: Evidence[];
  suggested_clarification: string | null;
  confidence: number;
}

export interface Contradiction {
  key: string;
  description: string;
  conflicting_items: string[];
  severity: FindingSeverity;
  evidence: Evidence[];
  clarification_needed: boolean;
  confidence: number;
}

export interface MissingInformation {
  key: string;
  description: string;
  area: string;
  severity: FindingSeverity;
  evidence: Evidence[];
  confidence: number;
}

export interface Assumption {
  key: string;
  statement: string;
  confidence: number;
  evidence: Evidence[];
}

export interface Risk {
  key: string;
  description: string;
  severity: FindingSeverity;
  affected_area: string;
  evidence: Evidence[];
  mitigation_hint: string | null;
  confidence: number;
}

export interface AnalysisQuestion {
  id: string;
  code: string;
  priority: QuestionPriority;
  status: QuestionStatus;
  question: string;
  rationale: string | null;
  related_requirements: string[];
  answer: string | null;
  answered_at: string | null;
  position: number;
}

export interface AnalyzedDeliverable {
  key: string;
  title: string;
  description: string | null;
  /** null means "genuinely unknown", which is not the same as not required. */
  required: boolean | null;
  expected_content: string[];
  format: string | null;
  related_requirements: string[];
  verification_needs: string[];
  depends_on: string[];
  uncertainty: SourceKind;
  evidence: Evidence[];
  confidence: number;
}

export interface RubricCriterion {
  title: string;
  description: string | null;
  weight: string | null;
  related_requirements: string[];
  implied: boolean;
  confidence: number;
}

export interface EvaluationAnalysis {
  rubric_available: boolean;
  criteria: RubricCriterion[];
  implied_quality_expectations: string[];
  missing_rubric_information: string[];
  confidence: number;
}

export interface ScopeDimension {
  level: ScopeLevel;
  rationale: string | null;
}

export interface ScopeAnalysis {
  breadth: ScopeDimension;
  depth: ScopeDimension;
  research_intensity: ScopeDimension;
  reasoning_intensity: ScopeDimension;
  technical_complexity: ScopeDimension;
  writing_intensity: ScopeDimension;
  experimental_complexity: ScopeDimension;
  presentation_complexity: ScopeDimension;
  dependency_complexity: ScopeDimension;
  deliverable_count: number;
  requirement_count: number;
  overall: ScopeLevel;
  confidence: number;
}

/** A high-level area of work. Not an executable task; Phase 4 plans those. */
export interface WorkArea {
  key: string;
  title: string;
  description: string | null;
  category: RequirementCategory;
  related_requirements: string[];
  depends_on: string[];
  origin: SourceKind;
  confidence: number;
}

export interface ResourceInsight {
  document_id: string | null;
  filename: string;
  resource_type: string;
  role: string;
  relevant_sections: string[];
  referenced_concepts: string[];
  instructions: string[];
  constraints: string[];
  terminology: string[];
  evidence: Evidence[];
  confidence: number;
}

export interface ResourceAnalysis {
  resources: ResourceInsight[];
  notes: string[];
  confidence: number;
}

export interface AnalysisDependency {
  predecessor: string;
  successor: string;
  kind: string;
  reason: string | null;
  confidence: number;
}

export interface VerificationItem {
  title: string;
  description: string | null;
  method: string;
  applies_to: string[];
  confidence: number;
}

export interface VerificationStrategy {
  items: VerificationItem[];
  notes: string[];
  confidence: number;
}

/**
 * One domain-specific analyzer's output. `data` is deliberately untyped: the
 * universal core must not know the field names, and the panel only renders the
 * known ones defensively.
 */
export interface SpecializedAnalysis {
  analyzer: string;
  assignment_types: AssignmentType[];
  data: Record<string, unknown>;
  summary: string | null;
  confidence: number;
}

export interface AnalysisConstraintSnapshot {
  id: string;
  title: string;
  description: string;
  value: string | null;
  type: ConstraintType;
  severity: ConstraintSeverity;
}

export interface AssignmentAnalysis {
  id: string;
  assignment_id: string;
  analysis_version: number;
  specification_version: number;
  specification_hash: string;
  prompt_version: string;
  provider: string;
  model: string;
  status: AnalysisReviewStatus;
  is_stale: boolean;
  stale_at: string | null;
  summary: string;
  confidence: number;
  assignment_types: ClassifiedType[];
  academic_domains: ClassifiedDomain[];
  objectives: Objective[];
  normalized_requirements: NormalizedRequirement[];
  constraints: AnalysisConstraintSnapshot[];
  ambiguities: Ambiguity[];
  contradictions: Contradiction[];
  missing_information: MissingInformation[];
  assumptions: Assumption[];
  clarification_questions: AnalysisQuestion[];
  deliverables: AnalyzedDeliverable[];
  evaluation: EvaluationAnalysis;
  scope: ScopeAnalysis;
  work_areas: WorkArea[];
  resources: ResourceAnalysis;
  dependencies: AnalysisDependency[];
  verification: VerificationStrategy;
  risks: Risk[];
  specialized_analysis: SpecializedAnalysis[];
  evidence: Evidence[];
  edited: boolean;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnalysisRun {
  id: string;
  assignment_id: string;
  analysis_id: string | null;
  status: AnalysisRunStatus;
  provider: string;
  model: string;
  prompt_version: string;
  specification_version: number;
  input_hash: string;
  output_hash: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  token_usage: Record<string, unknown> | null;
  estimated_cost: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface AnalysisRequest {
  /** Re-run even when an identical, non-stale analysis already exists. */
  force?: boolean;
  user_notes?: string | null;
  include_questions?: boolean;
}

export interface AnalysisEditRequest {
  types?: AssignmentType[];
  domains?: AcademicDomain[];
  /** Shallow overlay on the AI payload, e.g. replacing `ambiguities`. */
  edits?: Record<string, unknown>;
  note?: string | null;
}

/** The frozen, structured input the Phase 4 Planning Engine consumes. */
export interface PlanningContract {
  analysis_id: string;
  assignment_id: string;
  analysis_version: number;
  specification_version: number;
  specification_hash: string;
  prompt_version: string;
  provider: string;
  model: string;
  is_stale: boolean;
  assignment_types: ClassifiedType[];
  academic_domains: ClassifiedDomain[];
  objectives: Objective[];
  requirements: NormalizedRequirement[];
  constraints: AnalysisConstraintSnapshot[];
  deliverables: AnalyzedDeliverable[];
  dependencies: AnalysisDependency[];
  work_areas: WorkArea[];
  risks: Risk[];
  verification_strategy: VerificationStrategy;
  clarification_questions: AnalysisQuestion[];
  specialized_analysis: SpecializedAnalysis[];
  evaluation: EvaluationAnalysis;
  scope: ScopeAnalysis;
}
