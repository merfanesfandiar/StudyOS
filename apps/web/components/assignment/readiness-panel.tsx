"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import { CHECK_LABELS, labelFor, statusLabel } from "@/lib/format";
import type { AssignmentSpecification } from "@/lib/types";
import { usePreferences } from "@/components/preferences-provider";
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
  const [failure, setFailure] = useState<unknown>(null);
  // The notice is a catalogue key plus its arguments, not a finished sentence,
  // so it reads in the reader's language rather than the language active when
  // the click happened.
  const [notice, setNotice] = useState<{
    key: "readiness.markedReady" | "readiness.reopened" | "readiness.valid";
    vars?: { score: number; missing: string };
    status: string;
  } | null>(null);
  const { t } = usePreferences();
  const { readiness, assignment, summary } = specification;
  const canMarkReady = readiness.is_ready_for_analysis;
  const isReady = assignment.status === "READY_FOR_ANALYSIS";

  async function run(action: "ready" | "incomplete" | "validate") {
    setPending(action);
    setFailure(null);
    setNotice(null);
    try {
      if (action === "ready") {
        const updated = await api.markReady(assignment.id);
        setNotice({
          key: "readiness.markedReady",
          vars: { score: updated.readiness_score, missing: "" },
          status: updated.status,
        });
      } else if (action === "incomplete") {
        const updated = await api.markIncomplete(assignment.id);
        setNotice({
          key: "readiness.reopened",
          status: updated.status,
        });
      } else {
        const report = await api.validate(assignment.id);
        setNotice({
          key: "readiness.valid",
          vars: {
            score: report.readiness.score,
            missing: report.readiness.failing_checks
              .map((field) => labelFor(t, "readiness.field", field))
              .join("، "),
          },
          status: assignment.status,
        });
      }
      await onChanged();
    } catch (caught) {
      setFailure(caught);
    } finally {
      setPending(null);
    }
  }

  const error = failure
    ? errorMessage(failure, t, "readiness.refused")
    : "";
  // A confirmation only applies to the state it confirmed, so a later demotion
  // cannot leave "marked ready" on screen next to an incomplete badge.
  const shownNotice = notice?.status === assignment.status ? t(notice.key, notice.vars) : "";

  return (
    <section className="card p-6" data-testid="readiness-panel" id="readiness">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{t("readiness.title")}</h2>
          <p className="mt-1 text-sm text-[var(--color-ink-subtle)]">
            {t("readiness.description")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={assignment.status} />
          <span className="rounded-full bg-[var(--color-surface-sunken)] px-2.5 py-1 text-xs font-bold text-[var(--color-ink-muted)]">
            {readiness.score}%
          </span>
        </div>
      </div>

      <div className="mt-4">
        <ReadinessMeter score={readiness.score} bar={readiness.completeness_bar} />
        <p className="mt-2 text-xs text-[var(--color-ink-subtle)]">
          {readiness.is_ready_for_analysis
            ? isReady
              ? t("readiness.stateReady")
              : t("readiness.stateCanMark")
            : t("readiness.stateBlocked")}
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
        <div className="mt-4 rounded-xl border border-[var(--color-critical-soft)] bg-[var(--color-critical-soft)] p-4">
          <p className="text-sm font-bold text-[var(--color-critical)]">{t("readiness.blocking")}</p>
          <ul className="mt-2 space-y-1 text-sm text-[var(--color-critical)]">
            {readiness.failing_checks.map((field) => (
              <li key={field}>
                <span className="font-semibold">{labelFor(t, "readiness.field", field)}:</span>{" "}
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
              <span className="font-semibold text-[var(--color-ink)]">{check.label}</span>{" "}
              <span className="text-xs text-[var(--color-ink-subtle)]">
                {t(CHECK_LABELS[check.status])} · {check.weight}%
                {check.blocking ? ` · ${t("readiness.required")}` : ""}
              </span>
              <span className="block text-xs leading-5 text-[var(--color-ink-subtle)]">{check.message}</span>
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-5 flex flex-wrap gap-2 border-t border-[var(--color-surface-sunken)] pt-5">
        {isReady ? (
          <button
            className="btn-secondary"
            disabled={pending !== null}
            onClick={() => void run("incomplete")}
            type="button"
          >
            {pending === "incomplete" ? t("readiness.reopening") : t("readiness.reopen")}
          </button>
        ) : (
          <button
            className="btn-primary"
            disabled={pending !== null || !canMarkReady}
            onClick={() => void run("ready")}
            title={canMarkReady ? undefined : t("readiness.resolveFirst")}
            type="button"
          >
            {pending === "ready" ? t("readiness.marking") : t("readiness.markReady")}
          </button>
        )}
        <button
          className="btn-secondary"
          disabled={pending !== null}
          onClick={() => void run("validate")}
          type="button"
        >
          {pending === "validate" ? t("readiness.validating") : t("readiness.recheck")}
        </button>
        <span className="self-center text-xs text-[var(--color-ink-subtle)]">
          {t("readiness.tally", {
            requirements: summary.requirements_total,
            criteria: summary.criteria_count,
            weights: summary.criteria_balanced
              ? t("readiness.weightsBalanced")
              : t("readiness.weightsUnbalanced"),
          })}
        </span>
      </div>
      <p className="sr-only">{statusLabel(t, assignment.status)}</p>
    </section>
  );
}
