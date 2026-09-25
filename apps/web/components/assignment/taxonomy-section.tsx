"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  DELIVERABLE_STATUS_OPTIONS,
  DELIVERABLE_TYPE_OPTIONS,
  TECHNOLOGY_CATEGORY_OPTIONS,
  deliverableStatusLabel,
  deliverableTypeLabel,
  humanize,
  technologyCategoryLabel,
} from "@/lib/format";
import type { AssignmentSpecification, Deliverable, Technology } from "@/lib/types";
import { Alert, SubmitButton } from "@/components/ui";

export function DeliverablesSection({
  specification,
  onChanged,
}: {
  specification: AssignmentSpecification;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { deliverables, assignment } = specification;

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
    <section className="card p-6" data-testid="deliverables-section" id="deliverables">
      <div>
        <h2 className="section-title">Deliverables</h2>
        <p className="mt-1 text-sm text-slate-500">What has to be handed in, and its state.</p>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {deliverables.map((deliverable) => (
          <article className="rounded-xl border border-slate-200 p-4" key={deliverable.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-slate-950">{deliverable.title}</p>
                {deliverable.description ? (
                  <p className="mt-1 text-sm leading-6 text-slate-600">{deliverable.description}</p>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span className="rounded bg-slate-100 px-2 py-0.5">
                    {deliverableTypeLabel(deliverable.type)}
                  </span>
                  <span className="rounded bg-slate-100 px-2 py-0.5">
                    {deliverable.is_required ? "Required" : "Optional"}
                  </span>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <label className="sr-only" htmlFor={`deliverable-${deliverable.id}`}>
                  Status for {deliverable.title}
                </label>
                <select
                  className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
                  id={`deliverable-${deliverable.id}`}
                  onChange={(event) =>
                    void run(`deliverable-${deliverable.id}`, () =>
                      api.updateDeliverable(assignment.id, deliverable.id, {
                        status: event.target.value as Deliverable["status"],
                      }),
                    )
                  }
                  value={deliverable.status}
                >
                  {DELIVERABLE_STATUS_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {deliverableStatusLabel(value)}
                    </option>
                  ))}
                </select>
                <button
                  aria-label={`Delete ${deliverable.title}`}
                  className="text-sm font-semibold text-red-600"
                  disabled={pending === `deliverable-${deliverable.id}`}
                  onClick={() =>
                    void run(`deliverable-${deliverable.id}`, () =>
                      api.deleteDeliverable(assignment.id, deliverable.id),
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
        {deliverables.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
            No deliverables listed yet.
          </p>
        ) : null}
      </div>

      <form
        className="mt-5 grid gap-3 border-t border-slate-100 pt-5"
        onSubmit={(event) => {
          event.preventDefault();
          const element = event.currentTarget;
          const form = new FormData(element);
          void run("add-deliverable", async () => {
            await api.createDeliverable(assignment.id, {
              title: String(form.get("title") ?? ""),
              description: String(form.get("description") ?? "") || null,
              type: String(form.get("type") ?? "OTHER") as Deliverable["type"],
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
            <select defaultValue="SOURCE_CODE" name="type">
              {DELIVERABLE_TYPE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {deliverableTypeLabel(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span>Description</span>
          <textarea maxLength={5000} name="description" />
        </label>
        <SubmitButton pending={pending === "add-deliverable"} pendingLabel="Adding…">
          Add deliverable
        </SubmitButton>
      </form>
    </section>
  );
}

export function TaxonomySection({
  specification,
  onChanged,
}: {
  specification: AssignmentSpecification;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { technologies, tags, assignment } = specification;

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
    <section className="card p-6" data-testid="taxonomy-section" id="stack">
      <div>
        <h2 className="section-title">Tools and tags</h2>
        <p className="mt-1 text-sm text-slate-500">
          Technologies and tags are shared across the workspace, so they are entered once.
        </p>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="mt-5 grid gap-6 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Technologies</h3>
          <ul className="mt-3 space-y-2">
            {technologies.map((technology) => (
              <li
                className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm"
                key={technology.id}
              >
                <span className="min-w-0">
                  <span className="font-semibold text-slate-900">{technology.name}</span>
                  {technology.version ? (
                    <span className="text-slate-500"> {technology.version}</span>
                  ) : null}
                  <span className="block text-xs text-slate-500">
                    {technologyCategoryLabel(technology.category)}
                  </span>
                </span>
                <button
                  aria-label={`Remove ${technology.name}`}
                  className="shrink-0 text-sm font-semibold text-red-600"
                  onClick={() =>
                    void run(`technology-${technology.id}`, () =>
                      api.deleteTechnology(assignment.id, technology.id),
                    )
                  }
                  type="button"
                >
                  Remove
                </button>
              </li>
            ))}
            {technologies.length === 0 ? (
              <li className="rounded-lg border border-dashed border-slate-200 p-3 text-sm text-slate-500">
                None recorded.
              </li>
            ) : null}
          </ul>
          <form
            className="mt-3 space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              const element = event.currentTarget;
              const form = new FormData(element);
              void run("add-technology", async () => {
                await api.addTechnology(assignment.id, {
                  name: String(form.get("name") ?? ""),
                  version: String(form.get("version") ?? ""),
                  category: String(form.get("category") ?? "OTHER") as Technology["category"],
                });
                element.reset();
              });
            }}
          >
            <label className="field">
              <span>Name</span>
              <input maxLength={120} name="name" required type="text" />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="field">
                <span>Version</span>
                <input maxLength={60} name="version" type="text" />
              </label>
              <label className="field">
                <span>Category</span>
                <select defaultValue="LANGUAGE" name="category">
                  {TECHNOLOGY_CATEGORY_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {technologyCategoryLabel(value)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <SubmitButton
              className="btn-secondary"
              pending={pending === "add-technology"}
              pendingLabel="Adding…"
            >
              Add technology
            </SubmitButton>
          </form>
        </div>

        <div>
          <h3 className="text-sm font-semibold text-slate-900">Tags</h3>
          <ul className="mt-3 flex flex-wrap gap-2">
            {tags.map((tag) => (
              <li
                className="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1 text-sm text-indigo-800"
                key={tag.id}
              >
                {tag.name}
                <button
                  aria-label={`Remove ${tag.name}`}
                  className="font-bold text-indigo-500"
                  onClick={() =>
                    void run(`tag-${tag.id}`, () => api.deleteTag(assignment.id, tag.id))
                  }
                  type="button"
                >
                  ×
                </button>
              </li>
            ))}
            {tags.length === 0 ? (
              <li className="rounded-lg border border-dashed border-slate-200 p-3 text-sm text-slate-500">
                None yet.
              </li>
            ) : null}
          </ul>
          <form
            className="mt-3 space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              const element = event.currentTarget;
              const form = new FormData(element);
              void run("add-tag", async () => {
                await api.addTag(assignment.id, String(form.get("name") ?? ""));
                element.reset();
              });
            }}
          >
            <label className="field">
              <span>Tag</span>
              <input maxLength={60} name="name" required type="text" />
            </label>
            <SubmitButton className="btn-secondary" pending={pending === "add-tag"} pendingLabel="Adding…">
              Add tag
            </SubmitButton>
          </form>
        </div>
      </div>
      <p className="sr-only">{humanize("workspace catalogue")}</p>
    </section>
  );
}
