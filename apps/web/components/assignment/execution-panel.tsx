"use client";

import { useState } from "react";
import { Alert, EmptyState, LoadingState } from "@/components/ui";
import { usePreferences } from "@/components/preferences-provider";
import {
  EXECUTION_ENTRYPOINT,
  type ExecutionArtifact,
  type ExecutionAttempt,
  type ExecutionCreateInput,
  type ExecutionJob,
  type ExecutionJobDetail,
  type ExecutionJobStatus,
  type ExecutionResourceProfile,
  type ExecutionType,
} from "@/lib/execution-types";
import { useExecution } from "@/lib/use-execution";

/**
 * The sandbox workspace.
 *
 * The panel is built around the same assumption as the agent workspace: a
 * student did not ask for a sandbox and should be able to see its edges. So the
 * backend that serves a job, the runtimes that actually exist on this host, and
 * what the sandbox cannot reach are all rendered rather than implied.
 *
 * Two rules keep it honest.
 *
 * The form submits *source text and a runtime name*, never a command. There is
 * no field here for an image, a flag or a path, because the API has none either
 * — the boundary is drawn in the schema, and the UI does not pretend a control
 * that does not exist.
 *
 * A job that failed is not hidden. Its exit code, its failure class and the tail
 * of its stderr stay on screen, because "the compiler said this" is the whole
 * point of running it.
 */

