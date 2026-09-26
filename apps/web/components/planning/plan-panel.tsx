"use client";

import { useMemo, useState } from "react";
import { usePlan } from "@/lib/use-plan";
import type { PlanMilestone, PlanTask, RegenerateScope, WorkPlan } from "@/lib/planning-types";
import { usePreferences } from "@/components/preferences-provider";
import type { MessageKey } from "@/lib/i18n/messages";
import type { PluralBase } from "@/lib/i18n/translate";
import {
  ComplexityBadge,
  EffortBadge,
  PlanStatusBadge,
  PriorityBadge,
  TaskStatusBadge,
  TaskTypeBadge,
  TierBadge,
  TriggerBadge,
} from "./status-badges";

/**
 * The study plan.
 *
 * Three decisions shape this component, and each one exists because the
 * alternative quietly misleads.
 *
 * Schedule risk is shown as a number, not a verdict. The backend computes
 * "18 to 24 estimated hours against 8 hours remaining" and refuses to claim the
 * work will be finished on time. Rendering that as a red "Will not finish" badge
 * would replace a real judgement with a false certainty, so the panel shows the
 * arithmetic and lets the student decide.
 *
 * Every generation is stated. When the deterministic engine answered because
 * the model did not, the panel says so and says why. A fallback presented
 * silently as a model result is the one failure mode the backend goes to real
 * trouble to avoid, and undoing it in the interface would waste that work.
 *
 * A stale plan cannot be approved. The button is disabled and the reason is
 * stated, rather than letting the click fail server-side. The server refuses
 * regardless -- this is about not offering an action that cannot succeed.
 */

type Tab = "tasks" | "milestones" | "risks" | "coverage" | "history";

type TFn = (key: MessageKey, vars?: Record<string, string | number>) => string;
type CountFn = (base: PluralBase, value: number) => string;

