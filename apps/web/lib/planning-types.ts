/**
 * Planning types, mirroring `apps/api/app/schemas/planning.py`.
 *
 * The backend is the authority on the shape; these are hand-maintained because
 * the repo does not generate a client. Two consequences are worth stating
 * rather than hiding:
 *
 * Enum-ish fields are string unions, not TypeScript `enum`s, so a value the API
 * adds later fails at runtime in one place (the label lookup) instead of
 * failing to compile in a hundred.
 *
 * `AnalysisId` on a plan is nullable. A deterministic plan generated before
 * analysis existed — or an analysis that has since been superseded — legitimately
 * has none, and typing it as non-null would be a lie the compiler enforces.
 */

import type { PageResponse } from "./types";

// -- enums -----------------------------------------------------------------

/** Normalised assignment complexity, used for routing and plan shaping. */
export type ComplexityLevel = "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH";

/**
 * Coarse effort band. Never a guarantee.
 *
 * `UNKNOWN` is a real value rather than a zero. Treating an unknown estimate as
 * small would quietly corrupt the schedule-risk check, which is the one place
 * the number decides anything.
 */
export type EffortLevel =
  | "VERY_LOW"
  | "LOW"
  | "MEDIUM"
  | "HIGH"
  | "VERY_HIGH"
  | "UNKNOWN";

export type AcademicTaskType =
  | "READING"
  | "WRITING"
  | "ANALYSIS"
  | "IMPLEMENTATION"
  | "EXPERIMENT"
  | "STUDY"
  | "PRACTICE"
  | "REVIEW"
  | "OTHER";

export type AcademicTaskStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "BLOCKED"
  | "IN_REVIEW"
  | "DONE"
  | "SKIPPED";

export type AcademicTaskPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type PlanStatus = "DRAFT" | "IN_REVIEW" | "APPROVED" | "ARCHIVED";

export type PlanTrigger = "GENERATED" | "REGENERATED" | "EDITED" | "APPROVED";

export type PlanningRunStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export type ModelTier = "FAST" | "BALANCED" | "DEEP";

export type AIMode = "AUTO" | "FAST" | "THOROUGH" | "OFF";

export type PlanningStyle =
  | "BALANCED"
  | "DEEP_DIVE"
  | "PRACTICE_FOCUSED"
  | "FAST_TRACK"
  | "THESIS_LIKE";

export type GuidanceLevel = "MINIMAL" | "MODERATE" | "DETAILED";

export type SessionLength = "SHORT" | "MEDIUM" | "LONG";

/** How much of a regeneration to replace. */
export type RegenerateScope = "TASKS" | "MILESTONES" | "NONE";

// -- responses -------------------------------------------------------------

export interface PlanTask {
  id: string;
  /** Stable within a version, e.g. `T7`. The UI addresses tasks by key. */
  key: string;
  title: string;
  description: string;
  type: AcademicTaskType;
  status: AcademicTaskStatus;
  priority: AcademicTaskPriority;
  position: number;
  estimated_effort: EffortLevel;
  min_minutes: number | null;
  max_minutes: number | null;
  verification_method: string | null;
  acceptance_criteria: string[];
  resources: string[];
  notes: string | null;
  is_user_authored: boolean;
  depends_on: string[];
  related_requirements: string[];
  related_deliverables: string[];
  /** Keys of incomplete predecessors. Drives the blocked indicator. */
  blocked_by: string[];
}

export interface PlanMilestone {
  id: string;
  key: string;
  title: string;
  description: string | null;
  position: number;
  status: AcademicTaskStatus;
  task_keys: string[];
  completed_task_count: number;
  task_count: number;
}

export interface VerificationPoint {
  key: string;
  title: string;
  description: string;
  method: string;
  task_keys: string[];
  related_requirements: string[];
}

export interface PlanRisk {
  key: string;
  description: string;
  severity: string;
  mitigation: string | null;
  related_task_keys: string[];
}

/**
 * The deadline check, computed rather than asserted.
 *
 * `is_overcommitted` means the upper estimate exceeds the time remaining. It
 * does not mean the student will miss the deadline, and the UI must not render
 * it as though it does.
 */
export interface ScheduleRisk {
  level: ComplexityLevel;
  estimated_minutes: number;
  available_minutes: number | null;
  is_overcommitted: boolean;
  summary: string;
  factors: string[];
}

