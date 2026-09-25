import Link from "next/link";
import { formatDate } from "@/lib/format";
import type { Assignment } from "@/lib/types";
import { StatusBadge } from "./ui";

export function AssignmentCard({ assignment }: { assignment: Assignment }) {
  return (
    <Link
      className="block rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md"
      href={`/assignments/${assignment.id}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-wider text-indigo-600">
            {assignment.course_code}
          </p>
          <h2 className="mt-1 truncate text-lg font-bold text-slate-950">{assignment.title}</h2>
          <p className="mt-1 text-sm text-slate-500">{assignment.course_name}</p>
        </div>
        <StatusBadge status={assignment.status} />
      </div>
      <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4 text-sm">
        <span className="text-slate-600">{formatDate(assignment.deadline)}</span>
        <span className="font-medium text-slate-500">{assignment.criteria_total}% weighted</span>
      </div>
    </Link>
  );
}
