"use client";

import { useState } from "react";
import { AgentUiView } from "@/components/agent/agent-ui";
import { parseAgentUi } from "@/lib/agent-ui/validate";
import type {
  AgentCheckpoint,
  AgentInteraction,
} from "@/lib/agent-types";
import { api } from "@/lib/api";
import type { Translate } from "@/lib/i18n/translate";

/**
 * Human-in-the-loop cards for the workspace thread: pending checkpoints
 * (questions/approvals the runtime is blocked on) and interactions
 * (risk-gated actions needing an explicit decision).
 *
 * Every decision is submitted to the backend endpoint that owns the state —
 * a button here is a client for the decision, never the authorisation itself.
 * Expired requests render as expired and refuse to submit.
 */

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  const expiry = new Date(expiresAt).getTime();
  return Number.isFinite(expiry) && expiry <= Date.now();
}

export function CheckpointCard({
  t,
  assignmentId,
  runId,
  checkpoint,
  onResolved,
}: {
  t: Translate;
  assignmentId: string;
  runId: string;
  checkpoint: AgentCheckpoint;
  onResolved: () => Promise<void> | void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const expired = isExpired(checkpoint.expires_at) || checkpoint.status !== "PENDING";
  const ui = parseAgentUi(checkpoint.ui);

  const submit = async (input: { approved?: boolean; selected_option?: string; response?: string }) => {
    setBusy(true);
    try {
      await api.resolveAgentCheckpoint(assignmentId, runId, checkpoint.id, input);
      await onResolved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="rounded-[var(--radius-card)] border border-[var(--color-line-strong)] bg-[var(--color-surface)] p-4"
      data-testid="checkpoint-card"
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-subtle)]">
        {t("workspace.hitl.checkpoint")}
      </p>
      <p className="mt-1 text-sm">{checkpoint.question}</p>
      {checkpoint.context && (
        <p className="mt-1 text-xs text-[var(--color-ink-muted)]">{checkpoint.context}</p>
      )}
      {ui.ok && ui.envelope.blocks.length > 0 && (
        // Read-only: the checkpoint's own form owns the answer, exactly as in
        // the assignment panel. A structured payload is presentation.
        <div className="mt-2">
          <AgentUiView envelope={ui.envelope} errors={ui.errors} />
        </div>
      )}
      {expired ? (
        <p className="mt-2 text-sm text-[var(--color-ink-muted)]">{t("workspace.hitl.expired")}</p>
      ) : (
        <>
          {checkpoint.options && checkpoint.options.length > 0 ? (
            <div className="mt-2 space-y-1">
              {checkpoint.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  disabled={busy}
                  onClick={() => void submit({ selected_option: option })}
                  className="btn-ghost block w-full px-3 py-1.5 text-start text-sm"
                >
                  {option}
                </button>
              ))}
            </div>
          ) : (
            <div className="mt-2 flex items-end gap-2">
              <input
                value={text}
                onChange={(event) => setText(event.target.value)}
                placeholder={t("workspace.hitl.answerPlaceholder")}
                aria-label={t("workspace.hitl.answerPlaceholder")}
                className="field flex-1 py-1.5 text-sm"
                disabled={busy}
              />
              <button
                type="button"
                disabled={busy || !text.trim()}
                onClick={() => void submit({ response: text.trim() })}
                className="btn-primary px-3 py-1.5 text-sm"
              >
                {t("workspace.hitl.answer")}
              </button>
            </div>
          )}
        </>
      )}
      {error && (
        <p className="mt-2 text-sm text-[var(--color-critical)]" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function InteractionCard({
  t,
  assignmentId,
  runId,
  interaction,
  onResolved,
}: {
  t: Translate;
  assignmentId: string;
  runId: string;
  interaction: AgentInteraction;
  onResolved: () => Promise<void> | void;
}) {
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const resolved = interaction.status !== "PENDING";
  const expired = isExpired(interaction.expires_at);
  const ui = parseAgentUi(interaction.ui);

  const act = async (action: "approve" | "reject") => {
    setBusy(true);
    try {
      const input = {
        action,
        payload: {},
        rationale: rationale.trim() || undefined,
      };
      if (action === "approve") {
        await api.approveAgentInteraction(assignmentId, runId, interaction.id, input);
      } else {
        await api.rejectAgentInteraction(assignmentId, runId, interaction.id, input);
      }
      await onResolved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="rounded-[var(--radius-card)] border border-[var(--color-line-strong)] bg-[var(--color-surface)] p-4"
      data-testid="interaction-card"
    >
      <p className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-subtle)]">
        <span>{t("workspace.hitl.approval")}</span>
        <span dir="ltr">{interaction.risk}</span>
      </p>
      <p className="mt-1 text-sm font-medium">{interaction.title}</p>
      <p className="mt-1 text-sm">{interaction.prompt}</p>
      {interaction.context && (
        <p className="mt-1 text-xs text-[var(--color-ink-muted)]">{interaction.context}</p>
      )}
      {interaction.operation_binding && Object.keys(interaction.operation_binding).length > 0 && (
        <details className="mt-2 text-xs text-[var(--color-ink-muted)]">
          <summary className="cursor-pointer">{t("workspace.hitl.details")}</summary>
          <pre
            dir="ltr"
            className="mt-1 overflow-x-auto rounded-md bg-[var(--color-surface-sunken)] p-2 font-mono"
          >
            {JSON.stringify(interaction.operation_binding, null, 2)}
          </pre>
        </details>
      )}
      {ui.ok && ui.envelope.blocks.length > 0 && (
        <div className="mt-2">
          <AgentUiView envelope={ui.envelope} errors={ui.errors} />
        </div>
      )}
      {resolved || expired ? (
        <p className="mt-2 text-sm text-[var(--color-ink-muted)]">
          {expired ? t("workspace.hitl.expired") : t("workspace.hitl.resolved")}
        </p>
      ) : (
        <>
          <input
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            placeholder={t("workspace.hitl.rationalePlaceholder")}
            aria-label={t("workspace.hitl.rationalePlaceholder")}
            className="field mt-2 w-full py-1.5 text-sm"
            disabled={busy}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void act("approve")}
              className="btn-primary px-3 py-1.5 text-sm"
            >
              {t("workspace.hitl.approve")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void act("reject")}
              className="btn-danger px-3 py-1.5 text-sm"
            >
              {t("workspace.hitl.reject")}
            </button>
          </div>
        </>
      )}
      {error && (
        <p className="mt-2 text-sm text-[var(--color-critical)]" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
