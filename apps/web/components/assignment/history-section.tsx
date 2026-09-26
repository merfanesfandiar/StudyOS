"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import { humanize } from "@/lib/format";
import type { ActivityEvent, VersionSummary } from "@/lib/types";
import { usePreferences } from "@/components/preferences-provider";
import { Alert } from "@/components/ui";

type Tab = "activity" | "versions";

/**
 * The audit trail and the immutable snapshots it points at.
 *
 * `refreshToken` is the assignment's specification version: it moves on every
 * change, so both panes are re-keyed and re-read rather than showing what was
 * true when the page first loaded.
 */
export function HistorySection({
  assignmentId,
  refreshToken,
}: {
  assignmentId: string;
  refreshToken: number;
}) {
  const [tab, setTab] = useState<Tab>("activity");
  const { t } = usePreferences();

  return (
    <section className="card p-6" data-testid="history-section" id="history">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{t("history.title")}</h2>
          <p className="mt-1 text-sm text-[var(--color-ink-subtle)]">
            {t("history.description")}
          </p>
        </div>
        <div className="flex gap-1 rounded-lg bg-[var(--color-surface-sunken)] p-1">
          <button
            aria-pressed={tab === "activity"}
            className={`rounded-md px-3 py-1 text-xs font-semibold ${
              tab === "activity" ? "bg-[var(--color-surface)] text-[var(--color-ink)]" : "text-[var(--color-ink-subtle)]"
            }`}
            onClick={() => setTab("activity")}
            type="button"
          >
            {t("history.activity")}
          </button>
          <button
            aria-pressed={tab === "versions"}
            className={`rounded-md px-3 py-1 text-xs font-semibold ${
              tab === "versions" ? "bg-[var(--color-surface)] text-[var(--color-ink)]" : "text-[var(--color-ink-subtle)]"
            }`}
            onClick={() => setTab("versions")}
            type="button"
          >
            {t("history.versions")}
          </button>
        </div>
      </div>

      {tab === "activity" ? (
        <ActivityFeed key={refreshToken} assignmentId={assignmentId} />
      ) : (
        <VersionList key={refreshToken} assignmentId={assignmentId} />
      )}
    </section>
  );
}

interface ActivityState {
  page: number;
  events: ActivityEvent[];
  pages: number;
  /** The caught value, not a message: resolved at render so it follows the locale. */
  failure: unknown;
}

