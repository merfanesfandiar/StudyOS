"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AssignmentCard } from "@/components/assignment-card";
import { Alert, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { statusLabel } from "@/lib/format";
import type { AssignmentFilters, AssignmentListItem, AssignmentStatus, Page } from "@/lib/types";

const STATUS_FILTERS: Array<{ label: string; value: "ALL" | AssignmentStatus }> = [
  { label: "All", value: "ALL" },
  { label: "Draft", value: "DRAFT" },
  { label: "Incomplete", value: "INCOMPLETE" },
  { label: "Ready", value: "READY_FOR_ANALYSIS" },
  { label: "Analyzed", value: "ANALYZED" },
  { label: "Completed", value: "COMPLETED" },
  { label: "Archived", value: "ARCHIVED" },
];

const READINESS_FILTERS: Array<{ label: string; value: "ANY" | "READY" | "NOT_READY" }> = [
  { label: "Any readiness", value: "ANY" },
  { label: "Ready for analysis", value: "READY" },
  { label: "Not ready", value: "NOT_READY" },
];

const SORTS: Array<{ label: string; value: NonNullable<AssignmentFilters["sort_by"]> }> = [
  { label: "Deadline", value: "deadline" },
  { label: "Title", value: "title" },
  { label: "Readiness", value: "readiness_score" },
  { label: "Recently updated", value: "updated_at" },
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
            error: caught instanceof ApiError ? caught.message : "Could not load assignments.",
          });
        });
    }, 200);

    return () => {
      active = false;
      clearTimeout(timer);
    };
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
            New assignment
          </Link>
        }
        description="Turn each course brief into a structured, executable assignment plan."
        title="Assignments"
      />
      {error ? (
        <div className="mb-6">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="card mb-6 space-y-4 p-4">
        <div aria-label="Filter assignments" className="flex flex-wrap gap-2">
          {STATUS_FILTERS.map((item) => (
            <button
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                status === item.value
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
              key={item.value}
              onClick={() => {
                setStatus(item.value);
                resetPaging();
              }}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="field sm:max-w-xs sm:flex-1">
            <span className="sr-only">Search assignments</span>
            <input
              onChange={(event) => {
                setSearch(event.target.value);
                resetPaging();
              }}
              placeholder="Search title, brief, or course"
              type="search"
              value={search}
            />
          </label>
          <label className="field sm:max-w-[12rem]">
            <span className="sr-only">Filter by readiness</span>
            <select
              onChange={(event) => {
                setReadiness(event.target.value as typeof readiness);
                resetPaging();
              }}
              value={readiness}
            >
              {READINESS_FILTERS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field sm:max-w-[12rem]">
            <span className="sr-only">Sort assignments</span>
            <select
              onChange={(event) => {
                setSortBy(event.target.value as typeof sortBy);
                resetPaging();
              }}
              value={sortBy}
            >
              {SORTS.map((item) => (
                <option key={item.value} value={item.value}>
                  Sort: {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {loading ? <LoadingState label="Loading assignments" /> : null}

      {!loading && assignments.length ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {assignments.map((assignment) => (
              <AssignmentCard assignment={assignment} key={assignment.id} />
            ))}
          </div>
          {pager && pager.pages > 1 ? (
            <nav
              aria-label="Assignment pages"
              className="mt-8 flex items-center justify-between text-sm"
            >
              <button
                className="btn-secondary"
                disabled={pager.page <= 1}
                onClick={() => setPageNumber((value) => Math.max(1, value - 1))}
                type="button"
              >
                Previous
              </button>
              <span className="text-slate-500">
                Page {pager.page} of {pager.pages} · {pager.total} assignments
              </span>
              <button
                className="btn-secondary"
                disabled={pager.page >= pager.pages}
                onClick={() => setPageNumber((value) => value + 1)}
                type="button"
              >
                Next
              </button>
            </nav>
          ) : null}
        </>
      ) : null}

      {!loading && !assignments.length ? (
        <EmptyState
          action={
            <Link className="btn-primary" href="/assignments/new">
              Create an assignment
            </Link>
          }
          description={
            status === "ALL" && !search
              ? "Create an assignment from one of your courses."
              : `No assignments match ${status === "ALL" ? "this search" : statusLabel(status)}.`
          }
          title={status === "ALL" && !search ? "No assignments yet" : "No matching assignments"}
        />
      ) : null}
    </div>
  );
}
