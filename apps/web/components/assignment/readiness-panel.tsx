"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { CHECK_LABELS, humanize, statusLabel } from "@/lib/format";
import type { AssignmentSpecification } from "@/lib/types";
import { Alert, CheckDot, ReadinessMeter, StatusBadge } from "@/components/ui";

function failureMessage(specification: AssignmentSpecification, field: string): string {
  return specification.readiness.checks.find((check) => check.field === field)?.message ?? "";
}

/**
 * The deterministic readiness gate.
 *
 * The score is a weighted checklist, never a confidence number, so this panel
 * shows the failing checks and what to do about them instead of a bare
 * percentage.
 */
export function ReadinessPanel({
  specification,
  onChanged,
}: {
  specification: AssignmentSpecification;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<"ready" | "incomplete" | "validate" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ text: string; status: string } | null>(null);
  const { readiness, assignment, summary } = specification;
  const canMarkReady = readiness.is_ready_for_analysis;
  const isReady = assignment.status === "READY_FOR_ANALYSIS";

  async function run(action: "ready" | "incomplete" | "validate") {
    setPending(action);
    setError("");
    setNotice(null);
    try {
      if (action === "ready") {
        const updated = await api.markReady(assignment.id);
        setNotice({
          text: `Marked ready for analysis (${updated.readiness_score}%).`,
          status: updated.status,
        });
      } else if (action === "incomplete") {
        const updated = await api.markIncomplete(assignment.id);
        setNotice({
          text: "Reopened. This assignment is incomplete again.",
          status: updated.status,
        });
      } else {
        const report = await api.validate(assignment.id);
        setNotice({
          text: report.is_valid
            ? `Validated: ${report.readiness.score}% complete, nothing blocking.`
            : `Validated: still missing ${report.readiness.failing_checks
                .map(humanize)
                .join(", ")}.`,
          status: assignment.status,
        });
      }
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The readiness gate refused that change.");
    } finally {
      setPending(null);
    }
  }

  // A confirmation only applies to the state it confirmed, so a later demotion
  // cannot leave "marked ready" on screen next to an incomplete badge.
  const shownNotice = notice?.status === assignment.status ? notice.text : "";

  return (
    <section className="card p-6" data-testid="readiness-panel" id="readiness">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Readiness</h2>
          <p className="mt-1 text-sm text-slate-500">
            A weighted checklist of what this specification still needs.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={assignment.status} />
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-700">
            {readiness.score}%
          </span>
        </div>
      </div>

      <div className="mt-4">
        <ReadinessMeter score={readiness.score} bar={readiness.completeness_bar} />
        <p className="mt-2 text-xs text-slate-500">
          {readiness.is_ready_for_analysis
            ? isReady
              ? "Ready for analysis. Any edit that breaks a blocking check sends it back."
              : "Every blocking check passes. Mark it ready when the brief is final."
            : "Blocking checks are still failing, so this cannot be marked ready."}
        </p>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      {shownNotice ? (
        <div className="mt-4">
          <Alert tone="success">{shownNotice}</Alert>
        </div>
      ) : null}

      {readiness.failing_checks.length ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="text-sm font-bold text-red-900">Blocking</p>
          <ul className="mt-2 space-y-1 text-sm text-red-800">
            {readiness.failing_checks.map((field) => (
              <li key={field}>
                <span className="font-semibold">{humanize(field)}:</span>{" "}
                {failureMessage(specification, field)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {readiness.checks.map((check) => (
          <li className="flex items-start gap-2 text-sm" key={check.field}>
            <CheckDot status={check.status} />
            <span className="min-w-0">
              <span className="font-semibold text-slate-800">{check.label}</span>{" "}
              <span className="text-xs text-slate-400">
                {CHECK_LABELS[check.status]} · {check.weight}%
                {check.blocking ? " · required" : ""}
              </span>
              <span className="block text-xs leading-5 text-slate-500">{check.message}</span>
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-5">
        {isReady ? (
          <button
            className="btn-secondary"
            disabled={pending !== null}
            onClick={() => void run("incomplete")}
            type="button"
          >
            {pending === "incomplete" ? "Reopening…" : "Reopen for editing"}
          </button>
        ) : (
          <button
            className="btn-primary"
            disabled={pending !== null || !canMarkReady}
            onClick={() => void run("ready")}
            title={canMarkReady ? undefined : "Resolve the blocking checks first."}
            type="button"
          >
            {pending === "ready" ? "Marking…" : "Mark ready for analysis"}
          </button>
        )}
        <button
          className="btn-secondary"
          disabled={pending !== null}
          onClick={() => void run("validate")}
          type="button"
        >
          {pending === "validate" ? "Validating…" : "Re-check"}
        </button>
        <span className="self-center text-xs text-slate-500">
          {summary.requirements_total} requirements · {summary.criteria_count} criteria ·{" "}
          {summary.criteria_balanced ? "weights total 100%" : "weights do not total 100%"}
        </span>
      </div>
      <p className="sr-only">{statusLabel(assignment.status)}</p>
    </section>
  );
}