function ActivityFeed({ assignmentId }: { assignmentId: string }) {
  const { t, formatDate } = usePreferences();
  const [page, setPage] = useState(1);
  const [state, setState] = useState<ActivityState | null>(null);

  useEffect(() => {
    let active = true;
    api
      .activity(assignmentId, page)
      .then((result) => {
        if (!active) return;
        setState({
          page,
          events: result.items,
          pages: result.page.pages,
          failure: null,
        });
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setState({
          page,
          events: [],
          pages: 1,
          failure: caught,
        });
      });
    return () => {
      active = false;
    };
  }, [assignmentId, page]);

  const loading = state?.page !== page;
  const events = loading ? [] : state.events;
  const pages = loading ? 1 : state.pages;
  const failure = loading ? null : state.failure;
  const error = failure
    ? errorMessage(failure, t, "history.activityFailed")
    : "";

  return (
    <div className="mt-5">
      {error ? <Alert>{error}</Alert> : null}
      {loading && events.length === 0 ? (
        <p className="text-sm text-[var(--color-ink-subtle)]">{t("history.loadingActivity")}</p>
      ) : null}
      {!loading && events.length === 0 && !error ? (
        <p className="rounded-xl border border-dashed border-[var(--color-line)] p-4 text-sm text-[var(--color-ink-subtle)]">
          {t("history.activityEmpty")}
        </p>
      ) : null}
      {events.length ? (
        <ol className="space-y-2" data-testid="activity-feed">
          {events.map((event) => (
            <li className="rounded-xl border border-[var(--color-line)] p-3" key={event.id}>
              <p className="text-sm text-[var(--color-ink)]">
                {event.change_summary ?? humanize(event.event_type)}
              </p>
              <p className="mt-0.5 text-xs text-[var(--color-ink-subtle)]">{formatDate(event.created_at)}</p>
            </li>
          ))}
        </ol>
      ) : null}
      {pages > 1 ? (
        <div className="mt-4 flex items-center gap-3">
          <button
            className="btn-secondary"
            disabled={loading || page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            type="button"
          >
            {t("history.newer")}
          </button>
          <span className="text-xs text-[var(--color-ink-subtle)]">
            {t("history.pageOf", { page, pages })}
          </span>
          <button
            className="btn-secondary"
            disabled={loading || page >= pages}
            onClick={() => setPage((value) => value + 1)}
            type="button"
          >
            {t("history.older")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

interface VersionState {
  versions: VersionSummary[] | null;
  failure: unknown;
  opening: boolean;
  snapshotFailure: unknown;
  snapshot: Record<string, unknown> | null;
}

function VersionList({ assignmentId }: { assignmentId: string }) {
  const { t, formatDate } = usePreferences();
  const [state, setState] = useState<VersionState>({
    versions: null,
    failure: null,
    opening: false,
    snapshotFailure: null,
    snapshot: null,
  });

  useEffect(() => {
    let active = true;
    api
      .versions(assignmentId)
      .then((result) => {
        if (!active) return;
        setState((current) => ({ ...current, versions: result.items, failure: null }));
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setState((current) => ({
          ...current,
          versions: [],
          failure: caught,
        }));
      });
    return () => {
      active = false;
    };
  }, [assignmentId]);

  async function openVersion(version: number) {
    setState((current) => ({ ...current, opening: true, snapshotFailure: null, snapshot: null }));
    try {
      const result = await api.version(assignmentId, version);
      setState((current) => ({ ...current, snapshot: result.snapshot }));
    } catch (caught) {
      setState((current) => ({
        ...current,
        snapshotFailure: caught,
      }));
    } finally {
      setState((current) => ({ ...current, opening: false }));
    }
  }

  const { versions, failure, opening, snapshot, snapshotFailure } = state;
  const error = failure
    ? errorMessage(failure, t, "history.versionsFailed")
    : "";
  const snapshotError = snapshotFailure
    ? errorMessage(snapshotFailure, t, "history.versionFailed")
    : "";

  return (
    <div className="mt-5">
      {error ? <Alert>{error}</Alert> : null}
      {versions === null && !error ? (
        <p className="text-sm text-[var(--color-ink-subtle)]">{t("history.loadingVersions")}</p>
      ) : null}
      {versions?.length === 0 ? (
        <p className="rounded-xl border border-dashed border-[var(--color-line)] p-4 text-sm text-[var(--color-ink-subtle)]">
          {t("history.versionsEmpty")}
        </p>
      ) : null}
      {versions?.length ? (
        <ol className="space-y-2" data-testid="version-list">
          {versions.map((version) => (
            <li
              className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-line)] p-3"
              key={version.version}
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[var(--color-ink)]">{t("history.version", { number: version.version })}</p>
                <p className="mt-0.5 text-xs text-[var(--color-ink-subtle)]">
                  {version.change_summary || t("history.snapshot")}
                </p>
                <p className="mt-0.5 text-xs text-[var(--color-ink-subtle)]">{formatDate(version.created_at)}</p>
              </div>
              <button
                className="btn-secondary shrink-0"
                disabled={opening}
                onClick={() => void openVersion(version.version)}
                type="button"
              >
                {t("action.view")}
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      {snapshotError ? (
        <div className="mt-4">
          <Alert>{snapshotError}</Alert>
        </div>
      ) : null}
      {snapshot ? (
        <pre
          className="mt-4 max-h-80 overflow-auto rounded-xl bg-[var(--color-ink)] p-4 text-xs leading-5 text-[var(--color-surface-sunken)]"
          data-testid="version-snapshot"
        >
          {JSON.stringify(snapshot, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
