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

/**
 * The closed set of decisions the runtime may take. Mirrors `AgentAction` in
 * `app/models/enums.py` exactly: a model may not invent an action, and the UI
 * must not render one that cannot exist.
 */
export type AgentAction =
  | "EXECUTE_TASK"
  | "ASK_USER"
  | "REQUEST_APPROVAL"
  | "CREATE_ARTIFACT"
  | "UPDATE_ARTIFACT"
  | "REVIEW_RESULT"
  | "RETRY_TASK"
  | "MARK_BLOCKED"
  | "COMPLETE_TASK"
  | "PAUSE_RUN"
  | "CALL_TOOL";

/** Mirrors `AgentCheckpointType`. */
export type AgentCheckpointType =
  | "CLARIFICATION"
  | "APPROVAL"
  | "REVIEW"
  | "DECISION"
  | "MISSING_INFORMATION"
  | "PERMISSION";

/** Mirrors `AgentCheckpointStatus`. `EXPIRED` questions can never authorise. */
export type AgentCheckpointStatus = "PENDING" | "RESOLVED" | "CANCELLED" | "EXPIRED";

/** Mirrors `AgentArtifactType`. */
export type AgentArtifactType =
  | "TEXT"
  | "MARKDOWN"
  | "REPORT"
  | "OUTLINE"
  | "SOLUTION"
  | "CALCULATION"
  | "PROOF_DRAFT"
  | "PRESENTATION"
  | "RESEARCH_NOTES"
  | "CODE"
  | "DOCUMENT";

/** Mirrors `AgentArtifactStatus`. */
export type AgentArtifactStatus = "DRAFT" | "ACTIVE" | "SUPERSEDED" | "ARCHIVED";

/** Who an artifact belongs to. Mirrors `AgentArtifactOwnership`. */
export type AgentArtifactOwnership =
  | "USER_OWNED"
  | "AGENT_OWNED"
  | "SYSTEM_GENERATED"
  | "IMPORTED";

/** How a task kind is executed. Mirrors `AgentExecutorKind`. */
export type AgentExecutorKind =
  | "REASONING"
  | "WRITING"
  | "ANALYSIS"
  | "RESEARCH"
  | "CALCULATION"
  | "PLANNING"
  | "ARTIFACT"
  | "MOCK_TOOL";

/**
 * The specialized academic worker serving a task. Mirrors `AgentWorkerKind`.
 *
 * A worker is the connection between a task type and a bounded toolset:
 * `PROVE` is served by `MATHEMATICS`, which may use the mathematics tools.
 * `REASONING` is the fallback for an unmapped task type, so an unfamiliar task
 * is served by a narrow boundary rather than by everything.
 */
export type AgentWorkerKind =
  | "REASONING"
  | "MATHEMATICS"
  | "DATA"
  | "WRITING"
  | "RESEARCH"
  | "CODE"
  | "PRESENTATION";

/** Outcome of one recorded tool call. Mirrors `AgentToolInvocationStatus`. */
export type AgentToolInvocationStatus = "SUCCESS" | "FAILED" | "BLOCKED";

/** Outcome of one attempt at one task. Mirrors `AgentExecutionStatus`. */
export type AgentExecutionStatus =
  | "SUCCESS"
  | "PARTIAL_SUCCESS"
  | "FAILED"
  | "BLOCKED"
  | "NEEDS_USER_INPUT"
  | "NEEDS_APPROVAL"
  | "SKIPPED";

/** Why an attempt failed, in terms the recovery policy can act on. Mirrors `AgentFailureCategory`. */
export type AgentFailureCategory =
  | "TRANSIENT_PROVIDER"
  | "RATE_LIMITED"
  | "VALIDATION_ERROR"
  | "CONTEXT_ERROR"
  | "DEPENDENCY_ERROR"
  | "PERMISSION_DENIED"
  | "AUTHORIZATION_ERROR"
  | "USER_INPUT_REQUIRED"
  | "UNSUPPORTED_OPERATION"
  | "TIMEOUT"
  | "EXTERNAL_SERVICE_ERROR"
  | "INVALID_RESULT"
  | "RESOURCE_LIMIT"
  | "SYSTEM_ERROR"
  | "CANCELLED";

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
  /** Nullable: attempt history outlives its task (`SET NULL` on task deletion). */
  task_id: string | null;
  task_key: string;
  attempt: number;
  status: AgentExecutionStatus;
  executor: AgentExecutorKind;
  /** The worker boundary that served this attempt, e.g. `MATHEMATICS`. */
  worker: AgentWorkerKind | null;
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
  ownership: AgentArtifactOwnership;
  content: string;
  metadata_json: Record<string, unknown> | null;
  /** 1 for the first draft. Every revision is kept. */
  revision: number;
  deliverable_key: string | null;
  /** The worker that produced the artifact, so output is attributable. */
  worker_name: string | null;
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
  /**
   * The Dynamic Agent UI the runtime wants rendered for this checkpoint.
   *
   * Untyped on purpose: it is untrusted payload from the server that is parsed
   * and validated by `lib/agent-ui/validate.ts` before anything renders. Typing
   * it as the validated `AgentUiEnvelope` here would falsely imply the API has
   * already checked it. Absent for the runtime's plain text questions, which is
   * every checkpoint the deterministic executor produces today.
   */
  ui?: unknown;
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

