"use client";

import { useState } from "react";
import type { Conversation } from "@/lib/conversations-types";
import type { Translate } from "@/lib/i18n/translate";

/**
 * Conversation management for the workspace sidebar: search over the backend
 * list, create, rename, archive/restore, and delete with confirmation.
 *
 * Every action here hits the real conversations API — there is no local
 * conversation store to fall out of sync. Deleting is a soft delete enforced
 * server-side; the confirm dialog says so honestly.
 */
export function ConversationSidebar({
  t,
  conversations,
  activeId,
  loading,
  error,
  query,
  onQueryChange,
  onSelect,
  onNew,
  creating,
  onRename,
  onArchive,
  onRestore,
  onDelete,
  showArchived,
  onToggleArchived,
  archivedCount,
}: {
  t: Translate;
  conversations: Conversation[];
  activeId: string | null;
  loading: boolean;
  error: string;
  query: string;
  onQueryChange: (query: string) => void;
  onSelect: (id: string) => void;
  onNew: () => Promise<string | null>;
  creating: boolean;
  onRename: (id: string, title: string) => Promise<void>;
  onArchive: (id: string) => Promise<void>;
  onRestore: (id: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  showArchived: boolean;
  onToggleArchived: (value: boolean) => void;
  archivedCount: number;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState<Conversation | null>(null);

  const commitRename = async () => {
    const id = editingId;
    const title = draftTitle.trim();
    setEditingId(null);
    if (!id || !title) return;
    await onRename(id, title);
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t("workspace.sidebar.conversations")}</h2>
        <button
          type="button"
          onClick={() => void onNew()}
          disabled={creating}
          className="btn-primary px-2.5 py-1 text-xs"
        >
          {creating ? t("workspace.sidebar.creating") : t("workspace.sidebar.new")}
        </button>
      </div>

      <input
        type="search"
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder={t("workspace.sidebar.searchPlaceholder")}
        aria-label={t("workspace.sidebar.searchPlaceholder")}
        className="field w-full py-1.5 text-sm"
      />

      <label className="flex items-center gap-2 text-xs text-[var(--color-ink-muted)]">
        <input
          type="checkbox"
          checked={showArchived}
          onChange={(event) => onToggleArchived(event.target.checked)}
          className="size-3.5"
        />
        {t("workspace.sidebar.showArchived")}
        {archivedCount > 0 ? ` (${archivedCount})` : ""}
      </label>

      {error && (
        <p className="text-sm text-[var(--color-critical)]" role="alert">
          {error}
        </p>
      )}

      <nav aria-label={t("workspace.sidebar.conversations")} className="min-h-0 flex-1 overflow-y-auto">
        {loading && conversations.length === 0 && (
          <p className="px-1 py-2 text-sm text-[var(--color-ink-muted)]">
            {t("workspace.sidebar.loading")}
          </p>
        )}
        {!loading && conversations.length === 0 && (
          <p className="px-1 py-2 text-sm text-[var(--color-ink-muted)]">
            {showArchived
              ? t("workspace.sidebar.emptyArchived")
              : t("workspace.sidebar.empty")}
          </p>
        )}
        <ul className="space-y-1">
          {conversations.map((conversation) => {
            const active = conversation.id === activeId;
            const archived = conversation.status === "ARCHIVED";
            return (
              <li key={conversation.id}>
                {editingId === conversation.id ? (
                  <input
                    autoFocus
                    value={draftTitle}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    onBlur={() => void commitRename()}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void commitRename();
                      if (event.key === "Escape") setEditingId(null);
                    }}
                    aria-label={t("workspace.sidebar.renamePrompt")}
                    className="field w-full py-1 text-sm"
                  />
                ) : (
                  <div
                    className={`group flex items-center gap-1 rounded-[var(--radius-control)] px-2 py-1.5 text-sm ${
                      active
                        ? "bg-[var(--color-accent-soft)] font-medium"
                        : "hover:bg-[var(--color-surface-sunken)]"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelect(conversation.id)}
                      className="min-w-0 flex-1 text-start"
                      aria-current={active ? "page" : undefined}
                    >
                      <span className="block truncate">{conversation.title}</span>
                      {conversation.last_preview && (
                        <span className="block truncate text-xs font-normal text-[var(--color-ink-subtle)]">
                          {conversation.last_preview}
                        </span>
                      )}
                      {conversation.assignment_id && (
                        <span className="mt-0.5 inline-block rounded-full bg-[var(--color-surface-sunken)] px-1.5 text-[10px] text-[var(--color-ink-muted)]">
                          {t("workspace.sidebar.boundToAssignment")}
                        </span>
                      )}
                    </button>
                    <span className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                      <button
                        type="button"
                        onClick={() => {
                          setEditingId(conversation.id);
                          setDraftTitle(conversation.title);
                        }}
                        className="rounded px-1 text-xs hover:bg-[var(--color-surface)]"
                        aria-label={t("workspace.sidebar.rename")}
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void (archived ? onRestore(conversation.id) : onArchive(conversation.id))
                        }
                        className="rounded px-1 text-xs hover:bg-[var(--color-surface)]"
                        aria-label={archived ? t("workspace.sidebar.restore") : t("workspace.sidebar.archive")}
                      >
                        {archived ? "↩" : "▤"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingDelete(conversation)}
                        className="rounded px-1 text-xs hover:bg-[var(--color-surface)]"
                        aria-label={t("workspace.sidebar.delete")}
                      >
                        ×
                      </button>
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      {confirmingDelete && (
        <div
          role="dialog"
          aria-modal="false"
          aria-label={t("workspace.sidebar.deleteConfirmTitle")}
          className="rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)] p-3 text-sm shadow-[var(--shadow-soft)]"
        >
          <p className="font-medium">{t("workspace.sidebar.deleteConfirmTitle")}</p>
          <p className="mt-1 text-[var(--color-ink-muted)]">
            {t("workspace.sidebar.deleteConfirmBody", {
              title: confirmingDelete.title,
            })}
          </p>
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirmingDelete(null)}
              className="btn-ghost px-2.5 py-1 text-xs"
            >
              {t("workspace.sidebar.deleteCancel")}
            </button>
            <button
              type="button"
              onClick={() => {
                const id = confirmingDelete.id;
                setConfirmingDelete(null);
                void onDelete(id);
              }}
              className="btn-danger px-2.5 py-1 text-xs"
            >
              {t("workspace.sidebar.deleteConfirm")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