export function PlanPanel({ assignmentId }: { assignmentId: string }) {
  const { t, count, formatNumber, formatDate } = usePreferences();
  const {
    plan,
    runs,
    loading,
    busy,
    error,
    actionError,
    isApproved,
    isStale,
    canApprove,
    lastRun,
    generate,
    regenerate,
    approve,
  } = usePlan(assignmentId);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("tasks");
  const [scope, setScope] = useState<RegenerateScope>("TASKS");

  const selected = useMemo(
    () => plan?.tasks.find((task) => task.key === selectedKey) ?? null,
    [plan, selectedKey],
  );

  /** Order by milestone, not by flat position, so the list answers "what now". */
  const tasksByMilestone = useMemo(() => groupByMilestone(plan), [plan]);

  const notice = actionError || error;

  if (loading) {
    return (
      <section className="card p-6" aria-busy="true">
        <p className="muted text-sm">{t("common.loading")}</p>
      </section>
    );
  }

  if (!plan) {
    return (
      <section className="card grid gap-4 p-6">
        <div>
          <h2 className="section-title">{t("plan.title")}</h2>
          <p className="muted mt-1 text-sm">{t("plan.empty")}</p>
        </div>
        {notice && <p className="text-sm text-[var(--color-critical)]" role="alert">{notice}</p>}
        <div>
          <button
            className="btn-primary"
            disabled={busy !== null}
            onClick={() => void generate()}
            type="button"
          >
            {busy === "generate" ? t("plan.generating") : t("plan.generate")}
          </button>
        </div>
      </section>
    );
  }

  const blockedCount = plan.tasks.filter((task) => task.blocked_by.length > 0).length;
  const reasons = fallbackReasons(plan);

  return (
    <section className="grid gap-4">
      <header className="card grid gap-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="section-title">{plan.title}</h2>
              <PlanStatusBadge status={plan.status} />
              <TriggerBadge trigger={plan.trigger} />
              {isStale && (
                <span className="badge bg-[var(--color-critical-soft)] text-[var(--color-critical)]">
                  {t("plan.stale")}
                </span>
              )}
            </div>
            <p className="muted text-sm">
              {t("plan.version", { version: formatNumber(plan.version) })}
              {" · "}
              {formatDate(plan.created_at)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <EffortBadge effort={plan.estimated_effort} />
            {plan.schedule_risk && (
              <ComplexityBadge complexity={plan.schedule_risk.level} />
            )}
          </div>
        </div>

        <p className="text-sm text-[var(--color-ink-muted)]">{plan.summary}</p>

        <PlanStats
          plan={plan}
          blockedCount={blockedCount}
          formatNumber={formatNumber}
          count={count}
          t={t}
        />

        {isStale && (
          <p
            className="rounded-[var(--radius-control)] bg-[var(--color-caution-soft)] px-3 py-2 text-sm text-[var(--color-caution)]"
            role="status"
          >
            {t("plan.staleNotice")}
          </p>
        )}

        {/*
          The fallback notice. `used_fallback` and the rejection reasons are
          rendered verbatim from the plan payload; this is the one place a
          student learns the model did not answer.
        */}
        {reasons.length > 0 && (
          <div
            className="rounded-[var(--radius-control)] bg-[var(--color-info-soft)] px-3 py-2 text-sm text-[var(--color-info)]"
            role="status"
          >
            <p className="font-semibold">{t("plan.fallbackNotice")}</p>
            <ul className="mt-1 list-disc ps-5">
              {reasons.map((reason) => (
                <li key={reason}>{t("plan.fallbackReason", { reason })}</li>
              ))}
            </ul>
          </div>
        )}

        {plan.validation_warnings.length > 0 && (
          <details className="rounded-[var(--radius-control)] border border-[var(--color-line)] px-3 py-2 text-sm">
            <summary className="cursor-pointer font-semibold">
              {count("common.count", plan.validation_warnings.length)}
            </summary>
            <ul className="mt-2 grid gap-1 list-disc ps-5 text-[var(--color-ink-muted)]">
              {plan.validation_warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </details>
        )}

        {notice && <p className="text-sm text-[var(--color-critical)]" role="alert">{notice}</p>}

        <div className="flex flex-wrap items-end gap-3">
          <button
            className="btn-primary"
            disabled={!canApprove}
            onClick={() => void approve()}
            title={isStale ? t("plan.staleNotice") : undefined}
            type="button"
          >
            {busy === "approve" ? t("common.loading") : t("plan.approve")}
          </button>

          <label className="field !w-auto">
            <span className="text-xs">{t("plan.scope.label")}</span>
            <select
              aria-describedby="plan-scope-help"
              className="!w-auto !py-1.5 text-sm"
              disabled={busy !== null}
              onChange={(event) => setScope(event.target.value as RegenerateScope)}
              value={scope}
            >
              <option value="TASKS">{t("plan.scope.tasks")}</option>
              <option value="MILESTONES">{t("plan.scope.milestones")}</option>
              <option value="NONE">{t("plan.scope.none")}</option>
            </select>
          </label>
          <button
            className="btn-secondary"
            disabled={busy !== null}
            onClick={() => void regenerate(scope)}
            type="button"
          >
            {busy === "regenerate" ? t("common.loading") : t("plan.regenerate")}
          </button>
          <p className="muted text-xs" id="plan-scope-help">
            {scope === "MILESTONES" ? t("plan.scope.milestonesHelp") : null}
            {scope === "TASKS" ? t("plan.scope.tasksHelp") : null}
            {scope === "NONE" ? t("plan.scope.noneHelp") : null}
          </p>
        </div>

        {isApproved && <p className="muted text-xs">{t("plan.error.approved")}</p>}
      </header>

      <nav aria-label={t("plan.title")} className="flex flex-wrap gap-1 border-b border-[var(--color-line)]">
        {(
          [
            ["tasks", t("plan.tasks")],
            ["milestones", t("plan.milestones")],
            ["risks", t("plan.risks")],
            ["coverage", t("plan.traceability")],
            ["history", t("plan.versionHistory")],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            aria-current={tab === key ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-semibold transition ${
              tab === key
                ? "border-[var(--color-accent)] text-[var(--color-accent)]"
                : "border-transparent text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
            }`}
            key={key}
            onClick={() => setTab(key)}
            type="button"
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "tasks" && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="grid gap-3">
            {plan.tasks.length === 0 && <p className="muted text-sm">{t("plan.noTasks")}</p>}
            {tasksByMilestone.map((group, index) => (
              <MilestoneGroup
                group={group}
                key={group.milestone?.key ?? `unassigned-${index}`}
                onSelect={setSelectedKey}
                selectedKey={selectedKey}
              />
            ))}
          </div>
          <TaskDetail task={selected} />
        </div>
      )}

      {tab === "milestones" && (
        <div className="grid gap-3">
          {plan.milestones.map((milestone) => (
            <MilestoneProgress key={milestone.key} milestone={milestone} />
          ))}
          {plan.verification_points.length > 0 && (
            <div className="card grid gap-2 p-4">
              <h3 className="font-semibold">{t("plan.schedule")}</h3>
              {plan.verification_points.map((point) => (
                <div key={point.key} className="text-sm">
                  <p className="font-medium">{point.title}</p>
                  <p className="muted">{point.description}</p>
                  <p className="muted text-xs">{point.method}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "risks" && (
        <div className="grid gap-3">
          {/*
            The schedule risk leads, and it is arithmetic rather than a verdict.
            The estimate is explicitly the planner's, so it is labelled as an
            estimate everywhere it appears.
          */}
          {plan.schedule_risk && (
            <div
              className={`card p-4 ${
                plan.schedule_risk.is_overcommitted ? "border-[var(--color-critical)]" : ""
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">{t("plan.estimate")}</h3>
                <ComplexityBadge complexity={plan.schedule_risk.level} />
              </div>
              <p className="mt-1 text-sm">{plan.schedule_risk.summary}</p>
              {plan.schedule_risk.factors.length > 0 && (
                <ul className="muted mt-2 grid gap-1 text-xs">
                  {plan.schedule_risk.factors.map((factor) => (
                    <li key={factor}>{factor}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {plan.risks.map((risk) => (
            <div key={risk.key} className="card grid gap-1 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold">{risk.description}</h3>
                <span className="badge bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)]">
                  {risk.severity}
                </span>
              </div>
              {risk.mitigation && <p className="muted text-sm">{risk.mitigation}</p>}
            </div>
          ))}
        </div>
      )}

      {tab === "coverage" && (
        <div className="card grid gap-3 p-4">
          <p className="muted text-sm">{t("plan.covers")}</p>
          {plan.tasks.map((task) => (
            <div className="grid gap-1 border-t border-[var(--color-line)] pt-2" key={task.key}>
              <p className="text-sm font-semibold">
                <span className="muted">{task.key}</span> {task.title}
              </p>
              <div className="flex flex-wrap gap-1">
                {task.related_requirements.map((reference) => (
                  <span
                    className="badge bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                    key={`r-${reference}`}
                  >
                    {reference}
                  </span>
                ))}
                {task.related_deliverables.map((reference) => (
                  <span
                    className="badge bg-[var(--color-info-soft)] text-[var(--color-info)]"
                    key={`d-${reference}`}
                  >
                    {reference}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "history" && (
        <div className="grid gap-2">
          {runs.length === 0 && <p className="muted text-sm">{t("common.none")}</p>}
          {runs.map((run) => (
            <div className="card flex flex-wrap items-center gap-2 p-3 text-sm" key={run.id}>
              <TierBadge tier={run.model_tier} />
              <span className="font-medium">{run.model}</span>
              <span
                className={`badge ${
                  run.status === "SUCCEEDED"
                    ? "bg-[var(--color-positive-soft)] text-[var(--color-positive)]"
                    : run.status === "FAILED"
                      ? "bg-[var(--color-critical-soft)] text-[var(--color-critical)]"
                      : "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)]"
                }`}
              >
                {t(`status.run.${run.status.toLowerCase()}` as MessageKey)}
              </span>
              <span className="muted">{formatDate(run.started_at)}</span>
              {/*
                A failed run's error is shown. A generation that failed and left
                no visible reason is indistinguishable from one that never ran.
              */}
              {run.error_code && (
                <span className="text-[var(--color-critical)]">
                  {run.error_code}
                  {run.error_message ? `: ${run.error_message}` : null}
                </span>
              )}
              {run.fell_back_from_tier && (
                <span className="muted">
                  {t("plan.fallbackNotice")}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {lastRun?.routing_reason && tab === "history" && (
        <p className="muted text-xs">{lastRun.routing_reason}</p>
      )}
    </section>
  );
}

// -- pieces ----------------------------------------------------------------

function PlanStats({
  plan,
  blockedCount,
  formatNumber,
  count,
  t,
}: {
  plan: WorkPlan;
  blockedCount: number;
  formatNumber: (value: number) => string;
  count: CountFn;
  t: TFn;
}) {
  const total = plan.min_minutes ?? 0;
  const upper = plan.max_minutes ?? 0;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label={t("plan.tasks")} value={count("plan.taskCount", plan.tasks.length)} />
      <Stat label={t("plan.milestones")} value={count("plan.milestoneCount", plan.milestones.length)} />
      <Stat
        label={t("plan.totalHours")}
        value={`${formatNumber(Math.round(total / 60))}–${formatNumber(Math.round(upper / 60))}`}
      />
      <Stat
        label={t("plan.status")}
        value={blockedCount > 0 ? count("common.count", blockedCount) : t("common.none")}
      />
    </dl>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius-control)] bg-[var(--color-surface-sunken)] px-3 py-2">
      <dt className="muted text-xs">{label}</dt>
      <dd className="text-sm font-semibold">{value}</dd>
    </div>
  );
}

function MilestoneGroup({
  group,
  selectedKey,
  onSelect,
}: {
  group: { milestone: PlanMilestone | null; tasks: PlanTask[] };
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const { t } = usePreferences();
  return (
    <div className="card grid gap-2 p-4">
      {group.milestone && (
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold">{group.milestone.title}</h3>
          <TaskStatusBadge status={group.milestone.status} />
        </div>
      )}
      <ul className="grid gap-1">
        {group.tasks.map((task) => (
          <li key={task.key}>
            <button
              aria-pressed={selectedKey === task.key}
              className={`grid w-full gap-1 rounded-[var(--radius-control)] px-3 py-2 text-start transition ${
                selectedKey === task.key
                  ? "bg-[var(--color-accent-soft)]"
                  : "hover:bg-[var(--color-surface-sunken)]"
              }`}
              onClick={() => onSelect(task.key)}
              type="button"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="muted text-xs">{task.key}</span>
                <span className="text-sm font-medium">{task.title}</span>
                <TaskStatusBadge status={task.status} />
                {task.blocked_by.length > 0 && (
                  <span className="badge bg-[var(--color-critical-soft)] text-[var(--color-critical)]">
                    {t("plan.dependencies")}
                  </span>
                )}
              </span>
              <span className="flex flex-wrap items-center gap-1">
                <TaskTypeBadge type={task.type} />
                <PriorityBadge priority={task.priority} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TaskDetail({ task }: { task: PlanTask | null }) {
  const { t } = usePreferences();
  if (!task) {
    return (
      <aside className="card p-4">
        <p className="muted text-sm">{t("plan.selectTask")}</p>
      </aside>
    );
  }
  return (
    <aside className="card grid gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{task.title}</h3>
        <TaskStatusBadge status={task.status} />
      </div>
      <p className="muted text-xs">{task.key}</p>
      <p className="text-sm">{task.description}</p>

      {task.depends_on.length > 0 ? (
        <p className="text-sm">
          <span className="muted">{t("plan.dependencies")}: </span>
          {task.depends_on.join(", ")}
        </p>
      ) : (
        <p className="muted text-sm">{t("plan.noDependencies")}</p>
      )}

      {task.acceptance_criteria.length > 0 && (
        <div className="grid gap-1">
          <p className="text-xs font-semibold">{t("plan.covers")}</p>
          <ul className="grid gap-1 text-sm">
            {task.acceptance_criteria.map((criterion) => (
              <li key={criterion} className="flex gap-2">
                <span aria-hidden="true">·</span>
                <span>{criterion}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {task.is_user_authored && (
        <p className="muted text-xs">{t("plan.editTask")}</p>
      )}
    </aside>
  );
}

function MilestoneProgress({ milestone }: { milestone: PlanMilestone }) {
  const { t, formatNumber } = usePreferences();
  const ratio = milestone.task_count === 0 ? 0 : milestone.completed_task_count / milestone.task_count;
  return (
    <div className="card grid gap-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{milestone.title}</h3>
        <span className="muted text-sm">
          {t("common.of", {
            current: formatNumber(milestone.completed_task_count),
            total: formatNumber(milestone.task_count),
          })}
        </span>
      </div>
      {/*
        `role="progressbar"` with the value attributes, rather than a styled div.
        A progress bar a screen reader cannot read is a progress bar that does
        not exist for half the people looking at it.
      */}
      <div
        aria-label={milestone.title}
        aria-valuemax={milestone.task_count}
        aria-valuemin={0}
        aria-valuenow={milestone.completed_task_count}
        className="h-2 overflow-hidden rounded-full bg-[var(--color-surface-sunken)]"
        role="progressbar"
      >
        <div
          className="h-full bg-[var(--color-accent)]"
          style={{ width: `${Math.round(ratio * 100)}%` }}
        />
      </div>
      {milestone.description && <p className="muted text-sm">{milestone.description}</p>}
    </div>
  );
}


// -- helpers ---------------------------------------------------------------

/**
 * Group tasks under the milestone that claims them.
 *
 * Ordering by milestone rather than by raw position is the difference between a
 * list and a schedule: "what do I do next" is a milestone question, and a flat
 * position list answers it by accident.
 */
function groupByMilestone(plan: WorkPlan | null): { milestone: PlanMilestone | null; tasks: PlanTask[] }[] {
  if (!plan) return [];
  const byKey = new Map(plan.tasks.map((task) => [task.key, task]));
  const claimed = new Set<string>();
  // Annotated rather than inferred: `.map` alone would narrow `milestone` to
  // non-null, and the "no milestone claims this task" group below is exactly the
  // case the inference cannot express.
  const groups: { milestone: PlanMilestone | null; tasks: PlanTask[] }[] = plan.milestones
    .slice()
    .sort((a, b) => a.position - b.position)
    .map((milestone) => {
      const tasks = milestone.task_keys
        .map((key) => byKey.get(key))
        .filter((task): task is PlanTask => Boolean(task));
      tasks.forEach((task) => claimed.add(task.key));
      return { milestone, tasks };
    });

  // A task no milestone claims would otherwise be invisible, which is a worse
  // outcome than an "unassigned" heading.
  const unassigned = plan.tasks.filter((task) => !claimed.has(task.key));
  if (unassigned.length > 0) {
    groups.push({ milestone: null, tasks: unassigned });
  }
  return groups;
}

/**
 * Why the deterministic engine answered instead of the model, if it did.
 *
 * The reasons come from the plan as data, not from parsing the English prose in
 * `validation_warnings`. Two reasons for that: the reasons are the planner's
 * actual findings, so a generic "the model was unavailable" would be less true
 * than the data; and a substring match on server prose breaks the moment the
 * server rewords it, which would turn a stated fallback into a silent one.
 */
function fallbackReasons(plan: WorkPlan): string[] {
  if (!plan.used_fallback) return [];
  return plan.rejection_reasons.length > 0
    ? plan.rejection_reasons
    : [plan.validation_warnings[0] ?? ""].filter(Boolean);
}

