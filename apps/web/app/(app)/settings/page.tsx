"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { usePreferences } from "@/components/preferences-provider";
import { LanguageToggle, ThemeToggle } from "@/components/preferences-controls";
import { Alert, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useDocumentTitle } from "@/lib/use-document-title";
import type { Notification } from "@/lib/types";

export default function SettingsPage() {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<unknown>(null);
  const { t, count, formatDate } = usePreferences();

  useDocumentTitle(t("nav.settings"));

  useEffect(() => {
    let active = true;
    api
      .notifications()
      .then((items) => {
        if (active) setNotifications(items);
      })
      .catch((caught: unknown) => {
        if (active) setFailure(caught);
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
      setFailure(caught);
    }
  }

  const error = failure ? (failure instanceof ApiError ? failure.message : t("settings.loadFailed")) : "";
  const unread = notifications.filter((notification) => !notification.read_at).length;

  return (
    <div className="mx-auto max-w-5xl" id="main-content">
      <PageHeader description={t("settings.description")} title={t("nav.settings")} />
      {error ? <div className="mb-5"><Alert>{error}</Alert></div> : null}
      <div className="grid gap-8 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <aside>
          <section className="card p-6">
            <h2 className="section-title">{t("settings.account")}</h2>
            <dl className="mt-5 space-y-4 text-sm">
              <div>
                <dt className="font-medium text-[var(--color-ink-subtle)]">{t("common.name")}</dt>
                <dd className="mt-1 font-semibold text-[var(--color-ink)]">{user?.name}</dd>
              </div>
              <div>
                <dt className="font-medium text-[var(--color-ink-subtle)]">{t("common.email")}</dt>
                <dd className="mt-1 break-all font-semibold text-[var(--color-ink)]">{user?.email}</dd>
              </div>
              <div>
                <dt className="font-medium text-[var(--color-ink-subtle)]">{t("settings.memberSince")}</dt>
                <dd className="mt-1 font-semibold text-[var(--color-ink)]">{formatDate(user?.created_at)}</dd>
              </div>
            </dl>
          </section>
          <section className="card mt-5 p-6">
            <h2 className="section-title">{t("settings.workspace")}</h2>
            <p className="mt-3 text-sm leading-6 text-[var(--color-ink-muted)]">{t("settings.workspaceBody")}</p>
            <div className="mt-5 grid gap-4">
              {/*
                Appearance and language are shown here as well as in the shell.
                The header toggles are for changing a preference in passing; this
                is where someone goes to find out what the settings *are*.
              */}
              <div>
                <p className="text-sm font-medium text-[var(--color-ink-subtle)]">{t("settings.appearance")}</p>
                <div className="mt-2">
                  <ThemeToggle />
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-[var(--color-ink-subtle)]">{t("settings.language")}</p>
                <div className="mt-2">
                  <LanguageToggle />
                </div>
              </div>
            </div>
          </section>
        </aside>
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="section-title">{t("settings.notifications")}</h2>
            {unread ? <span className="rounded-full bg-[var(--color-accent-soft)] px-2.5 py-1 text-xs font-bold text-[var(--color-accent-hover)]">{count("settings.unread", unread)}</span> : null}
          </div>
          {loading ? (
            <LoadingState />
          ) : notifications.length ? (
            <div className="card divide-y divide-[var(--color-surface-sunken)]">
              {notifications.map((notification) => (
                <article className="p-5" key={notification.id}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex gap-3">
                      {!notification.read_at ? <span className="mt-2 size-2 shrink-0 rounded-full bg-[var(--color-accent)]" /> : null}
                      <div>
                        <h3 className="font-semibold text-[var(--color-ink)]">{notification.title}</h3>
                        <p className="mt-1 text-sm leading-6 text-[var(--color-ink-muted)]">{notification.message}</p>
                        <p className="mt-2 text-xs text-[var(--color-ink-subtle)]">{formatDate(notification.created_at)}</p>
                      </div>
                    </div>
                    {!notification.read_at ? (
                      <button className="btn-secondary shrink-0" onClick={() => void markRead(notification.id)} type="button">
                        {t("settings.markRead")}
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              description={t("settings.emptyNotificationsBody")}
              title={t("settings.emptyNotifications")}
            />
          )}
        </section>
      </div>
    </div>
  );
}
