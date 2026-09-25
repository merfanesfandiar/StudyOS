"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { formatDate, humanize } from "@/lib/format";
import type { ActivityEvent, VersionSummary } from "@/lib/types";
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

  return (
    <section className="card p-6" data-testid="history-section" id="history">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">History</h2>
          <p className="mt-1 text-sm text-slate-500">
            What changed, and the snapshots taken along the way.
          </p>
        </div>
        <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
          <button
            aria-pressed={tab === "activity"}
            className={`rounded-md px-3 py-1 text-xs font-semibold ${
              tab === "activity" ? "bg-white text-slate-900" : "text-slate-500"
            }`}
            onClick={() => setTab("activity")}
            type="button"
          >
            Activity
          </button>
          <button
            aria-pressed={tab === "versions"}
            className={`rounded-md px-3 py-1 text-xs font-semibold ${
              tab === "versions" ? "bg-white text-slate-900" : "text-slate-500"
            }`}
            onClick={() => setTab("versions")}
            type="button"
          >
            Versions
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
  error: string;
}

function ActivityFeed({ assignmentId }: { assignmentId: string }) {
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
          error: "",
        });
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setState({
          page,
          events: [],
          pages: 1,
          error:
            caught instanceof ApiError ? caught.message : "Could not load the activity feed.",
        });
      });
    return () => {
      active = false;
    };
  }, [assignmentId, page]);

  const loading = state?.page !== page;
  const events = loading ? [] : state.events;
  const pages = loading ? 1 : state.pages;
  const error = loading ? "" : state.error;

  return (
    <div className="mt-5">
      {error ? <Alert>{error}</Alert> : null}
      {loading && events.length === 0 ? (
        <p className="text-sm text-slate-500">Loading activity…</p>
      ) : null}
      {!loading && events.length === 0 && !error ? (
        <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
          Nothing recorded yet.
        </p>
      ) : null}
      {events.length ? (
        <ol className="space-y-2" data-testid="activity-feed">
          {events.map((event) => (
            <li className="rounded-xl border border-slate-200 p-3" key={event.id}>
              <p className="text-sm text-slate-900">
                {event.change_summary ?? humanize(event.event_type)}
              </p>
              <p className="mt-0.5 text-xs text-slate-400">{formatDate(event.created_at)}</p>
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
            Newer
          </button>
          <span className="text-xs text-slate-500">
            Page {page} of {pages}
          </span>
          <button
            className="btn-secondary"
            disabled={loading || page >= pages}
            onClick={() => setPage((value) => value + 1)}
            type="button"
          >
            Older
          </button>
        </div>
      ) : null}
    </div>
  );
}

interface VersionState {
  versions: VersionSummary[] | null;
  error: string;
  opening: boolean;
  snapshotError: string;
  snapshot: Record<string, unknown> | null;
}

function VersionList({ assignmentId }: { assignmentId: string }) {
  const [state, setState] = useState<VersionState>({
    versions: null,
    error: "",
    opening: false,
    snapshotError: "",
    snapshot: null,
  });

  useEffect(() => {
    let active = true;
    api
      .versions(assignmentId)
      .then((result) => {
        if (!active) return;
        setState((current) => ({ ...current, versions: result.items, error: "" }));
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setState((current) => ({
          ...current,
          versions: [],
          error:
            caught instanceof ApiError ? caught.message : "Could not load the versions.",
        }));
      });
    return () => {
      active = false;
    };
  }, [assignmentId]);

  async function openVersion(version: number) {
    setState((current) => ({ ...current, opening: true, snapshotError: "", snapshot: null }));
    try {
      const result = await api.version(assignmentId, version);
      setState((current) => ({ ...current, snapshot: result.snapshot }));
    } catch (caught) {
      setState((current) => ({
        ...current,
        snapshotError: caught instanceof ApiError ? caught.message : "Could not load that version.",
      }));
    } finally {
      setState((current) => ({ ...current, opening: false }));
    }
  }

  const { versions, error, opening, snapshot, snapshotError } = state;

  return (
    <div className="mt-5">
      {error ? <Alert>{error}</Alert> : null}
      {versions === null && !error ? (
        <p className="text-sm text-slate-500">Loading versions…</p>
      ) : null}
      {versions?.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">
          No snapshots yet. One is taken whenever the specification changes.
        </p>
      ) : null}
      {versions?.length ? (
        <ol className="space-y-2" data-testid="version-list">
          {versions.map((version) => (
            <li
              className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 p-3"
              key={version.version}
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">Version {version.version}</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {version.change_summary || "Specification snapshot"}
                </p>
                <p className="mt-0.5 text-xs text-slate-400">{formatDate(version.created_at)}</p>
              </div>
              <button
                className="btn-secondary shrink-0"
                disabled={opening}
                onClick={() => void openVersion(version.version)}
                type="button"
              >
                View
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
          className="mt-4 max-h-80 overflow-auto rounded-xl bg-slate-900 p-4 text-xs leading-5 text-slate-100"
          data-testid="version-snapshot"
        >
          {JSON.stringify(snapshot, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}
