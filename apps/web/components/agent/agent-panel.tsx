"use client";

import { useMemo, useState } from "react";
import { Alert, EmptyState, LoadingState } from "@/components/ui";
import { usePreferences } from "@/components/preferences-provider";
import {
  isAgentRunFinished,
  type AgentArtifact,
  type AgentCapabilities,
  type AgentCheckpoint,
  type AgentRunDetail,
  type AgentRunMode,
  type AgentRunStatus,
  type AgentTask,
} from "@/lib/agent-types";
import { useAgent } from "@/lib/use-agent";

/**
 * The agent workspace.
 *
 * The panel is built around one assumption: a student who did not ask for an
 * agent, and may not entirely want one. That shapes four things here.
 *
 * What the agent cannot do is on screen. Not in documentation, not behind a
 * link — stated in this panel, next to the button that starts it. The backend
 * publishes that list as data so it cannot drift from the real boundary, and it
 * is rendered verbatim.
 *
 * Every stop says why. A run that is paused, waiting or blocked shows the
 * server's own `paused_reason`. The alternative — a spinner, or a status badge
 * that says "paused" — leaves the student guessing whether to wait, refresh, or
 * give up.
 *
 * Nothing in the run's history is edited or hidden. Failed attempts stay visible
 * with their error, drafts keep every revision, and the activity trail is the
 * server's events in order. A run that only shows its successes would be a
 * marketing page.
 *
 * The capability boundary is not decorative. There is no "run my code" button
 * because the runtime has no such tool, and the panel does not imply otherwise.
 */

type Tab = "tasks" | "drafts" | "activity" | "context";

