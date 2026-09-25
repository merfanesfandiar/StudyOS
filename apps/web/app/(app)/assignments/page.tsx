"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AssignmentCard } from "@/components/assignment-card";
import { Alert, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Assignment, AssignmentStatus } from "@/lib/types";

const filters: Array<{ label: string; value: "ALL" | AssignmentStatus }> = [
  { label: "All", value: "ALL" },
  { label: "Draft", value: "DRAFT" },
  { label: "Active", value: "ACTIVE" },
  { label: "Completed", value: "COMPLETED" },
  { label: "Archived", value: "ARCHIVED" },
];

export default function AssignmentsPage() {
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"ALL" | AssignmentStatus>("ALL");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    api
      .assignments()
      .then((items) => {
        if (active) setAssignments(items);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Could not load assignments.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const visible = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return assignments.filter((assignment) => {
      const matchesStatus = filter === "ALL" || assignment.status === filter;
      const matchesQuery =
        !normalized ||
        assignment.title.toLowerCase().includes(normalized) ||
        assignment.course_name.toLowerCase().includes(normalized) ||
        assignment.course_code.toLowerCase().includes(normalized);
      return matchesStatus && matchesQuery;
    });
  }, [assignments, filter, query]);

  if (loading) return <LoadingState label="Loading assignments" />;

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
      <div className="card mb-6 flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div aria-label="Filter assignments" className="flex flex-wrap gap-2">
          {filters.map((item) => (
            <button
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                filter === item.value
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
              key={item.value}
              onClick={() => setFilter(item.value)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        <label className="field sm:max-w-xs sm:flex-1">
          <span className="sr-only">Search assignments</span>
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search assignments"
            type="search"
            value={query}
          />
        </label>
      </div>
      {visible.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((assignment) => (
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
          description={assignments.length ? "Try a different status or search term." : "Create an assignment from one of your courses."}
          title={assignments.length ? "No matching assignments" : "No assignments yet"}
        />
      )}
    </div>
  );
}
