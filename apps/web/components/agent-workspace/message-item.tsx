"use client";

import { useState } from "react";
import { Markdown } from "./markdown";
import type { ConversationMessage } from "@/lib/conversations-types";
import type { Translate } from "@/lib/i18n/translate";

/**
 * One message in the workspace thread.
 *
 * Reference messages (ARTIFACT / VERIFICATION / RUN_SUMMARY) carry pointers to
 * the source of truth in `metadata_json` and render as cards that name the
 * record — they never restate or re-render content the backend owns. USER
 * messages can be edited only when `canEdit` is set: the backend enforces
 * "most recent user message", and the UI mirrors that honestly.
 */
export function MessageItem({
  message,
  t,
  canEdit,
  onEdit,
}: {
  message: ConversationMessage;
  t: Translate;
  canEdit: boolean;
  onEdit: (messageId: string, content: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const isUser = message.role === "USER";
  const edited = message.edited_revision > 1;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_500);
    } catch {
      // Clipboard may be unavailable; not worth an error surface.
    }
  };

  const saveEdit = async () => {
    if (!draft.trim() || draft.trim() === message.content) {
      setEditing(false);
      return;
    }
    setSaving(true);
    const ok = await onEdit(message.id, draft.trim());
    setSaving(false);
    if (ok) setEditing(false);
  };

  return (
    <article
      aria-label={t(`workspace.message.role.${message.role.toLowerCase()}` as never)}
      className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}
    >
      <span className="text-xs font-medium text-[var(--color-ink-muted)]">
        {t(`workspace.message.role.${message.role.toLowerCase()}` as never)}
      </span>

      {message.kind === "ARTIFACT" ? (
        <ReferenceCard
          title={t("workspace.message.artifact")}
          pointer={String(message.metadata_json.artifact_id ?? "")}
          t={t}
        />
      ) : message.kind === "VERIFICATION" ? (
        <ReferenceCard
          title={t("workspace.message.verification")}
          pointer={String(message.metadata_json.verification_run_id ?? "")}
          t={t}
        />
      ) : editing ? (
        <div className="w-full max-w-full">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={3}
            className="field w-full resize-y"
            aria-label={t("workspace.message.edit")}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void saveEdit()}
              disabled={saving}
              className="btn-primary px-3 py-1.5 text-sm"
            >
              {t("workspace.message.saveEdit")}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setDraft(message.content);
              }}
              className="btn-ghost px-3 py-1.5 text-sm"
            >
              {t("workspace.message.cancelEdit")}
            </button>
          </div>
        </div>
      ) : (
        <div
          className={`w-fit max-w-[92%] rounded-[var(--radius-card)] border px-4 py-3 ${
            isUser
              ? "border-transparent bg-[var(--color-accent-soft)]"
              : "border-[var(--color-line)] bg-[var(--color-surface)]"
          }`}
        >
          <Markdown>{message.content}</Markdown>
        </div>
      )}

      <div className="flex items-center gap-2 text-xs text-[var(--color-ink-subtle)]">
        <button
          type="button"
          onClick={() => void copy()}
          className="rounded-md px-1.5 py-0.5 hover:bg-[var(--color-surface-sunken)]"
          aria-label={t("workspace.message.copy")}
        >
          {copied ? t("workspace.message.copied") : t("workspace.message.copy")}
        </button>
        {canEdit && isUser && !editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded-md px-1.5 py-0.5 hover:bg-[var(--color-surface-sunken)]"
          >
            {t("workspace.message.edit")}
          </button>
        )}
        {edited && (
          <>
            <span>·</span>
            <button
              type="button"
              onClick={() => setShowHistory((value) => !value)}
              className="rounded-md px-1.5 py-0.5 hover:bg-[var(--color-surface-sunken)]"
              aria-expanded={showHistory}
            >
              {t("workspace.message.edited", { revision: message.edited_revision })}
            </button>
          </>
        )}
      </div>

      {showHistory && message.edit_history_json.length > 0 && (
        <details className="w-fit max-w-[92%] rounded-[var(--radius-card)] border border-[var(--color-line)] px-3 py-2 text-sm">
          <summary className="cursor-pointer text-[var(--color-ink-muted)]">
            {t("workspace.message.history")}
          </summary>
          <ul className="mt-2 space-y-2">
            {message.edit_history_json.map((entry) => (
              <li key={entry.revision} className="text-[var(--color-ink-muted)]">
                <span className="font-mono text-xs">v{entry.revision}</span>
                <p className="whitespace-pre-wrap">{entry.content}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

function ReferenceCard({
  title,
  pointer,
  t,
}: {
  title: string;
  pointer: string;
  t: Translate;
}) {
  return (
    <div className="w-fit max-w-[92%] rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface-sunken)] px-4 py-3 text-sm">
      <p className="font-semibold">{title}</p>
      {pointer ? (
        <p className="mt-1 font-mono text-xs text-[var(--color-ink-muted)]" dir="ltr">
          {pointer}
        </p>
      ) : (
        <p className="mt-1 text-[var(--color-ink-muted)]">{t("workspace.common.unknownRecord")}</p>
      )}
    </div>
  );
}
