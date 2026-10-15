/**
 * Phase 7 execution types, mirroring `apps/api/app/schemas/execution.py`.
 *
 * Kept in its own file, like `agent-types.ts`, because the execution plane has
 * its own vocabulary. Three things are deliberately absent and worth stating:
 *
 * - No sandbox id and no host path. The API does not return either, so there is
 *   nothing here to render even by accident.
 * - No image or command field. A request names a *runtime*, never an executable,
 *   so the type itself is part of the boundary.
 * - No raw source is re-sent back: a job response carries excerpts of its output,
 *   and the source the student typed stays in the form.
 */

/** Union of every runtime a job may ask for. Mirrors `ExecutionType`. */
export type ExecutionType =
  | "PYTHON"
  | "JAVA"
  | "CPP"
  | "DATA_ANALYSIS"
  | "NUMERICAL_COMPUTATION"
  | "TEST_EXECUTION"
  | "BUILD"
  | "STATIC_ANALYSIS"
  | "OTHER";

/** A named, bounded resource policy. A ceiling, never an entitlement. */
export type ExecutionResourceProfile =
  | "LIGHT_COMPUTATION"
  | "STANDARD_CODE_EXECUTION"
  | "DATA_ANALYSIS"
  | "TEST_EXECUTION"
  | "BUILD_EXECUTION";

/** Which isolation backend served a job. `DISABLED` means nothing ran. */
export type ExecutionBackendKind = "DISABLED" | "DOCKER" | "MOCK";

export type ExecutionJobStatus =
  | "CREATED"
  | "VALIDATING"
  | "REJECTED"
  | "QUEUED"
  | "STARTING"
  | "RUNNING"
  | "COLLECTING_RESULTS"
  | "SUCCEEDED"
  | "FAILED"
  | "TIMED_OUT"
  | "CANCEL_REQUESTED"
  | "CANCELLED"
  | "RESOURCE_LIMIT_EXCEEDED"
  | "CLEANUP_PENDING";

export type ExecutionAttemptStatus =
  | "STARTING"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "TIMED_OUT"
  | "RESOURCE_LIMIT_EXCEEDED"
  | "CANCELLED"
  | "REJECTED";

/** Whether the environment was reclaimed, tracked apart from the job result. */
export type ExecutionCleanupStatus = "PENDING" | "CLEANED" | "FAILED" | "SKIPPED";

export type ExecutionFailureClass =
  | "INVALID_REQUEST"
  | "POLICY_REJECTED"
  | "ENVIRONMENT_UNAVAILABLE"
  | "STARTUP_FAILED"
  | "COMPILE_FAILED"
  | "USER_CODE_FAILED"
  | "TIMEOUT"
  | "RESOURCE_EXHAUSTED"
  | "INFRASTRUCTURE"
  | "CANCELLED";

export type ExecutionArtifactKind =
  | "SOURCE"
  | "RESULT"
  | "DATA_OUTPUT"
  | "CHART"
  | "TEST_REPORT"
  | "DIAGNOSTICS"
  | "LOG"
  | "SUMMARY"
  | "GENERATED_FILE"
  | "OTHER";

export type ExecutionMode = "sync" | "queue";

export interface ExecutionJob {
  id: string;
  workspace_id: string;
  assignment_id: string | null;
  agent_run_id: string | null;
  task_id: string | null;
  execution_type: ExecutionType;
  backend: ExecutionBackendKind | null;
  status: ExecutionJobStatus;
  resource_profile: ExecutionResourceProfile;
  entrypoint: string | null;
  attempt_count: number;
  max_attempts: number;
  exit_code: number | null;
  duration_ms: number | null;
  failure_class: ExecutionFailureClass | null;
  error_code: string | null;
  error_message: string | null;
  /** A bounded tail of the run's primary output. Never the full stream. */
  result_excerpt: string | null;
  cleanup_status: ExecutionCleanupStatus;
  created_at: string;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  cancelled_at: string | null;
}

