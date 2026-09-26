"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  CONSTRAINT_SEVERITY_OPTIONS,
  CONSTRAINT_TYPE_OPTIONS,
  constraintSeverityLabel,
  constraintTypeLabel,
  formatWeight,
} from "@/lib/format";
import type { AssignmentSpecification, Constraint } from "@/lib/types";
import { usePreferences } from "@/components/preferences-provider";
import { Alert, SubmitButton } from "@/components/ui";

const SEVERITY_STYLES: Record<Constraint["severity"], string> = {
  INFO: "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)]",
  WARNING: "bg-[var(--color-caution-soft)] text-[var(--color-caution)]",
  IMPORTANT: "bg-[var(--color-caution)] text-[var(--color-caution)]",
  CRITICAL: "bg-[var(--color-critical-soft)] text-[var(--color-critical)]",
};

export function ConstraintsSection({
  specification,
  onChanged,
}: {
  specification: AssignmentSpecification;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const { t } = usePreferences();
  const [error, setError] = useState("");
  const { constraints, assignment } = specification;

  async function run(key: string, action: () => Promise<unknown>) {
    setPending(key);
    setError("");
    try {
      await action();
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t("content.saveFailed"));
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="card p-6" data-testid="constraints-section" id="constraints">
      <div>
        <h2 className="section-title">{t("constraints.title")}</h2>
        <p className="mt-1 text-sm text-[var(--color-ink-subtle)]">
          Rules the solution has to respect. Advisory: they lower the score, never block.
        </p>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {constraints.map((constraint) => (
          <article className="rounded-xl border border-[var(--color-line)] p-4" key={constraint.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-[var(--color-ink)]">{constraint.title}</p>
                <p className="mt-1 text-sm leading-6 text-[var(--color-ink-muted)]">{constraint.description}</p>
                {constraint.value ? (
                  <p className="mt-1 font-mono text-xs text-[var(--color-ink-subtle)]">{constraint.value}</p>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="rounded bg-[var(--color-surface-sunken)] px-2 py-0.5 text-[var(--color-ink-muted)]">
                    {constraintTypeLabel(t, constraint.type)}
                  </span>
                  <span className={`rounded px-2 py-0.5 ${SEVERITY_STYLES[constraint.severity]}`}>
                    {constraintSeverityLabel(t, constraint.severity)}
                  </span>
                </div>
              </div>
              <button
                aria-label={`Delete ${constraint.title}`}
                className="shrink-0 text-sm font-semibold text-[var(--color-critical)]"
                disabled={pending === `constraint-${constraint.id}`}
                onClick={() =>
                  void run(`constraint-${constraint.id}`, () =>
                    api.deleteConstraint(assignment.id, constraint.id),
                  )
                }
                type="button"
              >
                Delete
              </button>
            </div>
          </article>
        ))}
        {constraints.length === 0 ? (
          <p className="rounded-xl border border-dashed border-[var(--color-line)] p-4 text-sm text-[var(--color-ink-subtle)]">
            No constraints recorded.
          </p>
        ) : null}
      </div>

      <form
        className="mt-5 grid gap-3 border-t border-[var(--color-surface-sunken)] pt-5"
        onSubmit={(event) => {
          event.preventDefault();
          const element = event.currentTarget;
          const form = new FormData(element);
          void run("add-constraint", async () => {
            await api.createConstraint(assignment.id, {
              title: String(form.get("title") ?? ""),
              description: String(form.get("description") ?? ""),
              value: String(form.get("value") ?? "") || null,
              type: String(form.get("type") ?? "OTHER") as Constraint["type"],
              severity: String(form.get("severity") ?? "WARNING") as Constraint["severity"],
            });
            element.reset();
          });
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="field">
            <span>{t("requirements.fieldTitle")}</span>
            <input maxLength={240} name="title" required type="text" />
          </label>
          <label className="field">
            <span>{t("requirements.fieldType")}</span>
            <select defaultValue="OTHER" name="type">
              {CONSTRAINT_TYPE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {constraintTypeLabel(t, value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>{t("requirements.fieldDescription")}</span>
          <textarea maxLength={5000} name="description" required />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="field">
            <span>{t("constraints.valueOptional")}</span>
            <input maxLength={500} name="value" type="text" />
          </label>
          <label className="field">
            <span>{t("constraints.fieldSeverity")}</span>
            <select defaultValue="WARNING" name="severity">
              {CONSTRAINT_SEVERITY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {constraintSeverityLabel(t, value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <SubmitButton pending={pending === "add-constraint"} pendingLabel={t("action.adding")}>
          Add constraint
        </SubmitButton>
      </form>
    </section>
  );
}

export function CriteriaSection({
  specification,
  onChanged,
}: {
  specification: AssignmentSpecification;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { t } = usePreferences();
  const { evaluation_criteria: criteria, assignment, criteria_total: total } = specification;
  const balanced = criteria.reduce((sum, item) => sum + Number(item.weight), 0) === 100;

  async function run(key: string, action: () => Promise<unknown>) {
    setPending(key);
    setError("");
    try {
      await action();
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "That change could not be saved.");
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="card p-6" data-testid="criteria-section" id="criteria">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{t("criteria.title")}</h2>
          <p className="mt-1 text-sm text-[var(--color-ink-subtle)]">
            Weights must total exactly 100% before this specification is complete.
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-bold ${
            balanced ? "bg-[var(--color-positive-soft)] text-[var(--color-positive)]" : "bg-[var(--color-caution-soft)] text-[var(--color-caution)]"
          }`}
        >
          {formatWeight(total)} of 100%
        </span>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {criteria.map((criterion) => (
          <article className="rounded-xl border border-[var(--color-line)] p-4" key={criterion.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-[var(--color-ink)]">{criterion.title}</p>
                {criterion.description ? (
                  <p className="mt-1 text-sm leading-6 text-[var(--color-ink-muted)]">{criterion.description}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="rounded bg-[var(--color-surface-sunken)] px-2 py-1 text-xs font-bold text-[var(--color-ink-muted)]">
                  {formatWeight(criterion.weight)}
                </span>
                <button
                  aria-label={`Delete ${criterion.title}`}
                  className="text-sm font-semibold text-[var(--color-critical)]"
                  disabled={pending === `criterion-${criterion.id}`}
                  onClick={() =>
                    void run(`criterion-${criterion.id}`, () =>
                      api.deleteCriterion(assignment.id, criterion.id),
                    )
                  }
                  type="button"
                >
                  Delete
                </button>
              </div>
            </div>
          </article>
        ))}
        {criteria.length === 0 ? (
          <p className="rounded-xl border border-dashed border-[var(--color-line)] p-4 text-sm text-[var(--color-ink-subtle)]">
            No criteria yet.
          </p>
        ) : null}
      </div>

      <form
        className="mt-5 grid gap-3 border-t border-[var(--color-surface-sunken)] pt-5"
        onSubmit={(event) => {
          event.preventDefault();
          const element = event.currentTarget;
          const form = new FormData(element);
          void run("add-criterion", async () => {
            await api.createCriterion(assignment.id, {
              title: String(form.get("title") ?? ""),
              description: String(form.get("description") ?? "") || null,
              weight: String(form.get("weight") ?? "0"),
            });
            element.reset();
          });
        }}
      >
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
          <label className="field">
            <span>{t("criteria.fieldTitle")}</span>
            <input maxLength={240} name="title" required type="text" />
          </label>
          <label className="field">
            <span>{t("criteria.fieldWeight")}</span>
            <input max={100} min={0} name="weight" required step="0.01" type="number" />
          </label>
        </div>
        <label className="field">
          <span>{t("requirements.fieldDescription")}</span>
          <textarea maxLength={5000} name="description" />
        </label>
        <SubmitButton pending={pending === "add-criterion"} pendingLabel="Adding…">
          Add criterion
        </SubmitButton>
      </form>
    </section>
  );
}
