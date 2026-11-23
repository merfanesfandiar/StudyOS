"use client";

import { useCallback, useEffect, useState } from "react";
import { AgentUiView } from "@/components/agent/agent-ui";
import { VerificationPanel } from "@/components/assignment/verification-panel";
import { parseAgentUi } from "@/lib/agent-ui/validate";
import { api } from "@/lib/api";
import {
  isAgentRunActive,
  isAgentRunFinished,
  type AgentArtifactType,
  type AgentRunDetail,
} from "@/lib/agent-types";
import type { Assignment, AssignmentSummary } from "@/lib/types";
import type { Translate } from "@/lib/i18n/translate";

/**
 * The right-hand context panel: the real project intelligence for the
 * conversation's bound assignment.
 *
 * Everything shown is real: the assignment record is fetched here, and the run
 * (with its task/artifact lists) is the workspace's own state, kept fresh by
 * its refreshes and live polling. The verification panel runs over the same
 * assignment. When the conversation is not bound to an assignment the panel is
 * an honest empty state plus the control to bind one — never placeholder
 * content.
 */
/**
 * Download the artifact's exact content as a file. The content is the one the
 * API returned with the run detail — nothing is synthesised client-side.
 * Markdown artifacts keep their extension; everything else downloads as
 * plain text.
 */