export interface ExecutionAttempt {
  id: string;
  attempt: number;
  status: ExecutionAttemptStatus;
  backend: string | null;
  exit_code: number | null;
  failure_class: ExecutionFailureClass | null;
  error_code: string | null;
  error_message: string | null;
  duration_ms: number | null;
  stdout_excerpt: string | null;
  stderr_excerpt: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface ExecutionArtifact {
  id: string;
  filename: string;
  size_bytes: number;
  mime_type: string | null;
  kind: ExecutionArtifactKind;
  created_at: string;
}

export interface ExecutionEvent {
  id: string;
  sequence: number;
  event_type: string;
  summary: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface ExecutionJobDetail {
  job: ExecutionJob;
  attempts: ExecutionAttempt[];
  artifacts: ExecutionArtifact[];
  events: ExecutionEvent[];
}

export interface ExecutionCapabilities {
  enabled: boolean;
  backend: ExecutionBackendKind;
  /** Whether the configured backend is actually reachable on this host. */
  available: boolean;
  execution_types: ExecutionType[];
  resource_profiles: Record<string, Record<string, number>>;
  default_profile: Partial<Record<ExecutionType, ExecutionResourceProfile>>;
  limits: Record<string, number>;
  // The external coding-agent seam. Reported even when unavailable so the UI can
  // say "not configured" rather than offering an action that would fail.
  external_agent?: ExternalAgentCapability;
  absent_capabilities: string[];
}

export interface ExternalAgentCapability {
  kind: string;
  available: boolean;
  reason: string | null;
}

export interface ExecutionCreateInput {
  execution_type: ExecutionType;
  entrypoint?: string | null;
  files: Record<string, string>;
  options?: Record<string, unknown>;
  stdin?: string | null;
  resource_profile?: ExecutionResourceProfile | null;
  timeout_seconds?: number | null;
  mode?: ExecutionMode;
  idempotency_key?: string | null;
}

/**
 * Statuses a job will not leave.
 *
 * Kept as a predicate rather than a list so a new terminal status added to the
 * API is treated as terminal here by default, rather than silently becoming a
 * status the UI keeps polling forever.
 */
export function isExecutionJobTerminal(status: ExecutionJobStatus): boolean {
  return (
    status === "SUCCEEDED" ||
    status === "FAILED" ||
    status === "TIMED_OUT" ||
    status === "CANCELLED" ||
    status === "RESOURCE_LIMIT_EXCEEDED" ||
    status === "REJECTED"
  );
}

/**
 * True while the job is still moving and the panel should keep reading it.
 *
 * `CLEANUP_PENDING` is deliberately included: the result may be final while the
 * environment is still being reclaimed, and the panel should reflect that rather
 * than freeze on a job the server is still working on.
 */
export function isExecutionJobActive(status: ExecutionJobStatus): boolean {
  return !isExecutionJobTerminal(status);
}

/** Whether the job ended with a usable result. */
export function isExecutionJobSuccessful(status: ExecutionJobStatus): boolean {
  return status === "SUCCEEDED";
}

/** The conventional entrypoint filename for a runtime, used to seed the form. */
export const EXECUTION_ENTRYPOINT: Partial<Record<ExecutionType, string>> = {
  PYTHON: "main.py",
  DATA_ANALYSIS: "analysis.py",
  NUMERICAL_COMPUTATION: "computation.py",
  TEST_EXECUTION: "test_main.py",
  JAVA: "Main.java",
  CPP: "main.cpp",
  BUILD: "Makefile",
  STATIC_ANALYSIS: "main.py",
  OTHER: "main.txt",
};

const PYTHON_STARTER = 'print("Hello from the sandbox")\n';

const STARTERS: Partial<Record<ExecutionType, string>> = {
  PYTHON: PYTHON_STARTER,
  JAVA:
    "public class Main {\n" +
    "  public static void main(String[] args) {\n" +
    '    System.out.println("Hello from the sandbox");\n' +
    "  }\n" +
    "}\n",
  CPP:
    "#include <iostream>\n\n" +
    "int main() {\n" +
    '  std::cout << "Hello from the sandbox" << std::endl;\n' +
    "  return 0;\n" +
    "}\n",
  DATA_ANALYSIS: '# Read and print a small dataset.\nprint("ready")\n',
  NUMERICAL_COMPUTATION: '# A small numerical experiment.\nprint(2 ** 10)\n',
  TEST_EXECUTION: 'def test_it_works():\n    assert 2 + 2 == 4\n\n\nprint("tests passed")\n',
  STATIC_ANALYSIS: '# Static analysis placeholder.\nprint("analysed")\n',
  OTHER: "hello\n",
};

/** Starter source for a runtime, so the form is usable without a blank editor. */
export function executionStarter(type: ExecutionType): string {
  return STARTERS[type] ?? PYTHON_STARTER;
}
