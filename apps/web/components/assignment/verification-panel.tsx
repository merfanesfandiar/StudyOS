"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, LoadingState } from "@/components/ui";
import { usePreferences } from "@/components/preferences-provider";
import { api } from "@/lib/api";
import {
  isVerificationReport,
  type VerificationReport,
  type VerificationRunSummary,
} from "@/lib/verification-types";

/**
 * The verification panel.
 *
 * Phase 10's honesty rules are rendered, not hidden: the verdict is labelled as
 * StudyOS's own estimate (never an instructor grade), unverified areas are
 * listed alongside failures, and every finding says which validator produced
 * it and whether it is heuristic.
 */

type PanelState = {
  runs: VerificationRunSummary[];
  report: VerificationReport | null;
  loading: boolean;
  busy: boolean;
  error: string;
};

const INITIAL: PanelState = { runs: [], report: null, loading: true, busy: false, error: "" };

const SEVERITY_TONE: Record<string, string> = {
  CRITICAL: "critical",
  HIGH: "critical",
  MEDIUM: "warning",
  LOW: "info",
  INFORMATIONAL: "info",
};

const VERDICT_TONE: Record<string, string> = {
  VERIFIED: "success",
  PARTIAL: "warning",
  FAILED: "critical",
};

function severityClass(severity: string): string {
  switch (SEVERITY_TONE[severity]) {
    case "critical":
      return "text-[var(--color-danger,#b91c1c)] font-semibold";
    case "warning":
      return "text-amber-600 font-medium";
    default:
      return "";
  }
}

export function VerificationPanel({ assignmentId }: { assignmentId: string }) {
  const { t } = usePreferences();
  const [state, setState] = useState<PanelState>(INITIAL);

  const load = useCallback(
    async (id: string) => {
      const page = await api.verificationRuns(id);
      const latest = page.items[0] ?? null;
      const report =
        latest && latest.status === "COMPLETED"
          ? await api.verificationReport(id, latest.id).catch(() => null)
          : null;
      return {
        runs: page.items,
        report: report && isVerificationReport(report) ? report : null,
      };
    },
    [],
  );

  const read = useCallback(
    async (id: string) => {
      try {
        const loaded = await load(id);
        setState({
          ...loaded,
          loading: false,
          busy: false,
          error: "",
        });
      } catch {
        setState((previous) => ({
          ...previous,
          runs: [],
          report: null,
          loading: false,
          busy: false,
          error: t("verification.loadFailed"),
        }));
      }
    },
    [t, load],
  );

  useEffect(() => {
    let active = true;
    load(assignmentId).then(
      (loaded) => {
        if (active) {
          setState({ ...loaded, loading: false, busy: false, error: "" });
        }
      },
      () => {
        if (active) {
          setState({ runs: [], report: null, loading: false, busy: false, error: t("verification.loadFailed") });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId, load, t]);

  const trigger = useCallback(
    async (reVerificationOf: string | null) => {
      setState((previous) => ({ ...previous, busy: true, error: "" }));
      try {
        await api.triggerVerification(assignmentId, {
          scope: "FULL",
          re_verification_of: reVerificationOf,
          idempotency_key: `panel-${Date.now()}`,
        });
        await read(assignmentId);
      } catch {
        setState((previous) => ({ ...previous, busy: false, error: t("verification.runFailed") }));
      }
    },
    [assignmentId, read, t],
  );

  if (state.loading) {
    return <LoadingState label={t("common.loading")} />;
  }

  const { report } = state;
  const rubricSummary = (report?.summary as { rubric?: { weighted_total?: number | null; ambiguities?: string[] } } | undefined)?.rubric;

  return (
    <section aria-labelledby="verification-heading" data-testid="verification-panel">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="verification-heading" className="text-lg font-semibold">
          {t("verification.title")}
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-md border px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            disabled={state.busy}
            onClick={() => void trigger(null)}
          >
            {state.busy ? t("verification.running") : t("verification.run")}
          </button>
          {report ? (
            <button
              type="button"
              className="rounded-md border px-3 py-1.5 text-sm font-medium disabled:opacity-50"
              disabled={state.busy}
              onClick={() => void trigger(report.id)}
            >
              {t("verification.rerun")}
            </button>
          ) : null}
        </div>
      </div>

      {state.error ? <Alert>{state.error}</Alert> : null}

      {!report ? (
        <p className="text-sm text-[var(--color-muted,#6b7280)]">
          {t("verification.noRuns")}
        </p>
      ) : (
        <div className="space-y-4">
          <div
            className={
              "rounded-lg border p-4 " +
              (VERDICT_TONE[report.verdict ?? ""] === "critical"
                ? "border-red-300 bg-red-50"
                : VERDICT_TONE[report.verdict ?? ""] === "warning"
                  ? "border-amber-300 bg-amber-50"
                  : "border-emerald-300 bg-emerald-50")
            }
            data-testid="verification-verdict"
          >
            <p className="font-semibold">
              {t("verification.verdictLabel", { verdict: report.verdict ?? "UNVERIFIED" })}
            </p>
            <p className="text-sm">
              {t("verification.completion", { percent: report.completion_percentage })}
            </p>
            <p className="text-xs text-[var(--color-muted,#6b7280)]">
              {t("verification.estimateNote")}
            </p>
          </div>

          {report.requirements.length > 0 ? (
            <div data-testid="verification-requirements">
              <h3 className="mb-2 text-sm font-semibold">{t("verification.requirements")}</h3>
              <ul className="space-y-1 text-sm">
                {report.requirements.map((row) => (
                  <li key={row.requirement_id}>
                    <span className="font-medium">{row.code}</span>{" "}
                    <span className={severityClass(row.status === "FAILED" ? "HIGH" : "LOW")}>
                      {row.status}
                    </span>{" "}
                    — {row.explanation}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {report.findings.length > 0 ? (
            <div data-testid="verification-findings">
              <h3 className="mb-2 text-sm font-semibold">{t("verification.findings")}</h3>
              <ul className="space-y-2 text-sm">
                {report.findings.slice(0, 12).map((finding) => (
                  <li key={finding.id} className="rounded-md border p-3">
                    <p className={severityClass(finding.severity)}>
                      {finding.severity} · {finding.validator}
                      {finding.heuristic ? ` · ${t("verification.heuristic")}` : ""}
                    </p>
                    <p className="font-medium">{finding.title}</p>
                    <p>{finding.description}</p>
                    {finding.recommendation ? (
                      <p className="text-[var(--color-muted,#6b7280)]">
                        {t("verification.recommendation")}: {finding.recommendation}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {rubricSummary ? (
            <div data-testid="verification-rubric">
              <h3 className="mb-2 text-sm font-semibold">{t("verification.rubric")}</h3>
              {typeof rubricSummary.weighted_total === "number" ? (
                <p className="text-sm">
                  {t("verification.weightedTotal", {
                    percent: Math.round(rubricSummary.weighted_total * 100),
                  })}
                </p>
              ) : null}
              {(rubricSummary.ambiguities ?? []).length > 0 ? (
                <Alert>{t("verification.rubricAmbiguous")}</Alert>
              ) : null}
            </div>
          ) : null}

          <details>
            <summary className="cursor-pointer text-sm font-semibold">
              {t("verification.limitations")}
            </summary>
            <ul className="mt-2 space-y-1 text-sm text-[var(--color-muted,#6b7280)]">
              {((report.summary as { limitations?: string[] }).limitations ?? []).map(
                (limitation, index) => (
                  <li key={index}>• {limitation}</li>
                ),
              )}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}
