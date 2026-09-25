"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  PRIORITY_OPTIONS,
  REQUIREMENT_STATUS_OPTIONS,
  REQUIREMENT_TYPE_OPTIONS,
  priorityLabel,
  requirementStatusLabel,
  requirementTypeLabel,
} from "@/lib/format";
import type { AssignmentSpecification, DependencyGraph, Requirement } from "@/lib/types";
import { Alert, SubmitButton } from "@/components/ui";

/** Requirements carry the codes everything else refers to, so they lead. */
export function RequirementsSection({
  specification,
  graph,
  onChanged,
}: {
  specification: AssignmentSpecification;
  graph: DependencyGraph | null;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [dependencyFor, setDependencyFor] = useState<string | null>(null);
  const { requirements, assignment } = specification;
  const completed = requirements.filter(
    (item) => item.status === "COMPLETED" || item.status === "VERIFIED",
  ).length;

  const dependenciesOf = (requirementId: string) =>
    (graph?.edges ?? []).filter((edge) => edge.requirement_id === requirementId);

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
    <section className="card p-6" data-testid="requirements-section" id="requirements">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Requirements</h2>
          <p className="mt-1 text-sm text-slate-500">
            Numbered once and never reused, so references stay valid after a deletion.
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">
          {completed}/{requirements.length} done
        </span>
      </div>

      {graph?.execution_order.length ? (
        <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
          A safe order to work in:{" "}
          <span className="font-semibold text-slate-800">
            {graph.execution_order.join(" → ")}
          </span>
        </p>
      ) : null}

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <ol className="mt-5 space-y-3">
        {requirements.map((requirement) => (
          <li className="rounded-xl border border-slate-200 p-4" key={requirement.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-bold uppercase tracking-wider text-indigo-600">
                  {requirement.code}
                </p>
                <p className="mt-0.5 font-semibold text-slate-950">{requirement.title}</p>
                {requirement.description ? (
                  <p className="mt-1 text-sm leading-6 text-slate-600">{requirement.description}</p>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span className="rounded bg-slate-100 px-2 py-0.5">
                    {requirementTypeLabel(requirement.type)}
                  </span>
                  <span className="rounded bg-slate-100 px-2 py-0.5">
                    {priorityLabel(requirement.priority)}
                  </span>
                  <span className="rounded bg-slate-100 px-2 py-0.5">
                    {requirement.is_required ? "Required" : "Optional"}
                  </span>
                  {dependenciesOf(requirement.id).length ? (
                    <span className="rounded bg-indigo-50 px-2 py-0.5 text-indigo-700">
                      Needs{" "}
                      {dependenciesOf(requirement.id)
                        .map((edge) => edge.depends_on_code)
                        .join(", ")}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <label className="sr-only" htmlFor={`status-${requirement.id}`}>
                  Status for {requirement.code}
                </label>
                <select
                  className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
                  disabled={pending === `requirement-${requirement.id}`}
                  id={`status-${requirement.id}`}
                  onChange={(event) =>
                    void run(`requirement-${requirement.id}`, () =>
                      api.updateRequirement(assignment.id, requirement.id, {
                        status: event.target.value as Requirement["status"],
                      }),
                    )
                  }
                  value={requirement.status}
                >
                  {REQUIREMENT_STATUS_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {requirementStatusLabel(value)}
                    </option>
                  ))}
                </select>
                <button
                  className="text-sm font-semibold text-indigo-700"
                  onClick={() => setDependencyFor(requirement.id)}
                  type="button"
                >
                  Depends on
                </button>
                <button
                  aria-label={`Delete ${requirement.code}`}
                  className="text-sm font-semibold text-red-600"
                  disabled={pending === `requirement-${requirement.id}`}
                  onClick={() =>
                    void run(`requirement-${requirement.id}`, () =>
                      api.deleteRequirement(assignment.id, requirement.id),
                    )
                  }
                  type="button"
                >
                  Delete
                </button>
              </div>
            </div>
            {dependenciesOf(requirement.id).length ? (
              <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3">
                {dependenciesOf(requirement.id).map((edge) => (
                  <li className="flex items-center justify-between text-xs" key={edge.depends_on_id}>
                    <span className="text-slate-600">Depends on {edge.depends_on_code}</span>
                    <button
                      className="font-semibold text-red-600"
                      disabled={pending === `dependency-${edge.depends_on_id}`}
                      onClick={() =>
                        void run(`dependency-${edge.depends_on_id}`, async () => {
                          const current = await api.dependencies(assignment.id, requirement.id);
                          const match = current.find(
                            (item) => item.depends_on_id === edge.depends_on_id,
                          );
                          if (match) {
                            await api.deleteDependency(assignment.id, requirement.id, match.id);
                          }
                        })
                      }
                      type="button"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>
      {requirements.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
          No requirements yet. The readiness gate needs at least one.
        </p>
      ) : null}

      <form
        className="mt-5 grid gap-3 border-t border-slate-100 pt-5"
        onSubmit={(event) => {
          event.preventDefault();
          const element = event.currentTarget;
          const form = new FormData(element);
          void run("add-requirement", async () => {
            await api.createRequirement(assignment.id, {
              title: String(form.get("title") ?? ""),
              description: String(form.get("description") ?? "") || null,
              type: String(form.get("type") ?? "FUNCTIONAL") as Requirement["type"],
              priority: String(form.get("priority") ?? "MEDIUM") as Requirement["priority"],
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
            <select defaultValue="FUNCTIONAL" name="type">
              {REQUIREMENT_TYPE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {requirementTypeLabel(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>Description</span>
          <textarea maxLength={5000} name="description" />
        </label>
        <div className="flex items-end gap-3">
          <label className="field flex-1">
            <span>Priority</span>
            <select defaultValue="MEDIUM" name="priority">
              {PRIORITY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {priorityLabel(value)}
                </option>
              ))}
            </select>
          </label>
          <SubmitButton pending={pending === "add-requirement"} pendingLabel="Adding…">
            Add requirement
          </SubmitButton>
        </div>
      </form>

      {dependencyFor ? (
        <DependencyPicker
          onClose={() => setDependencyFor(null)}
          onCreate={(dependsOnId) =>
            void run("add-dependency", async () => {
              await api.addDependency(assignment.id, dependencyFor, dependsOnId);
              setDependencyFor(null);
            })
          }
          pending={pending === "add-dependency"}
          requirement={requirements.find((item) => item.id === dependencyFor) ?? null}
          requirements={requirements.filter((item) => item.id !== dependencyFor)}
        />
      ) : null}
    </section>
  );
}

function DependencyPicker({
  requirement,
  requirements,
  pending,
  onCreate,
  onClose,
}: {
  requirement: Requirement | null;
  requirements: Requirement[];
  pending: boolean;
  onCreate: (dependsOnId: string) => void;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState("");
  return (
    <div className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
      <p className="text-sm font-semibold text-indigo-900">
        What must exist before {requirement?.code}?
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="field flex-1">
          <span>Depends on</span>
          <select onChange={(event) => setSelected(event.target.value)} value={selected}>
            <option value="">Choose a requirement</option>
            {requirements.map((item) => (
              <option key={item.id} value={item.id}>
                {item.code} — {item.title}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn-primary"
          disabled={!selected || pending}
          onClick={() => onCreate(selected)}
          type="button"
        >
          {pending ? "Adding…" : "Add dependency"}
        </button>
        <button className="btn-secondary" onClick={onClose} type="button">
          Cancel
        </button>
      </div>
    </div>
  );
}