function downloadArtifact(title: string, type: AgentArtifactType, content: string) {
  const extension = type === "MARKDOWN" ? "md" : "txt";
  const safe = title.replace(/[^\p{L}\p{N}_-]+/gu, "-").replace(/^-+|-+$/g, "") || "artifact";
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${safe}.${extension}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function ContextPanel({
  t,
  assignmentId,
  run,
  onRunChanged,
  onAssociate,
  canAssociate,
}: {
  t: Translate;
  assignmentId: string | null;
  /** The workspace's run state — the single source of truth, already kept
   * fresh by the workspace's own refreshes and live polling. The panel never
   * fetches its own copy: two fetches of one run drift apart, and the stale
   * one is the one a student acts on. */
  run: AgentRunDetail | null;
  /** Refresh the workspace's run after the panel acts on it (start, pause,
   * resume, cancel), so the prop this panel renders is the state that exists. */
  onRunChanged: () => Promise<void> | void;
  onAssociate: (assignmentId: string | null) => Promise<void>;
  canAssociate: boolean;
}) {
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [candidates, setCandidates] = useState<AssignmentSummary[]>([]);
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [associating, setAssociating] = useState(false);

  // Fetch only: state is written by the callers (effect continuation or the
  // action handlers), never synchronously from an effect body.
  const fetchAssignment = useCallback(async (id: string) => {
    return await api.assignment(id);
  }, []);

  useEffect(() => {
    // A mismatch between the loaded assignment and the bound one is guarded at
    // render time, so no cascading reset is needed here.
    if (!assignmentId) return;
    let active = true;
    fetchAssignment(assignmentId).then(
      (detail) => {
        if (!active) return;
        setAssignment(detail);
        setError("");
      },
      (caught: unknown) => {
        if (!active) return;
        setError(caught instanceof Error ? caught.message : String(caught));
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId, fetchAssignment]);

  // Candidate assignments for the association control, loaded on demand.
  const openAssociating = async () => {
    setAssociating(true);
    try {
      const page = await api.assignments({});
      setCandidates(page.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const act = async (action: "pause" | "resume" | "cancel" | "start") => {
    if (!assignmentId || !run || run.assignment_id !== assignmentId) return;
    setBusyAction(action);
    try {
      if (action === "pause") await api.pauseAgentRun(assignmentId, run.id);
      if (action === "resume") await api.resumeAgentRun(assignmentId, run.id);
      if (action === "cancel") await api.cancelAgentRun(assignmentId, run.id);
      if (action === "start") await api.startAgentRun(assignmentId, run.id);
      // The run is the workspace's state; the workspace refetches it and this
      // panel renders the refreshed prop.
      await onRunChanged();
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusyAction(null);
    }
  };

  if (!assignmentId) {
    return (
      <div className="flex h-full flex-col gap-3 p-4">
        <h2 className="text-sm font-semibold">{t("workspace.context.title")}</h2>
        <div className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-line)] p-4 text-sm text-[var(--color-ink-muted)]">
          <p>{t("workspace.context.noAssignment")}</p>
          {canAssociate && (
            <button
              type="button"
              onClick={() => void openAssociating()}
              className="btn-ghost mt-3 px-2.5 py-1 text-xs"
            >
              {t("workspace.context.associate")}
            </button>
          )}
          {associating && (
            <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto">
              {candidates.length === 0 && <li>{t("workspace.context.noCandidates")}</li>}
              {candidates.map((candidate) => (
                <li key={candidate.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setAssociating(false);
                      void onAssociate(candidate.id);
                    }}
                    className="w-full rounded-md px-2 py-1 text-start hover:bg-[var(--color-surface-sunken)]"
                  >
                    <span className="block truncate">{candidate.title}</span>
                  </button>
                </li>
              ))}
              <li>
                <button
                  type="button"
                  onClick={() => {
                    setAssociating(false);
                    void onAssociate(null);
                  }}
                  className="w-full rounded-md px-2 py-1 text-start text-[var(--color-ink-subtle)] hover:bg-[var(--color-surface-sunken)]"
                >
                  {t("workspace.context.cancelAssociate")}
                </button>
              </li>
            </ul>
          )}
        </div>
      </div>
    );
  }

  // Stale guard: state from a previously-bound assignment is not shown.
  const assignmentCurrent = assignment && assignment.id === assignmentId ? assignment : null;
  const runCurrent = run && run.assignment_id === assignmentId ? run : null;
  const active = runCurrent ? isAgentRunActive(runCurrent.status) : false;
  const finished = runCurrent ? isAgentRunFinished(runCurrent.status) : false;
  const progress = runCurrent?.progress ?? null;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <section>
        <div className="flex items-start justify-between gap-2">
          <h2 className="text-sm font-semibold">{t("workspace.context.title")}</h2>
          {canAssociate && (
            <button
              type="button"
              onClick={() => void onAssociate(null)}
              className="text-xs text-[var(--color-ink-subtle)] hover:underline"
            >
              {t("workspace.context.unbind")}
            </button>
          )}
        </div>
        {assignmentCurrent === null && (
          <p className="mt-2 text-sm text-[var(--color-ink-muted)]">{t("workspace.context.loading")}</p>
        )}
        {assignmentCurrent && (
          <dl className="mt-2 space-y-1 text-sm">
            <div>
              <dt className="inline font-medium">{t("workspace.context.assignmentLabel")}: </dt>
              <dd className="inline">{assignmentCurrent.title}</dd>
            </div>
              {assignmentCurrent.deadline && (
              <div>
                <dt className="inline font-medium">{t("workspace.context.deadline")}: </dt>
                <dd className="inline">{formatDate(assignmentCurrent.deadline)}</dd>
              </div>
            )}
            <div>
              <dt className="inline font-medium">{t("workspace.context.status")}: </dt>
              <dd className="inline">{assignmentCurrent.status}</dd>
            </div>
              {assignmentCurrent.description && (
              <div className="text-[var(--color-ink-muted)]">
                <dt className="sr-only">{t("workspace.context.description")}</dt>
                <dd className="line-clamp-3">{assignmentCurrent.description}</dd>
              </div>
            )}
          </dl>
        )}
        {error && (
          <p className="mt-2 text-sm text-[var(--color-critical)]" role="alert">
            {error}
          </p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold">{t("workspace.context.execution")}</h3>
        {runCurrent ? (
          <>
            <p className="mt-1 flex items-center gap-2 text-sm">
              <span
                className={`inline-block size-2 rounded-full ${
                  active ? "bg-[var(--color-info)]" : finished ? "bg-[var(--color-positive)]" : "bg-[var(--color-ink-subtle)]"
                }`}
                aria-hidden="true"
              />
              <span className="font-mono text-xs" dir="ltr">
                {runCurrent.status}
              </span>
            </p>
            {runCurrent.paused_reason && (
              <p className="mt-1 text-xs text-[var(--color-ink-muted)]">{runCurrent.paused_reason}</p>
            )}
            {progress && (
              <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
                {t("workspace.context.progress", {
                  completed: progress.completed + progress.skipped,
                  total: progress.total,
                })}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {runCurrent?.can_resume && (
                <button
                  type="button"
                  onClick={() => void act("resume")}
                  disabled={busyAction !== null}
                  className="btn-primary px-2.5 py-1 text-xs"
                >
                  {t("workspace.context.resume")}
                </button>
              )}
              {active && (
                <button
                  type="button"
                  onClick={() => void act("pause")}
                  disabled={busyAction !== null}
                  className="btn-ghost px-2.5 py-1 text-xs"
                >
                  {t("workspace.context.pause")}
                </button>
              )}
              {active && (
                <button
                  type="button"
                  onClick={() => void act("cancel")}
                  disabled={busyAction !== null}
                  className="btn-danger px-2.5 py-1 text-xs"
                >
                  {t("workspace.context.cancel")}
                </button>
              )}
            </div>

              {runCurrent.tasks.length > 0 && (
              <ul className="mt-3 space-y-1 text-sm">
                  {runCurrent.tasks.slice(0, 8).map((task) => (
                  <li key={task.id} className="flex items-center gap-2">
                    <span
                      className={`inline-block size-1.5 shrink-0 rounded-full ${
                        task.status === "COMPLETED" || task.status === "SKIPPED"
                          ? "bg-[var(--color-positive)]"
                          : task.status === "BLOCKED"
                            ? "bg-[var(--color-critical)]"
                            : task.status === "IN_PROGRESS"
                              ? "bg-[var(--color-info)]"
                              : "bg-[var(--color-ink-subtle)]"
                      }`}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate">{task.title}</span>
                    <span className="shrink-0 text-[10px] text-[var(--color-ink-subtle)]" dir="ltr">
                      {task.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{t("workspace.context.noRuns")}</p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold">{t("workspace.context.artifacts")}</h3>
        {runCurrent && runCurrent.artifacts.length > 0 ? (
          <ul className="mt-1 space-y-1 text-sm">
            {runCurrent.artifacts.slice(0, 6).map((artifact) => {
              const ui = parseAgentUi(artifact.metadata_json?.ui ?? null);
              return (
                <li key={artifact.id} className="rounded-md bg-[var(--color-surface-sunken)]">
                  <details>
                    <summary className="flex cursor-pointer items-center justify-between gap-2 px-2 py-1">
                      <span className="truncate font-medium">{artifact.title}</span>
                      <span className="shrink-0 text-[10px] text-[var(--color-ink-subtle)]" dir="ltr">
                        {artifact.artifact_type} · v{artifact.revision}
                      </span>
                    </summary>
                    {ui.ok && ui.envelope.blocks.length > 0 ? (
                      // Validated dynamic UI only: the artifact's own form is
                      // presentation, rendered through the registered renderer.
                      <div className="px-2 py-1">
                        <AgentUiView envelope={ui.envelope} errors={ui.errors} />
                      </div>
                    ) : (
                      // The artifact body is text, never HTML: model output is
                      // untrusted by construction (same rule as the agent panel).
                      <pre
                        dir="ltr"
                        className="max-h-64 overflow-x-auto whitespace-pre-wrap px-2 py-1 font-mono text-xs"
                      >
                        {artifact.content}
                      </pre>
                    )}
                    <div className="px-2 pb-1">
                      <button
                        type="button"
                        onClick={() => downloadArtifact(artifact.title, artifact.artifact_type, artifact.content)}
                        className="btn-ghost px-2 py-0.5 text-xs"
                      >
                        {t("workspace.context.download")}
                      </button>
                    </div>
                  </details>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{t("workspace.context.noArtifacts")}</p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold">{t("workspace.context.verification")}</h3>
        <div className="mt-1">
          <VerificationPanel assignmentId={assignmentId} />
        </div>
      </section>
    </div>
  );
}

function formatDate(value: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
  } catch {
    return value;
  }
}
