/**
 * Phase 5 agent runtime types, mirroring `apps/api/app/schemas/agent.py`.
 *
 * Kept in its own file, like `planning-types.ts`, because the runtime has its own
 * vocabulary. Two things are deliberately absent and worth stating rather than
 * discovering later:
 *
 * - No field for internal reasoning. The API does not return it, so there is
 *   nothing here to render even accidentally. Decisions carry a one-sentence
 *   reason and an outcome.
 * - No domain-specific fields. There is no `run_tests` or `submit_python`; the
 *   agent's work is text, and what it is about lives in the artifact content. A
 *   runtime that only worked for programming assignments would put that here.
 */

/** Union of every status a run can be in. Mirrors `AgentRunStatus`. */
export type AgentRunStatus =
  | "CREATED"
  | "STARTING"
  | "RUNNING"
  | "PAUSED"
  | "WAITING_FOR_USER"
  | "BLOCKED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

/** `SUPERVISED` asks before acting; `AUTONOMOUS` runs to the next real wall. */
export type AgentRunMode = "SUPERVISED" | "AUTONOMOUS";

export type AgentAction =
  | "CREATE_ARTIFACT"
  | "COMPLETE_TASK"
  | "REQUEST_CHECKPOINT"
  | "ASK_USER"
  | "PAUSE"
  | "SKIP_TASK"
  | "RETRY";

export type AgentCheckpointType =
  | "CLARIFICATION"
  | "MISSING_INFORMATION"
  | "APPROVAL"
  | "REVIEW"
  | "RESOURCE";

export type AgentCheckpointStatus = "PENDING" | "RESOLVED" | "EXPIRED";

export type AgentArtifactType =
  | "OUTLINE"
  | "DRAFT"
  | "SOLUTION"
  | "SUMMARY"
  | "NOTES"
  | "CODE";

export type AgentArtifactStatus = "DRAFT" | "REVIEWED" | "SUBMITTED";

export type AgentExecutorKind =
  | "DETERMINISTIC"
  | "MODEL_WORKER"
  | "HUMAN_REVIEW";

export type AgentExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "REJECTED"
  | "SKIPPED";

export type AgentFailureCategory =
  | "PROVIDER_UNAVAILABLE"
  | "PROVIDER_RATE_LIMIT"
  | "INVALID_OUTPUT"
  | "VALIDATION_FAILED"
  | "PERMISSION_DENIED"
  | "BUDGET_EXHAUSTED"
  | "STEP_TIMEOUT"
  | "DEPENDENCY_FAILED"
  | "TOOL_ERROR"
  | "INTERNAL";

/** Plan-task status, as the runtime sees it. Mirrors `AcademicTaskStatus`. */
export type AcademicTaskStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "BLOCKED"
  | "COMPLETED"
  | "SKIPPED";

export interface AgentProgress {
  total: number;
  completed: number;
  skipped: number;
  in_progress: number;
  blocked: number;
  remaining: number;
  percent: number;
}

export interface AgentRun {
  id: string;
  assignment_id: string;
  plan_id: string | null;
  plan_version: number;
  status: AgentRunStatus;
  mode: AgentRunMode;
  /**
   * Always populated for a stopped run.
   *
   * This is the difference between a run that is waiting on you and one that is
   * merely slow, so the UI reads it rather than guessing from the status alone.
   */
  paused_reason: string | null;
  error_code: string | null;
  error_message: string | null;
  error_category: AgentFailureCategory | null;
  model: string | null;
  model_tier: string | null;
  routing_reason: string | null;
  iteration_count: number;
  max_iterations: number;
  max_cost: number;
  estimated_cost: number;
  token_usage: Record<string, number> | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
  /** Absent on list responses; present on the detail endpoint. */
  progress?: AgentProgress | null;
  awaiting_checkpoint_id?: string | null;
  can_resume?: boolean;
  can_retry?: boolean;
}

export interface AgentTask {
  id: string;
  key: string;
  title: string;
  type: string;
  status: AcademicTaskStatus;
  priority: string;
  position: number;
  /** True once this run has attempted the task at all. */
  attempted: boolean;
  attempts: number;
  last_status: AgentExecutionStatus | null;
  last_summary: string | null;
  artifact_ids: string[];
  /** False when a human must look before the task counts as done. */
  can_auto_complete: boolean;
}

export interface AgentExecution {
  id: string;
  task_id: string;
  task_key: string;
  attempt: number;
  status: AgentExecutionStatus;
  executor: AgentExecutorKind;
  model: string | null;
  model_tier: string | null;
  summary: string | null;
  reason: string | null;
  output: Record<string, unknown> | null;
  failure_category: AgentFailureCategory | null;
  error_code: string | null;
  error_message: string | null;
  validation_errors: Record<string, unknown>[] | null;
  token_usage: Record<string, number> | null;
  estimated_cost: number | null;
  duration_ms: number | null;
  started_at: string;
  completed_at: string | null;
}

