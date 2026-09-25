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
import { Alert, SubmitButton } from "@/components/ui";

const SEVERITY_STYLES: Record<Constraint["severity"], string> = {
  INFO: "bg-slate-100 text-slate-600",
  WARNING: "bg-amber-50 text-amber-800",
  IMPORTANT: "bg-orange-50 text-orange-800",
  CRITICAL: "bg-red-50 text-red-800",
};

export function ConstraintsSection({
  specification,
  onChanged,
}: {
  specification: AssignmentSpecification;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { constraints, assignment } = specification;

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
    <section className="card p-6" data-testid="constraints-section" id="constraints">
      <div>
        <h2 className="section-title">Constraints</h2>
        <p className="mt-1 text-sm text-slate-500">
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
          <article className="rounded-xl border border-slate-200 p-4" key={constraint.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-slate-950">{constraint.title}</p>
                <p className="mt-1 text-sm leading-6 text-slate-600">{constraint.description}</p>
                {constraint.value ? (
                  <p className="mt-1 font-mono text-xs text-slate-500">{constraint.value}</p>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">
                    {constraintTypeLabel(constraint.type)}
                  </span>
                  <span className={`rounded px-2 py-0.5 ${SEVERITY_STYLES[constraint.severity]}`}>
                    {constraintSeverityLabel(constraint.severity)}
                  </span>
                </div>
              </div>
              <button
                aria-label={`Delete ${constraint.title}`}
                className="shrink-0 text-sm font-semibold text-red-600"
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
          <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
            No constraints recorded.
          </p>
        ) : null}
      </div>

      <form
        className="mt-5 grid gap-3 border-t border-slate-100 pt-5"
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
            <span>Title</span>
            <input maxLength={240} name="title" required type="text" />
          </label>
          <label className="field">
            <span>Type</span>
            <select defaultValue="OTHER" name="type">
              {CONSTRAINT_TYPE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {constraintTypeLabel(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>Description</span>
          <textarea maxLength={5000} name="description" required />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="field">
            <span>Value (optional)</span>
            <input maxLength={500} name="value" type="text" />
          </label>
          <label className="field">
            <span>Severity</span>
            <select defaultValue="WARNING" name="severity">
              {CONSTRAINT_SEVERITY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {constraintSeverityLabel(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <SubmitButton pending={pending === "add-constraint"} pendingLabel="Adding…">
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
          <h2 className="section-title">Evaluation criteria</h2>
          <p className="mt-1 text-sm text-slate-500">
            Weights must total exactly 100% before this specification is complete.
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-bold ${
            balanced ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"
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
          <article className="rounded-xl border border-slate-200 p-4" key={criterion.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-slate-950">{criterion.title}</p>
                {criterion.description ? (
                  <p className="mt-1 text-sm leading-6 text-slate-600">{criterion.description}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-700">
                  {formatWeight(criterion.weight)}
                </span>
                <button
                  aria-label={`Delete ${criterion.title}`}
                  className="text-sm font-semibold text-red-600"
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
          <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
            No criteria yet.
          </p>
        ) : null}
      </div>

      <form
        className="mt-5 grid gap-3 border-t border-slate-100 pt-5"
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
            <span>Criterion title</span>
            <input maxLength={240} name="title" required type="text" />
          </label>
          <label className="field">
            <span>Weight %</span>
            <input max={100} min={0} name="weight" required step="0.01" type="number" />
          </label>
        </div>
        <label className="field">
          <span>Description</span>
          <textarea maxLength={5000} name="description" />
        </label>
        <SubmitButton pending={pending === "add-criterion"} pendingLabel="Adding…">
          Add criterion
        </SubmitButton>
      </form>
    </section>
  );
}
