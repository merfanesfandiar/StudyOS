"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { Alert, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Notification } from "@/lib/types";

export default function SettingsPage() {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .notifications()
      .then((items) => {
        if (active) setNotifications(items);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Could not load notifications.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function markRead(id: string) {
    try {
      const updated = await api.markNotificationRead(id);
      setNotifications((items) => items.map((item) => (item.id === id ? updated : item)));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update the notification.");
    }
  }

  const unread = notifications.filter((notification) => !notification.read_at).length;

  return (
    <div className="mx-auto max-w-5xl" id="main-content">
      <PageHeader description="Review your account and keep up with workspace notifications." title="Settings" />
      {error ? <div className="mb-5"><Alert>{error}</Alert></div> : null}
      <div className="grid gap-8 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <aside>
          <section className="card p-6">
            <h2 className="section-title">Account</h2>
            <dl className="mt-5 space-y-4 text-sm">
              <div>
                <dt className="font-medium text-slate-500">Name</dt>
                <dd className="mt-1 font-semibold text-slate-900">{user?.name}</dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">Email</dt>
                <dd className="mt-1 break-all font-semibold text-slate-900">{user?.email}</dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">Member since</dt>
                <dd className="mt-1 font-semibold text-slate-900">{formatDate(user?.created_at)}</dd>
              </div>
            </dl>
          </section>
          <section className="card mt-5 p-6">
            <h2 className="section-title">Workspace</h2>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              You are the owner of a private workspace. Courses, assignments, and documents are visible only to you in Phase 1.
            </p>
          </section>
        </aside>
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title">Notifications</h2>
            {unread ? <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-bold text-indigo-700">{unread} unread</span> : null}
          </div>
          {loading ? (
            <LoadingState label="Loading notifications" />
          ) : notifications.length ? (
            <div className="card divide-y divide-slate-100">
              {notifications.map((notification) => (
                <article className="p-5" key={notification.id}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex gap-3">
                      {!notification.read_at ? <span className="mt-2 size-2 shrink-0 rounded-full bg-indigo-500" /> : null}
                      <div>
                        <h3 className="font-semibold text-slate-950">{notification.title}</h3>
                        <p className="mt-1 text-sm leading-6 text-slate-600">{notification.message}</p>
                        <p className="mt-2 text-xs text-slate-400">{formatDate(notification.created_at)}</p>
                      </div>
                    </div>
                    {!notification.read_at ? (
                      <button className="btn-secondary shrink-0" onClick={() => void markRead(notification.id)} type="button">
                        Mark read
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState description="Workspace updates and deadline reminders will appear here." title="No notifications" />
          )}
        </section>
      </div>
    </div>
  );
}
