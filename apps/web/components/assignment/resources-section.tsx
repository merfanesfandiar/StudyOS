"use client";

import { ChangeEvent, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { formatDate, formatFileSize } from "@/lib/format";
import type { AssignmentSpecification, Document } from "@/lib/types";
import { Alert } from "@/components/ui";

/** Uploaded evidence. StudyOS stores and serves it; it does not interpret it. */
export function ResourcesSection({
  specification,
  onChanged,
}: {
  specification: AssignmentSpecification;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const { resources, assignment } = specification;

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setPending("upload");
    setError("");
    setNotice("");
    try {
      await api.uploadDocument(assignment.id, file);
      setNotice(`${file.name} uploaded.`);
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not upload the document.");
    } finally {
      event.target.value = "";
      setPending(null);
    }
  }

  async function download(item: Document) {
    setError("");
    try {
      await api.downloadDocument(item.id, item.filename);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not download the document.");
    }
  }

  async function remove(item: Document) {
    if (!window.confirm(`Delete ${item.filename}?`)) return;
    setPending(item.id);
    setError("");
    setNotice("");
    try {
      await api.deleteDocument(item.id);
      setNotice(`${item.filename} deleted.`);
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the document.");
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="card p-6" data-testid="resources-section" id="resources">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Resources</h2>
          <p className="mt-1 text-sm text-slate-500">
            Briefs, rubrics, and reference files. PDF, DOCX, MD, TXT, ZIP, and images up to 10 MB.
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">
          {resources.length}
        </span>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-4">
          <Alert tone="success">{notice}</Alert>
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {resources.map((item) => (
          <article
            className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"
            data-testid="document-item"
            key={item.id}
          >
            <div className="min-w-0">
              <p className="truncate font-semibold text-slate-950">{item.filename}</p>
              <p className="mt-1 text-xs text-slate-500">
                {formatFileSize(item.size)} · {item.mime_type} · {formatDate(item.created_at)}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                className="btn-secondary"
                onClick={() => void download(item)}
                type="button"
              >
                Download
              </button>
              <button
                aria-label={`Delete ${item.filename}`}
                className="text-sm font-semibold text-red-600"
                disabled={pending === item.id}
                onClick={() => void remove(item)}
                type="button"
              >
                Delete
              </button>
            </div>
          </article>
        ))}
        {resources.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
            No documents attached yet.
          </p>
        ) : null}
      </div>

      <label className="btn-secondary mt-5 w-full">
        {pending === "upload" ? "Uploading…" : "Upload document"}
        <input
          accept=".pdf,.txt,.docx,.md,.zip,.png,.jpg,.jpeg"
          className="sr-only"
          data-testid="document-upload"
          disabled={pending !== null}
          onChange={(event) => void upload(event)}
          type="file"
        />
      </label>
    </section>
  );
}
