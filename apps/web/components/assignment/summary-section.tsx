"use client";

import { formatDate, formatWeight, humanize, statusLabel } from "@/lib/format";
import type { AssignmentSpecification } from "@/lib/types";
import { StatusBadge } from "@/components/ui";

/**
 * The read-only roll-up the API computes. It is deliberately server-derived so
 * the numbers here cannot drift from the readiness gate.
 */
export function SummarySection({ specification }: { specification: AssignmentSpecification }) {
  const { summary, assignment, updated_at: updatedAt, specification_version: version } =
    specification;
  const requirementsByStatus = Object.entries(summary.requirements_by_status).filter(
    ([, count]) => count > 0,
  );

  return (
    <section className="card p-6" data-testid="summary-section" id="summary">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Specification summary</h2>
          <p className="mt-1 text-sm text-slate-500">
            Version {version} · last changed {formatDate(updatedAt)}
          </p>
        </div>
        <StatusBadge status={summary.readiness} />
      </div>

      <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Course">
          {assignment.course_code} · {assignment.course_name}
        </Fact>
        <Fact label="Deadline">{formatDate(assignment.deadline)}</Fact>
        <Fact label="Readiness">
          {summary.readiness_score}% · {statusLabel(summary.readiness)}
        </Fact>
        <Fact label="Requirements">
          {summary.requirements_total} total · {summary.requirements_required} required ·{" "}
          {summary.requirements_completed} completed · {summary.requirements_verified} verified
        </Fact>
        <Fact label="Constraints">
          {summary.constraints_total} total
          {summary.constraints_by_severity.CRITICAL
            ? ` · ${summary.constraints_by_severity.CRITICAL} critical`
            : ""}
        </Fact>
        <Fact label="Criteria">
          {summary.criteria_count} · {formatWeight(summary.criteria_total)} of 100%
          {summary.criteria_balanced ? "" : " (unbalanced)"}
        </Fact>
        <Fact label="Deliverables">
          {summary.deliverables_total} total · {summary.deliverables_completed} completed
        </Fact>
        <Fact label="Resources">{summary.resources_total} attached</Fact>
        <Fact label="Tools">
          {summary.technologies.length ? summary.technologies.join(", ") : "None recorded"}
        </Fact>
        <Fact label="Tags">{summary.tags.length ? summary.tags.join(", ") : "None"}</Fact>
        <Fact label="Critical requirements">{summary.critical_requirements}</Fact>
      </dl>

      {requirementsByStatus.length ? (
        <div className="mt-5 border-t border-slate-100 pt-5">
          <h3 className="text-sm font-semibold text-slate-900">Requirements by status</h3>
          <ul className="mt-2 flex flex-wrap gap-2 text-xs">
            {requirementsByStatus.map(([status, count]) => (
              <li className="rounded-full bg-slate-100 px-3 py-1 font-semibold text-slate-600" key={status}>
                {humanize(status)} {count}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-slate-900">{children}</dd>
    </div>
  );
}
