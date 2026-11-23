"use client";

import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import type { Translate } from "@/lib/i18n/translate";

interface Attachment {
  id: string;
  filename: string;
  size: number;
  status: "uploading" | "uploaded" | "failed";
  reason?: string;
}

/**
 * The message composer: auto-resizing input, Enter to send (Shift+Enter for a
 * newline), attachments uploaded through the real documents API, and a stop
 * control wired to the live run's cancel.
 *
 * An attachment is only shown as "uploaded" after the backend confirmed it —
 * selecting a file means nothing until the server accepted it.
 */
export function Composer({
  t,
  disabled,
  sending,
  canStop,
  onStop,
  onSend,
  assignmentId,
  canAttach,
}: {
  t: Translate;
  disabled: boolean;
  sending: boolean;
  canStop: boolean;
  onStop: () => Promise<void> | void;
  onSend: (content: string) => Promise<boolean>;
  assignmentId: string | null;
  canAttach: boolean;
}) {
  const [value, setValue] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploadError, setUploadError] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  const submit = async () => {
    const content = value.trim();
    if (!content || sending) return;
    if (await onSend(content)) {
      setValue("");
      requestAnimationFrame(resize);
    }
  };

  const upload = async (file: File) => {
    if (!assignmentId) return;
    const pending: Attachment = {
      id: `pending-${Date.now()}-${file.name}`,
      filename: file.name,
      size: file.size,
      status: "uploading",
    };
    setAttachments((previous) => [...previous, pending]);
    try {
      const document = await api.uploadDocument(assignmentId, file);
      setAttachments((previous) =>
        previous.map((a) =>
          a.id === pending.id
            ? { ...a, id: document.id, status: "uploaded" as const }
            : a,
        ),
      );
    } catch (err) {
      const reason =
        err instanceof ApiError && err.code === "UNSUPPORTED_FILE_TYPE"
          ? t("workspace.composer.unsupportedType")
          : errorMessage(err, t, "workspace.composer.uploadFailed");
      setAttachments((previous) =>
        previous.map((a) =>
          a.id === pending.id ? { ...a, status: "failed" as const, reason } : a,
        ),
      );
    }
  };

  const onPick = async (files: FileList | null) => {
    setUploadError("");
    if (!files?.length) return;
    if (!assignmentId) {
      setUploadError(t("workspace.composer.attachNeedsAssignment"));
      return;
    }
    for (const file of Array.from(files)) {
      await upload(file);
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)] p-3">
      {attachments.length > 0 && (
        <ul className="mb-2 space-y-1">
          {attachments.map((attachment) => (
            <li
              key={attachment.id}
              className="flex items-center justify-between gap-2 rounded-md bg-[var(--color-surface-sunken)] px-2 py-1 text-sm"
            >
              <span className="min-w-0 truncate" title={attachment.filename}>
                {attachment.filename}
                <span className="ms-2 text-xs text-[var(--color-ink-subtle)]">
                  {formatSize(attachment.size)}
                </span>
              </span>
              <span className="flex items-center gap-2 text-xs">
                {attachment.status === "uploading" && (
                  <span className="text-[var(--color-ink-muted)]">
                    {t("workspace.composer.uploading")}
                  </span>
                )}
                {attachment.status === "uploaded" && (
                  <span className="text-[var(--color-positive)]">
                    {t("workspace.composer.uploaded")}
                  </span>
                )}
                {attachment.status === "failed" && (
                  <span className="text-[var(--color-critical)]" role="alert">
                    {attachment.reason ?? t("workspace.composer.uploadFailed")}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() =>
                    setAttachments((previous) => previous.filter((a) => a.id !== attachment.id))
                  }
                  className="rounded px-1 hover:bg-[var(--color-surface)]"
                  aria-label={t("workspace.composer.removeAttachment")}
                >
                  ×
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {uploadError && (
        <p className="mb-2 text-sm text-[var(--color-critical)]" role="alert">
          {uploadError}
        </p>
      )}

      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            resize();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          rows={1}
          disabled={disabled}
          placeholder={t("workspace.composer.placeholder")}
          aria-label={t("workspace.composer.placeholder")}
          className="field max-h-[200px] min-h-[44px] w-full resize-none"
        />
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            onChange={(event) => void onPick(event.target.files)}
            aria-hidden="true"
            tabIndex={-1}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={disabled || !canAttach}
            className="btn-ghost px-2 py-1.5 text-sm"
            title={canAttach ? undefined : t("workspace.composer.attachNeedsAssignment")}
          >
            {t("workspace.composer.attach")}
          </button>
        </div>
        <div className="flex items-center gap-2">
          {canStop && (
            <button
              type="button"
              onClick={() => void onStop()}
              className="btn-danger px-3 py-1.5 text-sm"
            >
              {t("workspace.composer.stop")}
            </button>
          )}
          <button
            type="button"
            onClick={() => void submit()}
            disabled={disabled || sending || !value.trim()}
            className="btn-primary px-4 py-1.5 text-sm"
          >
            {sending ? t("workspace.composer.sending") : t("workspace.composer.send")}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