export function ExecutionPanel({ assignmentId }: { assignmentId: string }) {
  const { t } = usePreferences();
  const {
    capabilities,
    jobs,
    detail,
    selectedId,
    loading,
    busy,
    error,
    actionError,
    isActive,
    select,
    submit,
    cancel,
  } = useExecution(assignmentId, t);

  const runtimes = capabilities?.execution_types ?? [];
  const profiles = capabilities ? Object.keys(capabilities.resource_profiles).sort() : [];

  const disabled =
    capabilities !== null && (!capabilities.enabled || capabilities.backend === "DISABLED");
  const unavailable = capabilities !== null && capabilities.enabled && !capabilities.available;

  if (loading && !detail && jobs.length === 0) {
    return <LoadingState label={t("common.loading")} />;
  }

  return (
    <section
      aria-labelledby="execution-heading"
      className="card space-y-5"
      id="execution"
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[var(--color-ink)]" id="execution-heading">
            {t("execution.title")}
          </h2>
          <p className="mt-1 max-w-2xl text-sm text-[var(--color-ink-muted)]">
            {t("execution.subtitle")}
          </p>
        </div>
        {capabilities ? <BackendBadge capabilities={capabilities} /> : null}
      </header>

      {error ? <Alert>{error}</Alert> : null}
      {actionError ? <Alert>{actionError}</Alert> : null}

      {disabled || unavailable ? (
        <EmptyState
          title={t("execution.disabled")}
          description={disabled ? t("execution.disabledHelp") : t("execution.unavailableHelp")}
        />
      ) : (
        // Keyed on the runtime list so the form's defaults follow the runtimes a
        // deployment actually offers. When the list changes the form remounts
        // with fresh initial state instead of an effect correcting it after the
        // fact -- which is both simpler and what React recommends.
        <ExecutionForm
          key={runtimes.join(",")}
          busy={busy}
          isActive={isActive}
          onCancel={cancel}
          onSubmit={submit}
          profiles={profiles}
          runtimes={runtimes}
        />
      )}

      <JobHistory jobs={jobs} selectedId={selectedId} onSelect={select} />

      {detail ? <JobDetail detail={detail} /> : null}

      <SandboxBoundary capabilities={capabilities} />
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

/**
 * The submission form.
 *
 * State lives here rather than in the panel so the whole form can be keyed on
 * the runtime list: when capabilities arrive, or change, the form remounts with
 * defaults for a runtime the deployment actually has, rather than needing an
 * effect to rewrite state mid-life.
 */
function ExecutionForm({
  runtimes,
  profiles,
  busy,
  isActive,
  onSubmit,
  onCancel,
}: {
  runtimes: ExecutionType[];
  profiles: string[];
  busy: "submit" | "cancel" | null;
  isActive: boolean;
  onSubmit: (input: ExecutionCreateInput) => Promise<void>;
  onCancel: (reason?: string) => Promise<void>;
}) {
  const { t } = usePreferences();
  const initial = runtimes[0] ?? "PYTHON";
  const [executionType, setExecutionType] = useState<ExecutionType>(initial);
  const [entrypoint, setEntrypoint] = useState(EXECUTION_ENTRYPOINT[initial] ?? "main.txt");
  const [code, setCode] = useState(starterFor(initial));
  const [stdin, setStdin] = useState("");
  const [profile, setProfile] = useState<ExecutionResourceProfile | "">("");
  const [mode, setMode] = useState<"sync" | "queue">("sync");

  function chooseRuntime(next: ExecutionType) {
    setExecutionType(next);
    setEntrypoint(EXECUTION_ENTRYPOINT[next] ?? "main.txt");
    // The starter loads only when the runtime changes, so a student editing code
    // is never reset underneath while they type.
    setCode(starterFor(next));
  }

  const file = entrypoint.trim() || "main.txt";

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit({
          execution_type: executionType,
          entrypoint: file,
          files: { [file]: code },
          stdin: stdin.trim() ? stdin : null,
          resource_profile: profile || null,
          mode,
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium text-[var(--color-ink)]">{t("execution.runtime")}</span>
          <select
            className="mt-1 w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 text-sm"
            onChange={(event) => chooseRuntime(event.target.value as ExecutionType)}
            value={executionType}
          >
            {(runtimes.length > 0 ? runtimes : [executionType]).map((runtime) => (
              <option key={runtime} value={runtime}>
                {t(`execution.type.${runtime.toLowerCase()}` as Parameters<typeof t>[0])}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          <span className="font-medium text-[var(--color-ink)]">{t("execution.entrypoint")}</span>
          <input
            className="mt-1 w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 font-mono text-sm"
            maxLength={255}
            onChange={(event) => setEntrypoint(event.target.value)}
            value={entrypoint}
          />
        </label>
      </div>

      <label className="block text-sm">
        <span className="font-medium text-[var(--color-ink)]">{t("execution.source")}</span>
        <textarea
          className="mt-1 w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 font-mono text-sm"
          onChange={(event) => setCode(event.target.value)}
          rows={12}
          spellCheck={false}
          value={code}
        />
      </label>

      <details className="rounded-xl border border-[var(--color-line)] px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium text-[var(--color-ink)]">
          {t("execution.options")}
        </summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="font-medium text-[var(--color-ink)]">{t("execution.stdin")}</span>
            <textarea
              className="mt-1 w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 font-mono text-sm"
              onChange={(event) => setStdin(event.target.value)}
              rows={3}
              value={stdin}
            />
          </label>
          <div className="space-y-3">
            <label className="block text-sm">
              <span className="font-medium text-[var(--color-ink)]">{t("execution.resources")}</span>
              <select
                className="mt-1 w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 text-sm"
                onChange={(event) => setProfile(event.target.value as ExecutionResourceProfile | "")}
                value={profile}
              >
                <option value="">{t("execution.defaultProfile")}</option>
                {profiles.map((name) => (
                  <option key={name} value={name}>
                    {t(`execution.profile.${name.toLowerCase()}` as Parameters<typeof t>[0])}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="text-sm">
              <legend className="font-medium text-[var(--color-ink)]">{t("execution.mode")}</legend>
              <div className="mt-1 flex flex-wrap gap-3">
                {(["sync", "queue"] as const).map((value) => (
                  <label className="flex items-center gap-2" key={value}>
                    <input
                      checked={mode === value}
                      name="execution-mode"
                      onChange={() => setMode(value)}
                      type="radio"
                      value={value}
                    />
                    <span className="text-[var(--color-ink)]">
                      {t(`execution.mode.${value}` as Parameters<typeof t>[0])}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        </div>
      </details>

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" disabled={busy !== null || !code.trim()} type="submit">
          {busy === "submit" ? t("execution.submitting") : t("execution.submit")}
        </button>
        {isActive ? (
          <button
            className="btn-secondary"
            disabled={busy !== null}
            onClick={() => void onCancel()}
            type="button"
          >
            {busy === "cancel" ? t("execution.cancelling") : t("execution.cancel")}
          </button>
        ) : null}
      </div>
    </form>
  );
}

function starterFor(executionType: ExecutionType): string {
  switch (executionType) {
    case "JAVA":
      return (
        "public class Main {\n" +
        "  public static void main(String[] args) {\n" +
        '    System.out.println("Hello from the sandbox");\n' +
        "  }\n" +
        "}\n"
      );
    case "CPP":
      return (
        "#include <iostream>\n\n" +
        "int main() {\n" +
        '  std::cout << "Hello from the sandbox" << std::endl;\n' +
        "  return 0;\n" +
        "}\n"
      );
    case "PYTHON":
    case "DATA_ANALYSIS":
    case "NUMERICAL_COMPUTATION":
    case "STATIC_ANALYSIS":
    case "OTHER":
      return 'print("Hello from the sandbox")\n';
    default:
      return "";
  }
}

function BackendBadge({
  capabilities,
}: {
  capabilities: NonNullable<ReturnType<typeof useExecution>["capabilities"]>;
}) {
  const { t } = usePreferences();
  const tone =
    capabilities.enabled && capabilities.available
      ? "text-[var(--color-positive)] bg-[var(--color-positive-soft)]"
      : "text-[var(--color-warning)] bg-[var(--color-warning-soft)]";
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-medium ${tone}`}>
      {t("execution.backend", { backend: capabilities.backend })}
    </span>
  );
}

function statusTone(status: ExecutionJobStatus): string {
  if (status === "SUCCEEDED") return "text-[var(--color-positive)] bg-[var(--color-positive-soft)]";
  if (status === "FAILED" || status === "TIMED_OUT" || status === "RESOURCE_LIMIT_EXCEEDED" || status === "REJECTED") {
    return "text-[var(--color-critical)] bg-[var(--color-critical-soft)]";
  }
  if (status === "CANCELLED") return "text-[var(--color-ink-muted)] bg-[var(--color-surface-muted)]";
  return "text-[var(--color-ink-muted)] bg-[var(--color-surface-muted)]";
}

function StatusBadge({ status }: { status: ExecutionJobStatus }) {
  const { t } = usePreferences();
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${statusTone(status)}`}>
      {t(`status.executionJob.${status.toLowerCase()}` as Parameters<typeof t>[0])}
    </span>
  );
}

function JobHistory({
  jobs,
  selectedId,
  onSelect,
}: {
  jobs: ExecutionJob[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { t, formatDate } = usePreferences();
  if (jobs.length === 0) {
    return <p className="text-sm text-[var(--color-ink-muted)]">{t("execution.noRuns")}</p>;
  }
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-[var(--color-ink)]">{t("execution.history")}</h3>
      <ul className="space-y-1">
        {jobs.map((job) => (
          <li key={job.id}>
            <button
              aria-pressed={selectedId === job.id}
              className={`flex w-full flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-start text-sm transition-colors ${
                selectedId === job.id
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                  : "border-[var(--color-line)] hover:border-[var(--color-line-strong)]"
              }`}
              onClick={() => onSelect(job.id)}
              type="button"
            >
              <span className="font-mono text-xs text-[var(--color-ink)]">
                {t(`execution.type.${job.execution_type.toLowerCase()}` as Parameters<typeof t>[0])}
              </span>
              <StatusBadge status={job.status} />
              {job.exit_code !== null ? (
                <span className="text-xs text-[var(--color-ink-muted)]">
                  {t("execution.exitCode", { code: job.exit_code })}
                </span>
              ) : null}
              <span className="ms-auto shrink-0 text-xs text-[var(--color-ink-subtle)]">
                {formatDate(job.created_at, "datetime")}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function JobDetail({ detail }: { detail: ExecutionJobDetail }) {
  const { t } = usePreferences();
  const { job, attempts, artifacts, events } = detail;
  return (
    <div className="space-y-4 rounded-xl border border-[var(--color-line)] p-4">
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={job.status} />
        {job.exit_code !== null ? (
          <span className="text-sm text-[var(--color-ink-muted)]">
            {t("execution.exitCode", { code: job.exit_code })}
          </span>
        ) : null}
        {job.duration_ms !== null ? (
          <span className="text-sm text-[var(--color-ink-muted)]">
            {t("execution.duration", { ms: job.duration_ms })}
          </span>
        ) : null}
        {job.failure_class ? (
          <span className="text-xs font-medium text-[var(--color-critical)]">
            {job.failure_class}
          </span>
        ) : null}
        {job.cleanup_status !== "CLEANED" && job.cleanup_status !== "SKIPPED" ? (
          <span className="text-xs text-[var(--color-caution)]">
            {t("execution.cleanup", { status: job.cleanup_status })}
          </span>
        ) : null}
      </div>

      {job.error_message ? <Alert>{job.error_message}</Alert> : null}

      {job.result_excerpt ? (
        <Output title={t("execution.output")} body={job.result_excerpt} />
      ) : null}

      {attempts.map((attempt) => (
        <Attempt key={attempt.id} attempt={attempt} />
      ))}

      {artifacts.length > 0 ? <Artifacts artifacts={artifacts} /> : null}

      {events.length > 0 ? (
        <div className="space-y-1">
          <h4 className="text-sm font-medium text-[var(--color-ink)]">{t("execution.timeline")}</h4>
          <ol className="space-y-1">
            {orderedEvents(events).map((event) => (
              <li className="flex gap-3 text-sm" key={event.id}>
                <span className="shrink-0 font-mono text-xs text-[var(--color-ink-subtle)]">
                  {event.sequence}
                </span>
                <span className="text-[var(--color-ink)]">{event.summary}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

function orderedEvents(events: ExecutionJobDetail["events"]): ExecutionJobDetail["events"] {
  return events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => a.event.sequence - b.event.sequence || a.index - b.index)
    .map((entry) => entry.event);
}

function Attempt({ attempt }: { attempt: ExecutionAttempt }) {
  const { t } = usePreferences();
  return (
    <div className="space-y-2 rounded-lg border border-[var(--color-line)] px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-[var(--color-ink)]">
          {t("execution.attempt", { attempt: attempt.attempt })}
        </span>
        <span className="text-xs text-[var(--color-ink-muted)]">
          {t(`status.executionAttempt.${attempt.status.toLowerCase()}` as Parameters<typeof t>[0])}
        </span>
        {attempt.exit_code !== null ? (
          <span className="text-xs text-[var(--color-ink-muted)]">
            {t("execution.exitCode", { code: attempt.exit_code })}
          </span>
        ) : null}
      </div>
      {attempt.stdout_excerpt ? (
        <Output title={t("execution.stdout")} body={attempt.stdout_excerpt} />
      ) : null}
      {attempt.stderr_excerpt ? (
        <Output title={t("execution.stderr")} body={attempt.stderr_excerpt} />
      ) : null}
      {attempt.failure_class ? (
        <p className="text-xs text-[var(--color-critical)]">{attempt.failure_class}</p>
      ) : null}
      {attempt.error_message ? (
        <p className="text-xs text-[var(--color-ink-muted)]">{attempt.error_message}</p>
      ) : null}
    </div>
  );
}

function Output({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <span className="text-xs font-medium text-[var(--color-ink-muted)]">{title}</span>
      {/* Rendered as text, never HTML: the output is untrusted by construction. */}
      <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-[var(--color-surface-sunken)] px-3 py-2 font-mono text-xs text-[var(--color-ink)]">
        {body}
      </pre>
    </div>
  );
}

function Artifacts({ artifacts }: { artifacts: ExecutionArtifact[] }) {
  const { t, formatNumber } = usePreferences();
  return (
    <div className="space-y-1">
      <h4 className="text-sm font-medium text-[var(--color-ink)]">{t("execution.artifacts")}</h4>
      <ul className="flex flex-wrap gap-2">
        {artifacts.map((artifact) => (
          <li
            className="rounded-full bg-[var(--color-surface-muted)] px-2.5 py-1 font-mono text-xs text-[var(--color-ink-muted)]"
            key={artifact.id}
          >
            {artifact.filename} · {formatNumber(artifact.size_bytes)}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * What the sandbox cannot reach, as the server publishes it.
 *
 * A constant on the server, rendered verbatim. It is not a settings panel
 * because these are not settings — there is no value to change.
 */
function SandboxBoundary({
  capabilities,
}: {
  capabilities: ReturnType<typeof useExecution>["capabilities"];
}) {
  const { t } = usePreferences();
  if (!capabilities) return null;
  return (
    <details className="rounded-xl border border-[var(--color-line)] bg-[var(--color-surface-muted)]">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[var(--color-ink)]">
        {t("execution.security")}
      </summary>
      <div className="space-y-2 border-t border-[var(--color-line)] px-4 py-3 text-sm">
        <p className="text-xs text-[var(--color-ink-muted)]">{t("execution.securityHelp")}</p>
        <ul className="flex flex-wrap gap-2">
          {(capabilities.absent_capabilities ?? []).map((capability) => (
            <li
              className="rounded-full bg-[var(--color-surface)] px-2.5 py-1 text-xs text-[var(--color-ink-muted)]"
              key={capability}
            >
              {capability}
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}
