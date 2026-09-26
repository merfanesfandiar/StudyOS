"use client";

import { formatDate, formatWeight, requirementStatusLabel, statusLabel } from "@/lib/format";
import type { AssignmentSpecification, RequirementStatus } from "@/lib/types";
import { usePreferences } from "@/components/preferences-provider";
import { StatusBadge } from "@/components/ui";

/**
 * The read-only roll-up the API computes. It is deliberately server-derived so
 * the numbers here cannot drift from the readiness gate.
 */
export function SummarySection({ specification }: { specification: AssignmentSpecification }) {
  const { t } = usePreferences();
  const { summary, assignment, updated_at: updatedAt, specification_version: version } =
    specification;
  // `Object.entries` widens the key to `string`. The API returns a bucket per
  // requirement status, and these are read back as statuses below, so the cast
  // is where that contract is reasserted rather than at each use.
  const requirementsByStatus = (
    Object.entries(summary.requirements_by_status) as [RequirementStatus, number][]
  ).filter(([, count]) => count > 0);

  return (
    <section className="card p-6" data-testid="summary-section" id="summary">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{t("summary.title")}</h2>
          <p className="mt-1 text-sm text-[var(--color-ink-subtle)]">
            {t("summary.versionChanged", { version, date: formatDate(updatedAt) })}
          </p>
        </div>
        <StatusBadge status={summary.readiness} />
      </div>

      <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label={t("summary.course")}>
          {assignment.course_code} · {assignment.course_name}
        </Fact>
        <Fact label={t("summary.deadline")}>{formatDate(assignment.deadline)}</Fact>
        <Fact label={t("summary.readiness")}>
          {summary.readiness_score}% · {statusLabel(t, summary.readiness)}
        </Fact>
        <Fact label={t("summary.requirements")}>
          {t("summary.tally", {
            total: summary.requirements_total,
            required: summary.requirements_required,
            completed: summary.requirements_completed,
            verified: summary.requirements_verified,
          })}
        </Fact>
        <Fact label={t("summary.constraints")}>
          {summary.constraints_total} total
          {summary.constraints_by_severity.CRITICAL
            ? ` · ${t("summary.criticalCount", {
                count: summary.constraints_by_severity.CRITICAL,
              })}`
            : ""}
        </Fact>
        <Fact label={t("summary.criteria")}>
          {summary.criteria_count} · {formatWeight(summary.criteria_total)} of 100%
          {summary.criteria_balanced ? "" : ` (${t("summary.unbalanced")})`}
        </Fact>
        <Fact label={t("summary.deliverables")}>
          {t("summary.deliverablesTally", {
            total: summary.deliverables_total,
            completed: summary.deliverables_completed,
          })}
        </Fact>
        <Fact label={t("summary.resources")}>{t("summary.attached", { count: summary.resources_total })}</Fact>
        <Fact label={t("summary.tools")}>
          {summary.technologies.length ? summary.technologies.join(", ") : t("summary.noneRecorded")}
        </Fact>
        <Fact label={t("summary.tags")}>
          {summary.tags.length ? summary.tags.join(", ") : t("summary.none")}
        </Fact>
        <Fact label={t("summary.criticalRequirements")}>{summary.critical_requirements}</Fact>
      </dl>

      {requirementsByStatus.length ? (
        <div className="mt-5 border-t border-[var(--color-surface-sunken)] pt-5">
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">{t("summary.byStatus")}</h3>
          <ul className="mt-2 flex flex-wrap gap-2 text-xs">
            {requirementsByStatus.map(([status, count]) => (
              <li className="rounded-full bg-[var(--color-surface-sunken)] px-3 py-1 font-semibold text-[var(--color-ink-muted)]" key={status}>
                {requirementStatusLabel(t, status)} {count}
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
      <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--color-ink-subtle)]">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-[var(--color-ink)]">{children}</dd>
    </div>
  );
}