export function AgentPanel({
  assignmentId,
  hasApprovedPlan,
}: {
  assignmentId: string;
  /**
   * Whether the plan is approved. Read from the plan panel rather than fetched
   * again, and used only to explain the empty state — the server refuses the
   * run either way, so this is never a gate in the UI's own logic.
   */
  hasApprovedPlan: boolean;
}) {
  const { t, count, formatNumber, formatDate } = usePreferences();
  const [tab, setTab] = useState<Tab>("tasks");
  const [mode, setMode] = useState<AgentRunMode>("SUPERVISED");
  const [note, setNote] = useState("");
  const [answer, setAnswer] = useState("");
  const [chosen, setChosen] = useState("");
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  const {
    run,
    loading,
    busy,
    error,
    actionError,
    recovery,
    capabilities,
    pendingCheckpoint,
    isActive,
    create,
    start,
    pause,
    resume,
    cancel,
    answer: sendAnswer,
    recover,
  } = useAgent(assignmentId, t);

  const status = run?.status ?? null;
  const pendingTask = useMemo(
    () => run?.tasks.find((task) => task.attempted && task.status !== "COMPLETED") ?? null,
    [run?.tasks],
  );

  if (loading && !run) return <LoadingState label={t("common.loading")} />;

  const tabs: { id: Tab; label: string }[] = [
    { id: "tasks", label: t("plan.tasks") },
    { id: "drafts", label: t("agent.artifacts") },
    { id: "activity", label: t("agent.activity") },
    { id: "context", label: t("agent.context") },
  ];

  return (
    <section aria-labelledby="agent-heading" className="card p-6" data-testid="agent-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="agent-heading" className="text-lg font-semibold text-[var(--color-ink)]">
            {t("agent.title")}
          </h2>
          <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{t("agent.subtitle")}</p>
        </div>
        <RunStatusBadge status={status} />
      </div>

      {error ? <Alert>{error}</Alert> : null}
      {actionError ? <Alert>{actionError}</Alert> : null}
      {recovery ? (
        <Alert tone="info">
          {recovery.runs_paused === 0
            ? t("agent.recoveredNone")
            : count("agent.recovered", recovery.runs_paused)}
        </Alert>
      ) : null}

      {run ? (
        <RunProgress
          run={run}
          count={count}
          formatNumber={formatNumber}
          workingOn={pendingTask?.title ?? null}
          isActive={isActive}
        />
      ) : null}

      {/* A run that needs a decision comes before the controls. When the agent
          is asking a question, "start" is the wrong word and any other control
          is secondary. */}
      {pendingCheckpoint ? (
        <CheckpointPrompt
          checkpoint={pendingCheckpoint}
          answer={answer}
          chosen={chosen}
          busy={busy === "resolve"}
          onAnswerChange={setAnswer}
          onChosenChange={setChosen}
          onSubmit={(retry) =>
            sendAnswer(pendingCheckpoint.id, {
              response: answer.trim() || undefined,
              selected_option: chosen || undefined,
              retry,
            })
          }
        />
      ) : null}

      {!run ? (
        hasApprovedPlan ? (
          <EmptyState
            title={t("agent.empty")}
            description={t("agent.emptyHelp")}
            action={
              <div className="space-y-4">
                <ModeChoice value={mode} onChange={setMode} />
                <button
                  className="btn-primary"
                  disabled={busy !== null}
                  onClick={() => create({ mode })}
                  type="button"
                >
                  {busy === "create" ? t("agent.creating") : t("agent.create")}
                </button>
              </div>
            }
          />
        ) : (
          <EmptyState title={t("agent.needsApproval")} description={t("agent.needsApprovalHelp")} />
        )
      ) : (
        <div className="space-y-4">
          <Controls
            run={run}
            busy={busy}
            isActive={isActive}
            isFinished={isAgentRunFinished(status!)}
            note={note}
            onNoteChange={setNote}
            onStart={() => start()}
            onPause={() => pause(note.trim() || undefined)}
            onResume={() => resume(note.trim() || undefined)}
            onCancel={() => cancel(note.trim() || undefined)}
          />
          <p className="text-xs text-[var(--color-ink-muted)]">
            {t("agent.iteration", {
              count: formatNumber(run.iteration_count),
              max: formatNumber(run.max_iterations),
            })}{" "}
            · {t("agent.costs", { spent: formatMoney(run.estimated_cost), max: formatMoney(run.max_cost) })}
            {run.model ? ` · ${run.model}` : ""}
          </p>
        </div>
      )}

      {run ? (
        <div className="space-y-4">
          <div className="flex gap-1 border-b border-[var(--color-line)]" role="tablist">
            {tabs.map((item) => (
              <button
                aria-controls={`agent-panel-${item.id}`}
                aria-selected={tab === item.id}
                className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  tab === item.id
                    ? "border-[var(--color-accent)] text-[var(--color-ink)]"
                    : "border-transparent text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
                }`}
                id={`agent-tab-${item.id}`}
                key={item.id}
                onClick={() => setTab(item.id)}
                role="tab"
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>

          {/*
            One panel per tab, wired with aria-labelledby rather than rendered
            as a bare div. A tab without a labelled panel is half an ARIA pattern:
            a screen reader announces "tab" and then nothing about what it opens.
          */}
          <div
            aria-labelledby={`agent-tab-${tab}`}
            className="space-y-4 pt-4"
            id={`agent-panel-${tab}`}
            role="tabpanel"
            tabIndex={0}
          >
          {tab === "tasks" ? (
            <TaskList
              tasks={run.tasks}
              selected={selectedTask}
              onSelect={setSelectedTask}
              detail={run.tasks.find((task) => task.id === selectedTask) ?? null}
            />
          ) : null}
          {tab === "drafts" ? <ArtifactList artifacts={run.artifacts} /> : null}
          {tab === "activity" ? (
            <ol className="space-y-2">
              {run.events.length === 0 ? (
                <li className="text-sm text-[var(--color-ink-muted)]">{t("agent.noActivity")}</li>
              ) : (
                orderedEvents(run).map((event) => (
                  <li className="flex gap-3 text-sm" key={event.id}>
                    <span className="shrink-0 font-mono text-xs text-[var(--color-ink-subtle)]">
                      {formatNumber(event.sequence)}
                    </span>
                    <span className="text-[var(--color-ink)]">{event.summary}</span>
                    <span className="ms-auto shrink-0 text-xs text-[var(--color-ink-subtle)]">
                      {formatDate(event.created_at, "datetime")}
                    </span>
                  </li>
                ))
              )}
            </ol>
          ) : null}
          {tab === "context" ? (
            <div className="space-y-2 text-sm">
              <p className="text-[var(--color-ink-muted)]">{t("agent.contextHelp")}</p>
              {run.context_provenance.length === 0 ? (
                <p className="text-[var(--color-ink-subtle)]">{t("agent.contextEmpty")}</p>
              ) : (
                run.context_provenance.map((item, index) => (
                  <div
                    className="rounded-lg border border-[var(--color-line)] px-3 py-2"
                    // Provenance entries have no stable id of their own; the
                    // position is what identifies them, and this list never
                    // reorders under the student.
                    key={`${item.kind ?? "entry"}-${index}`}
                  >
                    <span className="font-medium text-[var(--color-ink)]">
                      {String(item.label ?? item.kind ?? t("agent.context"))}
                    </span>{" "}
                    <span className="text-[var(--color-ink-muted)]">
                      {String(item.used ?? item.included ?? "")}
                    </span>
                  </div>
                ))
              )}
            </div>
          ) : null}
          </div>
        </div>
      ) : null}

      {/* The boundary, stated as data the server publishes. Rendered last so it
          is not the first thing that greets a student, but never hidden. */}
      <CapabilityBoundary capabilities={capabilities} />

      <div className="flex justify-end">
        <button
          className="text-xs font-medium text-[var(--color-ink-muted)] underline underline-offset-2 hover:text-[var(--color-ink)]"
          disabled={busy !== null}
          onClick={() => recover()}
          type="button"
        >
          {busy === "recover" ? t("agent.recovering") : t("agent.recover")}
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

function formatMoney(value: number): string {
  return `$${value.toFixed(4)}`;
}

/**
 * The activity trail, oldest first.
 *
 * Sorted by `sequence` rather than trusted from the array. A trail whose whole
 * meaning is the order things happened should not depend on which order a query
 * happened to return, and a tie on sequence keeps the server's order.
 */
function orderedEvents(run: AgentRunDetail): AgentRunDetail["events"] {
  return run.events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => a.event.sequence - b.event.sequence || a.index - b.index)
    .map((entry) => entry.event);
}

/**
 * The run's status, as the server words it.
 *
 * `paused_reason` is shown rather than summarised, because the reason is the
 * part that tells a student whether the run needs them.
 */
function RunStatusBadge({ status }: { status: AgentRunStatus | null }) {
  const { t } = usePreferences();
  if (!status) return null;
  const tone =
    status === "COMPLETED"
      ? "text-[var(--color-positive)] bg-[var(--color-positive-soft)]"
      : status === "FAILED"
        ? "text-[var(--color-critical)] bg-[var(--color-critical-soft)]"
        : status === "WAITING_FOR_USER" || status === "BLOCKED"
          ? "text-[var(--color-warning)] bg-[var(--color-warning-soft)]"
          : "text-[var(--color-ink-muted)] bg-[var(--color-surface-muted)]";
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-medium ${tone}`}>
      {t(`status.agentRun.${status.toLowerCase()}` as Parameters<typeof t>[0])}
    </span>
  );
}

function RunProgress({
  run,
  count,
  formatNumber,
  workingOn,
  isActive,
}: {
  run: NonNullable<ReturnType<typeof useAgent>["run"]>;
  count: ReturnType<typeof usePreferences>["count"];
  formatNumber: ReturnType<typeof usePreferences>["formatNumber"];
  /** The task the run is on, so a long wait has something to point at. */
  workingOn: string | null;
  /** False once the run stops; a finished run is not "working on" anything. */
  isActive: boolean;
}) {
  const { t } = usePreferences();
  const progress = run.progress;
  if (!progress) return null;
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span className="font-medium text-[var(--color-ink)]">{t("agent.progress")}</span>
        <span className="text-[var(--color-ink-muted)]">
          {t("agent.progressOf", {
            completed: formatNumber(progress.completed),
            total: formatNumber(progress.total),
          })}
        </span>
      </div>
      {/* `progress` is a real attribute, not a div with a width. Screen readers
          otherwise announce nothing here at all. */}
      <progress
        aria-label={t("agent.progress")}
        className="h-2 w-full"
        max={progress.total || 1}
        value={progress.completed}
      />
      {workingOn && isActive ? (
        <p className="text-sm text-[var(--color-ink)]">{t("agent.worksOn", { title: workingOn })}</p>
      ) : null}
      {progress.blocked > 0 ? (
        <p className="text-xs text-[var(--color-critical)]">
          {count("plan.taskCount", progress.blocked)} {t("status.task.blocked").toLowerCase()}
        </p>
      ) : null}
      {run.paused_reason ? (
        <p className="text-sm text-[var(--color-ink-muted)]">
          <span className="font-medium text-[var(--color-ink)]">
            {t("agent.stoppedReason")}:
          </span>{" "}
          {run.paused_reason}
        </p>
      ) : null}
      {run.error_message ? <Alert>{run.error_message}</Alert> : null}
    </div>
  );
}

function ModeChoice({ value, onChange }: { value: AgentRunMode; onChange: (m: AgentRunMode) => void }) {
  const { t } = usePreferences();
  return (
    <fieldset className="text-start">
      <legend className="text-sm font-medium text-[var(--color-ink)]">{t("agent.mode")}</legend>
      <div className="mt-2 flex flex-wrap gap-3">
        {(["SUPERVISED", "AUTONOMOUS"] as const).map((option) => (
          <label className="flex items-start gap-2 text-sm" key={option}>
            <input
              checked={value === option}
              className="mt-1"
              name="agent-mode"
              onChange={() => onChange(option)}
              type="radio"
              value={option}
            />
            <span>
              <span className="font-medium text-[var(--color-ink)]">
                {t(`agent.mode.${option.toLowerCase()}` as Parameters<typeof t>[0])}
              </span>
              <span className="block text-xs text-[var(--color-ink-muted)]">
                {t(`agent.mode.${option.toLowerCase()}Help` as Parameters<typeof t>[0])}
              </span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * The question the agent is asking.
 *
 * Rendered as a form with real labels and a real submit button: a student
 * answering with the keyboard should not have to reach for a mouse, and the
 * offered options are radio buttons so the answer is unambiguous.
 */
function CheckpointPrompt({
  checkpoint,
  answer,
  chosen,
  busy,
  onAnswerChange,
  onChosenChange,
  onSubmit,
}: {
  checkpoint: AgentCheckpoint;
  answer: string;
  chosen: string;
  busy: boolean;
  onAnswerChange: (value: string) => void;
  onChosenChange: (value: string) => void;
  onSubmit: (retry: boolean) => void;
}) {
  const { t } = usePreferences();
  const options = checkpoint.options ?? [];
  const needsText = options.length === 0 || chosen === "";

  return (
    <form
      className="space-y-4 rounded-2xl border border-[var(--color-accent)] bg-[var(--color-accent-soft)] p-5"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(false);
      }}
    >
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">
          {t("agent.waitingTitle")}
        </h3>
        <p className="mt-1 text-xs text-[var(--color-ink-muted)]">{t("agent.waitingHelp")}</p>
      </div>

      <p className="text-sm text-[var(--color-ink)]">
        <span className="font-medium">{t("agent.question")}: </span>
        {checkpoint.question}
      </p>
      {checkpoint.context ? (
        <p className="rounded-lg bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-ink-muted)]">
          {checkpoint.context}
        </p>
      ) : null}

      {options.length > 0 ? (
        <fieldset>
          <legend className="text-sm font-medium text-[var(--color-ink)]">
            {t("agent.chooseOption")}
          </legend>
          <div className="mt-2 space-y-1">
            {options.map((option) => (
              <label className="flex items-center gap-2 text-sm" key={option}>
                <input
                  checked={chosen === option}
                  name="agent-checkpoint-option"
                  onChange={() => onChosenChange(option)}
                  type="radio"
                  value={option}
                />
                <span className="text-[var(--color-ink)]">{option}</span>
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      {needsText ? (
        <label className="block text-sm">
          <span className="font-medium text-[var(--color-ink)]">{t("agent.answerPlaceholder")}</span>
          <textarea
            className="mt-1 w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 text-sm"
            onChange={(event) => onAnswerChange(event.target.value)}
            rows={3}
            value={answer}
          />
        </label>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={busy} type="submit">
          {busy ? t("agent.sendingAnswer") : t("agent.answer")}
        </button>
        <button
          className="btn-secondary"
          disabled={busy}
          onClick={() => onSubmit(true)}
          type="button"
        >
          {t("agent.retryRejected")}
        </button>
        <button
          className="btn-ghost"
          disabled={busy}
          onClick={() => onSubmit(false)}
          type="button"
        >
          {t("agent.stopHere")}
        </button>
      </div>
    </form>
  );
}

function Controls({
  run,
  busy,
  isActive,
  isFinished,
  note,
  onNoteChange,
  onStart,
  onPause,
  onResume,
  onCancel,
}: {
  run: NonNullable<ReturnType<typeof useAgent>["run"]>;
  busy: string | null;
  isActive: boolean;
  isFinished: boolean;
  note: string;
  onNoteChange: (value: string) => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}) {
  const { t } = usePreferences();

  return (
    <div className="flex flex-wrap items-center gap-2">
      {run.status === "CREATED" ? (
        <button
          className="btn-primary"
          disabled={busy !== null || isActive}
          onClick={onStart}
          type="button"
        >
          {busy === "start" ? t("agent.starting") : t("agent.start")}
        </button>
      ) : null}

      {run.can_resume || run.status === "PAUSED" || run.status === "BLOCKED" ? (
        <button className="btn-primary" disabled={busy !== null} onClick={onResume} type="button">
          {busy === "resume" ? t("agent.resuming") : t("agent.resume")}
        </button>
      ) : null}

      {!isFinished ? (
        <>
          {/* Available *because* the run is going. Disabling this while active
              would remove the only way to stop work a student did not want. */}
          <button className="btn-secondary" disabled={busy !== null} onClick={onPause} type="button">
            {busy === "pause" ? t("agent.pausing") : t("agent.pause")}
          </button>
          <label className="flex flex-1 items-center gap-2 text-sm">
            <span className="sr-only">{t("agent.resumeNotePlaceholder")}</span>
            <input
              className="w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 text-sm"
              onChange={(event) => onNoteChange(event.target.value)}
              placeholder={t("agent.resumeNotePlaceholder")}
              value={note}
            />
          </label>
          <button className="btn-ghost" disabled={busy !== null} onClick={onCancel} type="button">
            {busy === "cancel" ? t("agent.cancelling") : t("agent.cancel")}
          </button>
        </>
      ) : null}
    </div>
  );
}

function TaskList({
  tasks,
  selected,
  onSelect,
  detail,
}: {
  tasks: AgentTask[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  detail: AgentTask | null;
}) {
  const { t, count } = usePreferences();
  if (tasks.length === 0) return <p className="text-sm text-[var(--color-ink-muted)]">{t("plan.noTasks")}</p>;

  return (
    <div className="space-y-2">
      {tasks.map((task) => (
        <button
          aria-expanded={selected === task.id}
          className={`w-full rounded-xl border px-4 py-3 text-start transition-colors ${
            selected === task.id
              ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
              : "border-[var(--color-line)] hover:border-[var(--color-line-strong)]"
          }`}
          key={task.id}
          onClick={() => onSelect(selected === task.id ? null : task.id)}
          type="button"
        >
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-[var(--color-ink-subtle)]">{task.key}</span>
            <span className="font-medium text-[var(--color-ink)]">{task.title}</span>
            <span className="ms-auto text-xs text-[var(--color-ink-muted)]">
              {t(`status.task.${task.status.toLowerCase()}` as Parameters<typeof t>[0])}
            </span>
          </span>
          {task.attempted ? (
            <span className="mt-1 block text-xs text-[var(--color-ink-subtle)]">
              {count("agent.attemptCount", task.attempts)}
            </span>
          ) : null}
        </button>
      ))}

      {detail ? (
        <div className="space-y-2 rounded-xl border border-[var(--color-line)] p-4 text-sm">
          <h3 className="font-medium text-[var(--color-ink)]">{detail.title}</h3>
          {detail.last_summary ? (
            <p className="text-[var(--color-ink-muted)]">{detail.last_summary}</p>
          ) : null}
          {detail.last_status ? (
            <p className="text-xs text-[var(--color-ink-subtle)]">
              {t(`status.agentExecution.${detail.last_status.toLowerCase()}` as Parameters<typeof t>[0])}
            </p>
          ) : null}
          {/* A task that needs a human is not quietly counted as done. */}
          {!detail.can_auto_complete ? (
            <Alert tone="info">{t("agent.waitingHelp")}</Alert>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Drafts, newest revision first.
 *
 * Revisions are shown as separate entries rather than collapsed, because the
 * point of keeping them is that a student can see how the work changed across
 * attempts — including the ones that were rejected.
 */
function ArtifactList({ artifacts }: { artifacts: AgentArtifact[] }) {
  const { t } = usePreferences();
  if (artifacts.length === 0) {
    return <p className="text-sm text-[var(--color-ink-muted)]">{t("agent.noArtifacts")}</p>;
  }
  return (
    <div className="space-y-3">
      {artifacts.map((artifact) => (
        <details className="rounded-xl border border-[var(--color-line)]" key={artifact.id}>
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[var(--color-ink)]">
            {artifact.title}{" "}
            <span className="ms-2 text-xs font-normal text-[var(--color-ink-muted)]">
              {artifact.task_id
                ? t("agent.revision", { revision: artifact.revision })
                : t(`status.agentArtifact.${artifact.status.toLowerCase()}` as Parameters<typeof t>[0])}
            </span>
          </summary>
          {/* The draft is rendered as text, never as HTML. Model output is
              untrusted by construction and this is where that would matter. */}
          <pre className="overflow-x-auto whitespace-pre-wrap border-t border-[var(--color-line)] px-4 py-3 text-sm text-[var(--color-ink)]">
            {artifact.content}
          </pre>
        </details>
      ))}
    </div>
  );
}

/**
 * What this runtime cannot do.
 *
 * A constant on the server, rendered here. It is not a settings panel because
 * these are not settings — there is no value to change and nothing behind them.
 *
 * The list is passed in rather than fetched here, so opening this disclosure
 * costs nothing: the workspace already read it while loading, because the
 * absence of a boundary notice is itself information.
 */
function CapabilityBoundary({ capabilities }: { capabilities: AgentCapabilities | null }) {
  const { t } = usePreferences();
  if (!capabilities) return null;
  return (
    <details className="rounded-xl border border-[var(--color-line)] bg-[var(--color-surface-muted)]">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[var(--color-ink)]">
        {t("agent.security")}
      </summary>
      <div className="space-y-2 border-t border-[var(--color-line)] px-4 py-3 text-sm">
        <p className="text-xs text-[var(--color-ink-muted)]">{t("agent.securityHelp")}</p>
        <ul className="flex flex-wrap gap-2">
          {/* Defensive even though the hook validates: a disclosure section is
              never worth an exception that unmounts the workspace. */}
          {(capabilities.absent_capabilities ?? []).map((capability) => (
            <li
              className="rounded-full bg-[var(--color-surface)] px-2.5 py-1 text-xs text-[var(--color-ink-muted)]"
              key={capability}
            >
              {capability}
            </li>
          ))}
        </ul>
        <p className="text-xs text-[var(--color-ink-subtle)]">
          {(capabilities.tools ?? []).map((tool) => tool.name).join(" · ")}
        </p>
      </div>
    </details>
  );
}