export interface AgentArtifact {
  id: string;
  run_id: string;
  task_id: string | null;
  title: string;
  artifact_type: AgentArtifactType;
  status: AgentArtifactStatus;
  content: string;
  metadata_json: Record<string, unknown> | null;
  /** 1 for the first draft. Every revision is kept. */
  revision: number;
  deliverable_key: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentCheckpoint {
  id: string;
  run_id: string;
  task_id: string | null;
  checkpoint_type: AgentCheckpointType;
  status: AgentCheckpointStatus;
  question: string;
  context: string | null;
  /**
   * The complete list of acceptable answers, when the runtime offered one.
   * The API validates a submitted option against this, so a stale client cannot
   * invent one.
   */
  options: string[] | null;
  response: string | null;
  requested_at: string;
  resolved_at: string | null;
  expires_at: string | null;
}

export interface AgentEvent {
  id: string;
  sequence: number;
  event_type: string;
  /** One line written for the student. Never internal reasoning. */
  summary: string;
  metadata_json: Record<string, unknown>;
  task_id: string | null;
  created_at: string;
}

export interface AgentDecision {
  id: string;
  iteration: number;
  action: AgentAction;
  reason: string;
  expected_output: string | null;
  confidence: number;
  model: string | null;
  model_tier: string | null;
  payload: Record<string, unknown> | null;
  outcome: string | null;
  executed_at: string;
}

/** One run plus everything the workspace renders, in a single request. */
export interface AgentRunDetail extends AgentRun {
  tasks: AgentTask[];
  executions: AgentExecution[];
  artifacts: AgentArtifact[];
  checkpoints: AgentCheckpoint[];
  events: AgentEvent[];
  decisions: AgentDecision[];
  /**
   * What the context builder included, and what it dropped.
   *
   * The answer to "why couldn't the agent see my document?" lives here rather
   * than in a guess the UI makes.
   */
  context_provenance: Record<string, unknown>[];
}

export interface AgentTool {
  name: string;
  description: string;
  permissions: string[];
}

export interface AgentCapabilities {
  tools: AgentTool[];
  executors: string[];
  modes: AgentRunMode[];
  actions: AgentAction[];
  /**
   * What this runtime cannot do.
   *
   * Rendered in the UI rather than buried in docs, because "can this thing run
   * my code?" deserves an answer the student can see without asking.
   */
  absent_capabilities: string[];
  limits: Record<string, number | boolean>;
}

export interface RecoveryReport {
  runs_paused: number;
  checkpoints_expired: number;
  run_ids: string[];
}

export interface AgentRunCreateInput {
  mode?: AgentRunMode;
  /** Lowering the ceiling is fine; raising it above the max is refused. */
  max_cost?: number;
  /** Same key twice returns the same run rather than starting two. */
  idempotency_key?: string;
}

export interface AgentRunActionInput {
  /** Required when resuming from blocked: what the student did about it. */
  note?: string;
}

export interface AgentCheckpointResolveInput {
  /** Free text, for the questions that need one. */
  response?: string;
  /** Must be one of the options actually offered. */
  selected_option?: string;
  /** Only meaningful for APPROVAL and REVIEW. */
  approved?: boolean;
  retry?: boolean;
}

/**
 * Statuses a student cannot act on.
 *
 * Kept as a predicate rather than a list so a new terminal status added to the
 * API is treated as terminal here by default, rather than silently becoming an
 * actionable one.
 */
export function isAgentRunFinished(status: AgentRunStatus): boolean {
  return status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
}

/** True while the run is mid-flight and the UI should not offer actions. */
export function isAgentRunActive(status: AgentRunStatus): boolean {
  return status === "STARTING" || status === "RUNNING";
}

/**
 * The checkpoint the student must answer, if any.
 *
 * Derived from the run's own fields rather than by scanning the list: the API
 * tells us which checkpoint it is waiting on, and that cannot be stale.
 */
export function pendingAgentCheckpoint(
  run: AgentRunDetail | null,
): AgentCheckpoint | null {
  if (!run || !run.awaiting_checkpoint_id) return null;
  return (
    run.checkpoints.find(
      (checkpoint) =>
        checkpoint.id === run.awaiting_checkpoint_id && checkpoint.status === "PENDING",
    ) ?? null
  );
}

/** Newest first, so revision 3 is not rendered above revision 2. */
export function agentArtifactRevisions(artifacts: AgentArtifact[], taskId: string): AgentArtifact[] {
  return artifacts
    .filter((artifact) => artifact.task_id === taskId)
    .sort((a, b) => b.revision - a.revision);
}