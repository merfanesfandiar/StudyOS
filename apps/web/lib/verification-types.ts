/**
 * Contracts for the Phase 10 verification engine (mirrors
 * `apps/api/app/schemas/verification.py`).
 */

export type VerificationRunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export type VerificationRunSummary = {
  id: string;
  assignment_id: string;
  status: VerificationRunStatus;
  scope_kind: string;
  trigger: string;
  verdict: string | null;
  completion_percentage: number;
  created_at: string;
  finished_at: string | null;
  previous_run_id: string | null;
};

export type VerificationFinding = {
  id: string;
  validator: string;
  level: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFORMATIONAL";
  title: string;
  description: string;
  recommendation: string | null;
  requirement_codes: string[] | null;
  artifact_ids: string[] | null;
  heuristic: boolean;
};

export type VerificationEvidence = {
  id: string;
  validator: string;
  kind: string;
  source: string;
  method: string;
  status: string;
  content: string;
};

export type RequirementVerification = {
  requirement_id: string;
  code: string;
  status: string;
  explanation: string;
};

export type RubricEvaluation = {
  criterion_id: string;
  status: string;
  score: number | null;
  justification: string;
  improvement: string | null;
};

export type VerificationReport = VerificationRunSummary & {
  summary: Record<string, unknown>;
  findings: VerificationFinding[];
  evidence: VerificationEvidence[];
  requirements: RequirementVerification[];
  rubric: RubricEvaluation[];
  comparison: { changes: { code: string; before: string; after: string }[] } | null;
};

export type VerificationTriggerInput = {
  scope?: "FULL" | "ARTIFACT" | "REQUIREMENT";
  artifact_ids?: string[];
  requirement_ids?: string[];
  re_verification_of?: string | null;
  idempotency_key?: string | null;
};

export function isVerificationReport(value: unknown): value is VerificationReport {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    Array.isArray(candidate.findings) &&
    Array.isArray(candidate.requirements)
  );
}
