"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AssignmentCard } from "@/components/assignment-card";
import { usePreferences } from "@/components/preferences-provider";
import { Alert, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import { statusLabel } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n/messages";
import type { AssignmentFilters, AssignmentListItem, AssignmentStatus, Page } from "@/lib/types";
import { useDocumentTitle } from "@/lib/use-document-title";

// The label is a message key rather than a string, so a filter reads in the
// user's language. The value stays the API's enum: translating the wire format
// would make the request disagree with the server's contract.
const STATUS_FILTERS: Array<{ label: MessageKey; value: "ALL" | AssignmentStatus }> = [
  { label: "filters.all", value: "ALL" },
  { label: "status.draft", value: "DRAFT" },
  { label: "filters.incomplete", value: "INCOMPLETE" },
  { label: "filters.ready", value: "READY_FOR_ANALYSIS" },
  { label: "filters.analyzed", value: "ANALYZED" },
  { label: "status.completed", value: "COMPLETED" },
  { label: "status.archived", value: "ARCHIVED" },
];

const READINESS_FILTERS: Array<{ label: MessageKey; value: "ANY" | "READY" | "NOT_READY" }> = [
  { label: "filters.anyReadiness", value: "ANY" },
  { label: "status.ready_for_analysis", value: "READY" },
  { label: "filters.notReady", value: "NOT_READY" },
];

const SORTS: Array<{ label: MessageKey; value: NonNullable<AssignmentFilters["sort_by"]> }> = [
  { label: "common.deadline", value: "deadline" },
  { label: "common.title", value: "title" },
  { label: "readiness.title", value: "readiness_score" },
  { label: "dashboard.recentlyUpdated", value: "updated_at" },
];

const PAGE_SIZE = 12;

interface ListState {
  key: string;
  items: AssignmentListItem[];
  page: Page;
  error: string;
}

export default function AssignmentsPage() {
  const [state, setState] = useState<ListState | null>(null);
  const [status, setStatus] = useState<"ALL" | AssignmentStatus>("ALL");
  const [readiness, setReadiness] = useState<"ANY" | "READY" | "NOT_READY">("ANY");
  const [sortBy, setSortBy] = useState<NonNullable<AssignmentFilters["sort_by"]>>("deadline");
  const [search, setSearch] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const { t, count } = usePreferences();

  useDocumentTitle(t("nav.assignments"));

  const key = JSON.stringify([status, readiness, sortBy, search, pageNumber]);

  useEffect(() => {
    let active = true;
    const filters: AssignmentFilters = { page: pageNumber, page_size: PAGE_SIZE, sort_by: sortBy };
    if (status !== "ALL") filters.status = status;
    if (readiness === "READY") filters.readiness = "READY_FOR_ANALYSIS";
    if (readiness === "NOT_READY") filters.readiness = "INCOMPLETE";
    if (search.trim()) filters.search = search.trim();

    // Debounced so typing in the search box does not fire a request per key.
    const timer = setTimeout(() => {
      api
        .assignments(filters)
        .then((result) => {
          if (!active) return;
          setState({ key, items: result.items, page: result.page, error: "" });
        })
        .catch((caught: unknown) => {
          if (!active) return;
          setState({
            key,
            items: [],
            page: { page: 1, page_size: PAGE_SIZE, total: 0, pages: 0 },
            // Kept as the caught value, translated at render: putting `t` in here
            // would re-run the fetch whenever the locale changed.
            error:
              errorMessage(caught, t, "assignments.loadFailed"),
          });
        });
    }, 200);

    return () => {
      active = false;
      clearTimeout(timer);
    };
    // `t` is intentionally absent. It is stable for a given locale, and depending
    // on it would refetch the list on a theme or language change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, pageNumber, readiness, search, sortBy, status]);

  const loading = state?.key !== key;
  const assignments = loading ? [] : state.items;
  const pager = loading ? null : state.page;
  const error = loading ? "" : state.error;

  function resetPaging() {
    setPageNumber(1);
  }

  return (
    <div id="main-content">
      <PageHeader
        action={
          <Link className="btn-primary" href="/assignments/new">
            {t("assignments.new")}
          </Link>
        }
        description={t("assignments.description")}
        title={t("nav.assignments")}
      />
      {error ? (
        <div className="mb-6">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="card mb-6 space-y-4 p-4">
        <div aria-label={t("assignments.filterLabel")} className="flex flex-wrap gap-2">
          {STATUS_FILTERS.map((item) => (
            <button
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                status === item.value
                  ? "bg-[var(--color-accent)] text-white"
                  : "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)] hover:bg-[var(--color-line)]"
              }`}
              key={item.value}
              onClick={() => {
                setStatus(item.value);
                resetPaging();
              }}
              type="button"
            >
              {t(item.label)}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="field sm:max-w-xs sm:flex-1">
            <span className="sr-only">{t("assignments.search")}</span>
            <input
              onChange={(event) => {
                setSearch(event.target.value);
                resetPaging();
              }}
              placeholder={t("assignments.searchPlaceholder")}
              type="search"
              value={search}
            />
          </label>
          <label className="field sm:max-w-[12rem]">
            <span className="sr-only">{t("assignments.filterByReadiness")}</span>
            <select
              onChange={(event) => {
                setReadiness(event.target.value as typeof readiness);
                resetPaging();
              }}
              value={readiness}
            >
              {READINESS_FILTERS.map((item) => (
                <option key={item.value} value={item.value}>
                  {t(item.label)}
                </option>
              ))}
            </select>
          </label>
          <label className="field sm:max-w-[12rem]">
            <span className="sr-only">{t("assignments.sort")}</span>
            <select
              onChange={(event) => {
                setSortBy(event.target.value as typeof sortBy);
                resetPaging();
              }}
              value={sortBy}
            >
              {SORTS.map((item) => (
                <option key={item.value} value={item.value}>
                  {t("assignments.sortPrefix", { label: t(item.label) })}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {loading ? <LoadingState /> : null}

      {!loading && assignments.length ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {assignments.map((assignment) => (
              <AssignmentCard assignment={assignment} key={assignment.id} />
            ))}
          </div>
          {pager && pager.pages > 1 ? (
            <nav
              aria-label={t("assignments.pagesLabel")}
              className="mt-8 flex items-center justify-between text-sm"
            >
              <button
                className="btn-secondary"
                disabled={pager.page <= 1}
                onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
                type="button"
              >
                {t("common.previous")}
              </button>
              <span className="text-[var(--color-ink-subtle)]">
                {t("assignments.pageOf", { page: pager.page, pages: pager.pages })} ·{" "}
                {count("assignments.total", pager.total)}
              </span>
              <button
                className="btn-secondary"
                disabled={pager.page >= pager.pages}
                onClick={() => setPageNumber((value) => value + 1)}
                type="button"
              >
                {t("common.next")}
              </button>
            </nav>
          ) : null}
        </>
      ) : null}

      {!loading && !assignments.length ? (
        <EmptyState
          action={
            <Link className="btn-primary" href="/assignments/new">
              {t("assignments.create")}
            </Link>
          }
          description={
            status === "ALL" && !search
              ? t("assignments.emptyBody")
              : t("assignments.noMatch", {
                  filter:
                    status === "ALL"
                      ? t("assignments.thisSearch")
                      : statusLabel(t, status),
                })
          }
          title={status === "ALL" && !search ? t("assignments.empty") : t("assignments.noMatchTitle")}
        />
      ) : null}
    </div>
  );
}