/**
 * One tool call the run made, or had refused, on a worker.
 *
 * The log is the evidence for two questions the run alone cannot answer: which
 * worker served a step, and how often a model reached for a tool its worker did
 * not have. `BLOCKED` is a refusal — no work happened — and is kept precisely
 * because a silent no-op would hide the pattern a review wants to count.
 */
export interface AgentToolInvocation {
  id: string;
  run_id: string;
  task_id: string | null;
  task_key: string;
  worker_kind: AgentWorkerKind | null;
  tool_name: string;
  iteration: number | null;
  status: AgentToolInvocationStatus;
  args: Record<string, unknown>;
  /** A bounded snapshot of what the tool returned, or null when refused. */
  result: Record<string, unknown> | null;
  error: string | null;
  duration_ms: number | null;
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
   * Every tool call the run made or had refused, newest last.
   *
   * Distinct from the decisions above: a decision says what the model asked
   * for, and this records what the runtime actually dispatched or refused on a
   * worker's behalf.
   */
  tool_invocations: AgentToolInvocation[];
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

/**
 * One tool boundary in the runtime. Mirrors `AgentWorkerResponse`.
 *
 * Published as data so the UI can name the boundary, not just the tools: each
 * task type is bound to exactly one worker, and a worker never lists a tool the
 * runtime does not have.
 */
export interface AgentWorker {
  id: string;
  name: string;
  description: string;
  /** The plan's task types this worker serves. */
  academic_task_types: string[];
  /** The tool names this worker may call. Everything else is refused. */
  tools: string[];
  output_artifact_types: string[];
}

export interface AgentCapabilities {
  tools: AgentTool[];
  workers: AgentWorker[];
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
  /** Only meaningful for APPROVAL, REVIEW and PERMISSION. */
  approved?: boolean;
  retry?: boolean;
}

export type AgentInteractionType =
  | "CLARIFICATION"
  | "USER_DECISION"
  | "PLAN_APPROVAL"
  | "TASK_APPROVAL"
  | "TOOL_PERMISSION"
  | "EXECUTION_APPROVAL"
  | "ARTIFACT_REVIEW"
  | "ARTIFACT_APPROVAL"
  | "DESTRUCTIVE_ACTION_APPROVAL"
  | "EXTERNAL_ACTION_APPROVAL"
  | "CONFLICT_RESOLUTION"
  | "EXCEPTION_RESOLUTION"
  | "OTHER";

export type AgentInteractionStatus =
  | "PENDING"
  | "SUBMITTED"
  | "ACCEPTED"
  | "REJECTED"
  | "EXPIRED"
  | "CANCELLED";

export type AgentInteractionRisk = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AgentInteractionPriority = "LOW" | "NORMAL" | "HIGH" | "URGENT";

export interface AgentInteraction {
  id: string;
  run_id: string;
  assignment_id: string;
  workspace_id: string;
  task_id: string | null;
  checkpoint_id: string | null;
  owner_id: string | null;
  interaction_type: AgentInteractionType;
  status: AgentInteractionStatus;
  risk: AgentInteractionRisk;
  priority: AgentInteractionPriority;
  title: string;
  prompt: string;
  context: string | null;
  options: Array<Record<string, unknown>> | null;
  operation_binding: Record<string, unknown>;
  ui: Record<string, unknown>;
  version: number;
  expires_at: string | null;
  requested_at: string;
  resolved_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  metadata_json: Record<string, unknown>;
  responses?: AgentInteractionResponseHistoryItem[];
}

export interface AgentInteractionResponseHistoryItem {
  id: string;
  interaction_id: string;
  run_id: string;
  responder_id: string | null;
  version: number;
  status: string;
  response_type: string | null;
  payload: Record<string, unknown>;
  rationale: string | null;
  artifacts: Array<Record<string, unknown>> | null;
  diff: Record<string, unknown> | null;
  operation_binding_snapshot: Record<string, unknown>;
  submitted_at: string;
}

export interface AgentInteractionRespondInput {
  action: string;
  payload?: Record<string, unknown>;
  rationale?: string;
  artifacts?: Array<Record<string, unknown>> | null;
  diff?: Record<string, unknown> | null;
}

export interface AgentInteractionCreateInput {
  interaction_type?: AgentInteractionType;
  risk?: AgentInteractionRisk;
  priority?: AgentInteractionPriority;
  title: string;
  prompt: string;
  context?: string | null;
  options?: Array<Record<string, unknown>> | null;
  operation_binding?: Record<string, unknown>;
  ui?: Record<string, unknown>;
  task_id?: string | null;
  checkpoint_id?: string | null;
  expires_at?: string | null;
  metadata_json?: Record<string, unknown>;
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