"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AssignmentCard } from "@/components/assignment-card";
import { usePreferences } from "@/components/preferences-provider";
import { Alert, EmptyState, PageHeader, ReadinessMeter, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import { formatDate } from "@/lib/format";
import type { Dashboard, Notification } from "@/lib/types";

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [failure, setFailure] = useState<unknown>(null);
  const { t, count, formatNumber } = usePreferences();

  useEffect(() => {
    let active = true;
    Promise.all([api.dashboard(), api.notifications()])
      .then(([dashboard, result]) => {
        if (!active) return;
        setData(dashboard);
        setNotifications(result.items);
      })
      .catch((caught: unknown) => {
        if (active) setFailure(caught);
      });
    return () => {
      active = false;
    };
  }, []);

  if (failure) {
    return <Alert>{errorMessage(failure, t, "dashboard.loadFailed")}</Alert>;
  }
  if (!data) return <DashboardSkeleton />;

  const tiles = [
    {
      label: t("status.in_progress"),
      value: data.in_progress_assignments_count,
      hint: t("dashboard.hint.drafts"),
      tone: "text-[var(--color-info)]",
      rule: "bg-[var(--color-info)]",
    },
    {
      label: t("status.ready_for_analysis"),
      value: data.ready_assignments_count,
      hint: t("dashboard.hint.gate"),
      tone: "text-[var(--color-positive)]",
      rule: "bg-[var(--color-positive)]",
    },
    {
      label: t("dashboard.tile.incomplete"),
      value: data.incomplete_assignments_count,
      hint: t("dashboard.hint.blocking"),
      tone: "text-[var(--color-caution)]",
      rule: "bg-[var(--color-caution)]",
    },
    {
      label: t("status.completed"),
      value: data.completed_assignments_count,
      hint: t("dashboard.hint.handedIn"),
      tone: "text-[var(--color-ink-muted)]",
      rule: "bg-[var(--color-line-strong)]",
    },
  ];
  const glance = [
    { label: t("nav.courses"), value: data.courses_count },
    { label: t("nav.assignments"), value: data.assignments_count },
    { label: t("dashboard.glance.completion"), value: `${formatNumber(data.completion_percentage)}%` },
    { label: t("dashboard.glance.readiness"), value: `${formatNumber(data.average_readiness_score)}%` },
  ];
  const next = data.upcoming_assignments[0];

  return (
    <div id="main-content">
      <PageHeader
        action={
          <Link className="btn-primary" href="/assignments/new">
            {t("assignments.new")}
          </Link>
        }
        description={t("dashboard.description")}
        title={t("nav.dashboard")}
      />
      {next ? (
        <section
          aria-label={t("dashboard.focus")}
          className="card relative mb-6 overflow-hidden p-6 shadow-[var(--shadow-card)]"
        >
          <span aria-hidden="true" className="absolute inset-y-0 start-0 w-1 bg-[var(--color-accent)]" />
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-wider text-[var(--color-accent)]">
                {t("dashboard.focusLabel")}
              </p>
              <p className="mt-2 text-xs font-semibold text-[var(--color-ink-subtle)]">{next.course_code}</p>
              <h2 className="mt-0.5 truncate text-xl font-bold tracking-tight text-[var(--color-ink)]">
                {next.title}
              </h2>
              <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{formatDate(next.deadline)}</p>
            </div>
            <div className="w-full shrink-0 sm:w-64">
              <div className="flex items-center justify-between text-xs text-[var(--color-ink-subtle)]">
                <span>
                  {next.completed_requirements_count}/{next.requirements_count} {t("requirements.shortTitle")}
                </span>
                <span className="font-semibold text-[var(--color-ink-muted)]">
                  {formatNumber(next.readiness_score)}%{" "}
                  {t("readiness.shortTitle")}
                </span>
              </div>
              <div className="mt-2">
                <ReadinessMeter score={next.readiness_score} />
              </div>
              <Link className="btn-primary mt-4 w-full" href={`/assignments/${next.id}`}>
                {t("dashboard.openAssignment")}
              </Link>
            </div>
          </div>
        </section>
      ) : null}
      <section aria-label={t("dashboard.workspaceSummary")} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {tiles.map((tile) => (
            <div className="card relative overflow-hidden p-5" key={tile.label}>
              <span aria-hidden="true" className={`absolute inset-x-0 top-0 h-1 ${tile.rule}`} />
              <p className="text-sm font-medium text-[var(--color-ink-subtle)]">{tile.label}</p>
              <p className={`mt-2 text-3xl font-black tracking-tight ${tile.tone}`}>{tile.value}</p>
              <p className="mt-1 text-xs text-[var(--color-ink-subtle)]">{tile.hint}</p>
            </div>
          ))}
        </div>
        <dl className="card grid gap-4 p-5 sm:grid-cols-4">
          {glance.map((item) => (
            <div key={item.label}>
              <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-subtle)]">
                {item.label}
              </dt>
              <dd className="mt-1 text-xl font-bold text-[var(--color-ink)]">{item.value}</dd>
            </div>
          ))}
        </dl>
      </section>
      <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title">{t("dashboard.upcomingDeadlines")}</h2>
            <Link className="text-sm font-semibold text-[var(--color-accent-hover)]" href="/assignments">
              {t("dashboard.viewAll")}
            </Link>
          </div>
          {data.upcoming_assignments.length ? (
            <div className="grid gap-4 md:grid-cols-2">
              {data.upcoming_assignments.map((assignment) => (
                <AssignmentCard assignment={assignment} key={assignment.id} />
              ))}
            </div>
          ) : (
            <EmptyState
              action={
                <Link className="btn-primary" href="/assignments/new">
                  {t("assignments.create")}
                </Link>
              }
              description={t("dashboard.emptyDeadlinesBody")}
              title={t("dashboard.emptyDeadlines")}
            />
          )}
          <div className="mb-4 mt-9 flex items-center justify-between">
            <h2 className="section-title">{t("dashboard.recentlyUpdated")}</h2>
          </div>
          {data.recent_assignments.length ? (
            <div className="card divide-y divide-[var(--color-surface-sunken)]">
              {data.recent_assignments.slice(0, 5).map((assignment) => (
                <Link
                  className="flex items-center justify-between gap-4 px-5 py-4 transition hover:bg-[var(--color-canvas)]"
                  href={`/assignments/${assignment.id}`}
                  key={assignment.id}
                >
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-[var(--color-ink)]">{assignment.title}</p>
                    <p className="mt-0.5 text-xs text-[var(--color-ink-subtle)]">
                      {assignment.course_code} · {formatNumber(assignment.readiness_score)}%{" "}
                      {t("dashboard.ready")} ·{" "}
                      {assignment.completed_requirements_count}/{assignment.requirements_count}{" "}
                      {t("requirements.title")}
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-[var(--color-ink-subtle)]">{formatDate(assignment.deadline)}</span>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState description={t("dashboard.emptyRecentBody")} title={t("dashboard.emptyAssignments")} />
          )}
        </section>
        <aside>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title">{t("dashboard.notifications")}</h2>
            {data.unread_notifications_count ? (
              <span className="rounded-full bg-[var(--color-accent-soft)] px-2.5 py-1 text-xs font-bold text-[var(--color-accent-hover)]">
                {count("dashboard.unread", data.unread_notifications_count)}
              </span>
            ) : null}
          </div>
          <div className="card divide-y divide-[var(--color-surface-sunken)]">
            {notifications.length ? (
              notifications.slice(0, 6).map((notification) => (
                <div className="p-4" key={notification.id}>
                  <div className="flex items-center gap-2">
                    {!notification.read_at ? <span className="size-2 rounded-full bg-[var(--color-accent)]" /> : null}
                    <p className="font-semibold text-[var(--color-ink)]">{notification.title}</p>
                  </div>
                  <p className="mt-1 text-sm leading-5 text-[var(--color-ink-muted)]">{notification.message}</p>
                  <p className="mt-2 text-xs text-[var(--color-ink-subtle)]">{formatDate(notification.created_at)}</p>
                </div>
              ))
            ) : (
              <div className="p-6 text-center text-sm text-[var(--color-ink-subtle)]">
                {t("dashboard.caughtUp")}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

/**
 * The dashboard's own loading shape, not a spinner.
 *
 * A centred spinner says "something is happening"; a skeleton that matches the
 * cards that are about to arrive says "these cards are coming", which is both
 * less jarring and shorter. It still announces itself to assistive tech through
 * a single `role="status"` rather than a dozen decorative boxes.
 */
function DashboardSkeleton() {
  const { t } = usePreferences();
  return (
    <div aria-busy="true" id="main-content">
      <span className="sr-only" role="status">
        {t("common.loading")}
      </span>
      <div className="mb-7 space-y-3">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      <div className="card mb-6 p-6">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-6 w-2/3 max-w-md" />
        <Skeleton className="mt-2 h-4 w-40" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <div className="card p-5" key={index}>
            <Skeleton className="h-4 w-24" />
            <Skeleton className="mt-3 h-8 w-16" />
            <Skeleton className="mt-2 h-3 w-28" />
          </div>
        ))}
      </div>
    </div>
  );
}