export interface WorkPlan {
  id: string;
  assignment_id: string;
  analysis_id: string | null;
  version: number;
  trigger: PlanTrigger;
  reason: string;
  /** Which sections the regeneration changed. Null for a first generation. */
  changed_sections: string[] | null;
  title: string;
  summary: string;
  status: PlanStatus;
  objectives: string[];
  estimated_effort: EffortLevel;
  min_minutes: number | null;
  max_minutes: number | null;
  is_stale: boolean;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  tasks: PlanTask[];
  milestones: PlanMilestone[];
  verification_points: VerificationPoint[];
  risks: PlanRisk[];
  schedule_risk: ScheduleRisk | null;
  progress_percentage: number;
  validation_warnings: string[];
}

/** A plan without its tasks, for list views. */
export interface PlanSummary {
  id: string;
  assignment_id: string;
  analysis_id: string | null;
  version: number;
  trigger: PlanTrigger;
  title: string;
  status: PlanStatus;
  is_stale: boolean;
  task_count: number;
  completed_task_count: number;
  progress_percentage: number;
  estimated_effort: EffortLevel;
  created_at: string;
  approved_at: string | null;
}

export type PlanSummaryPage = PageResponse<PlanSummary>;

/**
 * One generation attempt. Telemetry, never chain-of-thought.
 *
 * `error_code` and `error_message` are populated for a `FAILED` run. Showing
 * them is the point: a silent failure that leaves no trace is indistinguishable
 * from a request that never arrived.
 */
export interface PlanningRun {
  id: string;
  assignment_id: string;
  plan_id: string | null;
  status: PlanningRunStatus;
  provider: string;
  model: string;
  model_tier: ModelTier;
  routing_reason: string;
  routing_confidence: number;
  complexity: ComplexityLevel;
  fell_back_from_tier: ModelTier | null;
  prompt_version: string;
  duration_ms: number | null;
  token_usage: Record<string, unknown> | null;
  estimated_cost: number | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface ModelSelection {
  model_tier: ModelTier;
  model: string;
  reason: string;
  confidence: number;
  complexity: ComplexityLevel;
  complexity_factors: string[];
  ai_mode: AIMode;
  overridden: boolean;
  override_reason: string | null;
}

export interface PlanningPreferences {
  planning_style: PlanningStyle;
  guidance_level: GuidanceLevel;
  session_length: SessionLength;
  ai_mode: AIMode;
}

// -- requests --------------------------------------------------------------

export interface PlanGenerateInput {
  analysis_id?: string | null;
  force?: boolean;
  planning_style?: PlanningStyle;
  guidance_level?: GuidanceLevel;
  session_length?: SessionLength;
  ai_mode?: AIMode;
  idempotency_key?: string;
  reason?: string;
}

export interface PlanRegenerateInput {
  scope?: RegenerateScope;
  reason?: string;
  force?: boolean;
  preserve_user_edits?: boolean;
  planning_style?: PlanningStyle;
  guidance_level?: GuidanceLevel;
  session_length?: SessionLength;
  ai_mode?: AIMode;
  idempotency_key?: string;
}

export interface PlanUpdateInput {
  title?: string;
  summary?: string;
}

export interface TaskCreateInput {
  title: string;
  description?: string;
  type?: AcademicTaskType;
  priority?: AcademicTaskPriority;
  estimated_effort?: EffortLevel;
  depends_on?: string[];
  related_requirements?: string[];
  related_deliverables?: string[];
  verification_method?: string | null;
  acceptance_criteria?: string[];
  notes?: string | null;
  position?: number;
}

export interface TaskUpdateInput {
  title?: string;
  description?: string;
  type?: AcademicTaskType;
  priority?: AcademicTaskPriority;
  status?: AcademicTaskStatus;
  estimated_effort?: EffortLevel;
  min_minutes?: number | null;
  max_minutes?: number | null;
  verification_method?: string | null;
  acceptance_criteria?: string[];
  resources?: string[];
  notes?: string | null;
  /** Replaces the dependency set wholesale. Omit to leave it unchanged. */
  depends_on?: string[];
  related_requirements?: string[];
  related_deliverables?: string[];
}

export interface PlanningPreferencesInput {
  planning_style?: PlanningStyle;
  guidance_level?: GuidanceLevel;
  session_length?: SessionLength;
  ai_mode?: AIMode;
}
