"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AssignmentCard } from "@/components/assignment-card";
import { Alert, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Dashboard, Notification } from "@/lib/types";

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([api.dashboard(), api.notifications()])
      .then(([dashboard, items]) => {
        if (!active) return;
        setData(dashboard);
        setNotifications(items);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof ApiError ? caught.message : "Could not load the dashboard.");
      });
    return () => {
      active = false;
    };
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <LoadingState label="Loading dashboard" />;

  const tiles = [
    { label: "In progress", value: data.in_progress_assignments_count, hint: "Drafts and open work" },
    { label: "Ready for analysis", value: data.ready_assignments_count, hint: "Gate passed" },
    { label: "Incomplete", value: data.incomplete_assignments_count, hint: "Blocking checks failing" },
    { label: "Completed", value: data.completed_assignments_count, hint: "Handed in" },
  ];
  const glance = [
    { label: "Courses", value: data.courses_count },
    { label: "Assignments", value: data.assignments_count },
    { label: "Completion", value: `${data.completion_percentage}%` },
    { label: "Average readiness", value: `${data.average_readiness_score}%` },
  ];

  return (
    <div id="main-content">
      <PageHeader
        action={
          <Link className="btn-primary" href="/assignments/new">
            New assignment
          </Link>
        }
        description="See what needs attention and keep every brief moving forward."
        title="Dashboard"
      />
      <section aria-label="Workspace summary" className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {tiles.map((tile) => (
            <div className="card p-5" key={tile.label}>
              <p className="text-sm font-medium text-slate-500">{tile.label}</p>
              <p className="mt-2 text-3xl font-black tracking-tight text-slate-950">{tile.value}</p>
              <p className="mt-1 text-xs text-slate-400">{tile.hint}</p>
            </div>
          ))}
        </div>
        <dl className="card grid gap-4 p-5 sm:grid-cols-4">
          {glance.map((item) => (
            <div key={item.label}>
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {item.label}
              </dt>
              <dd className="mt-1 text-xl font-bold text-slate-900">{item.value}</dd>
            </div>
          ))}
        </dl>
      </section>
      <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title">Upcoming deadlines</h2>
            <Link className="text-sm font-semibold text-indigo-700" href="/assignments">
              View all
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
                  Create an assignment
                </Link>
              }
              description="Add a course assignment and its deadline to see it here."
              title="Nothing due soon"
            />
          )}
          <div className="mb-4 mt-9 flex items-center justify-between">
            <h2 className="section-title">Recently updated</h2>
          </div>
          {data.recent_assignments.length ? (
            <div className="card divide-y divide-slate-100">
              {data.recent_assignments.slice(0, 5).map((assignment) => (
                <Link
                  className="flex items-center justify-between gap-4 px-5 py-4 transition hover:bg-slate-50"
                  href={`/assignments/${assignment.id}`}
                  key={assignment.id}
                >
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-slate-900">{assignment.title}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {assignment.course_code} · {assignment.readiness_score}% ready ·{" "}
                      {assignment.completed_requirements_count}/{assignment.requirements_count}{" "}
                      requirements
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-slate-500">{formatDate(assignment.deadline)}</span>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState description="Your latest assignments will appear here." title="No assignments yet" />
          )}
        </section>
        <aside>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title">Notifications</h2>
            {data.unread_notifications_count ? (
              <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-bold text-indigo-700">
                {data.unread_notifications_count} new
              </span>
            ) : null}
          </div>
          <div className="card divide-y divide-slate-100">
            {notifications.length ? (
              notifications.slice(0, 6).map((notification) => (
                <div className="p-4" key={notification.id}>
                  <div className="flex items-center gap-2">
                    {!notification.read_at ? <span className="size-2 rounded-full bg-indigo-500" /> : null}
                    <p className="font-semibold text-slate-900">{notification.title}</p>
                  </div>
                  <p className="mt-1 text-sm leading-5 text-slate-600">{notification.message}</p>
                  <p className="mt-2 text-xs text-slate-400">{formatDate(notification.created_at)}</p>
                </div>
              ))
            ) : (
              <div className="p-6 text-center text-sm text-slate-500">You are all caught up.</div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
