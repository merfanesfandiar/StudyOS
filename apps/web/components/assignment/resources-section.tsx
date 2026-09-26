"use client";

import { ChangeEvent, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import { formatFileSize } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n/messages";
import type { AssignmentSpecification, Document } from "@/lib/types";
import { usePreferences } from "@/components/preferences-provider";
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
  // The caught value and the key for its fallback are kept together, so the
  // message is chosen at render time from the catalogue rather than at catch
  // time. Catching a non-ApiError here means something below the API layer
  // broke, and each operation has its own way of saying so.
  const [failure, setFailure] = useState<{ caught: unknown; key: MessageKey } | null>(null);
  const [notice, setNotice] = useState("");
  const { t, formatDate } = usePreferences();
  const { resources, assignment } = specification;

  const error = failure ? errorMessage(failure.caught, t, failure.key) : "";

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setPending("upload");
    setFailure(null);
    setNotice("");
    try {
      await api.uploadDocument(assignment.id, file);
      setNotice(t("resources.uploaded", { name: file.name }));
      await onChanged();
    } catch (caught) {
      setFailure({ caught, key: "resources.uploadFailed" });
    } finally {
      event.target.value = "";
      setPending(null);
    }
  }

  async function download(item: Document) {
    setFailure(null);
    try {
      await api.downloadDocument(item.id, item.filename);
    } catch (caught) {
      setFailure({ caught, key: "resources.downloadFailed" });
    }
  }

  async function remove(item: Document) {
    if (!window.confirm(t("resources.deleteConfirm", { name: item.filename }))) return;
    setPending(item.id);
    setFailure(null);
    setNotice("");
    try {
      await api.deleteDocument(item.id);
      setNotice(t("resources.deleted", { name: item.filename }));
      await onChanged();
    } catch (caught) {
      setFailure({ caught, key: "resources.deleteFailed" });
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="card p-6" data-testid="resources-section" id="resources">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{t("resources.title")}</h2>
          <p className="mt-1 text-sm text-[var(--color-ink-subtle)]">
            {t("resources.description")}
          </p>
        </div>
        <span className="rounded-full bg-[var(--color-surface-sunken)] px-2.5 py-1 text-xs font-bold text-[var(--color-ink-muted)]">
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
            className="flex items-center justify-between gap-3 rounded-xl border border-[var(--color-line)] p-4"
            data-testid="document-item"
            key={item.id}
          >
            <div className="min-w-0">
              <p className="truncate font-semibold text-[var(--color-ink)]">{item.filename}</p>
              <p className="mt-1 text-xs text-[var(--color-ink-subtle)]">
                {formatFileSize(item.size)} · {item.mime_type} · {formatDate(item.created_at)}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                className="btn-secondary"
                onClick={() => void download(item)}
                type="button"
              >
                {t("resources.download")}
              </button>
              <button
                aria-label={t("resources.deleteNamed", { name: item.filename })}
                className="text-sm font-semibold text-[var(--color-critical)]"
                disabled={pending === item.id}
                onClick={() => void remove(item)}
                type="button"
              >
                {t("action.delete")}
              </button>
            </div>
          </article>
        ))}
        {resources.length === 0 ? (
          <p className="rounded-xl border border-dashed border-[var(--color-line)] p-4 text-sm text-[var(--color-ink-subtle)]">
            {t("resources.empty")}
          </p>
        ) : null}
      </div>

      <label className="btn-secondary mt-5 w-full">
        {pending === "upload" ? t("resources.uploading") : t("resources.upload")}
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
