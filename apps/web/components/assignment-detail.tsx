"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AssignmentBrief } from "@/components/assignment/assignment-brief";
import { ConstraintsSection, CriteriaSection } from "@/components/assignment/content-sections";
import { HistorySection } from "@/components/assignment/history-section";
import { ReadinessPanel } from "@/components/assignment/readiness-panel";
import { RequirementsSection } from "@/components/assignment/requirements-section";
import { ResourcesSection } from "@/components/assignment/resources-section";
import { SummarySection } from "@/components/assignment/summary-section";
import { DeliverablesSection, TaxonomySection } from "@/components/assignment/taxonomy-section";
import { AnalysisPanel } from "@/components/assignment/analysis-panel";
import { PlanPanel } from "@/components/planning/plan-panel";
import { Alert, LoadingState, PageHeader, StatusBadge } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n/messages";
import type { Course } from "@/lib/types";
import { useSpecification } from "@/lib/use-specification";
import { usePreferences } from "@/components/preferences-provider";

const SECTIONS: { href: string; key: MessageKey }[] = [
  { href: "#brief", key: "assignment.sections.brief" },
  { href: "#readiness", key: "assignment.sections.readiness" },
  { href: "#requirements", key: "assignment.sections.requirements" },
  { href: "#constraints", key: "assignment.sections.constraints" },
  { href: "#criteria", key: "assignment.sections.criteria" },
  { href: "#deliverables", key: "assignment.sections.deliverables" },
  { href: "#analysis", key: "assignment.sections.analysis" },
  { href: "#stack", key: "assignment.sections.stack" },
  { href: "#resources", key: "assignment.sections.resources" },
  { href: "#summary", key: "assignment.sections.summary" },
  { href: "#history", key: "assignment.sections.history" },
];

export function AssignmentDetail({ assignmentId }: { assignmentId: string }) {
  const router = useRouter();
  const { t } = usePreferences();
  const { specification, graph, loading, error, refresh } = useSpecification(assignmentId);
  const [courses, setCourses] = useState<Course[]>([]);
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .courses()
      .then((result) => {
        if (active) setCourses(result);
      })
      .catch(() => {
        // The course list only powers the edit form; the brief still renders.
        if (active) setCourses([]);
      });
    return () => {
      active = false;
    };
  }, []);

  async function deleteAssignment() {
    if (!specification) return;
    if (!window.confirm(`Delete ${specification.assignment.title} and all of its documents?`)) return;
    setDeleteError("");
    try {
      await api.deleteAssignment(specification.assignment.id);
      router.push("/assignments");
      router.refresh();
    } catch (caught) {
      setDeleteError(
        caught instanceof ApiError ? caught.message : t("assignment.deleteFailed"),
      );
    }
  }

  if (loading && !specification) {
    return <LoadingState label={t("assignment.loading")} />;
  }

  if (!specification) {
    return <Alert>{error || t("assignment.loadFailed")}</Alert>;
  }

  return (
    <div id="main-content">
      <PageHeader
        action={
          <nav aria-label={t("assignment.sectionsLabel")} className="flex flex-wrap justify-end gap-1">
            {SECTIONS.map((section) => (
              <a
                className="rounded-md px-2 py-1 text-xs font-semibold text-[var(--color-ink-subtle)] hover:bg-[var(--color-surface-sunken)] hover:text-[var(--color-ink)]"
                href={section.href}
                key={section.href}
              >
                {t(section.key)}
              </a>
            ))}
          </nav>
        }
        description={`${specification.assignment.course_code} · ${specification.assignment.course_name}`}
        title={specification.assignment.title}
      />

      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <Link className="text-sm font-semibold text-[var(--color-accent-hover)]" href="/assignments">
          ← Back to assignments
        </Link>
        <StatusBadge status={specification.assignment.status} />
      </div>

      {error || deleteError ? (
        <div className="mb-5">
          <Alert>{error || deleteError}</Alert>
        </div>
      ) : null}

      <div className="space-y-6">
        <AssignmentBrief
          courses={courses}
          onChanged={refresh}
          onDelete={() => void deleteAssignment()}
          specification={specification}
        />
        <ReadinessPanel onChanged={refresh} specification={specification} />
        <RequirementsSection
          graph={graph}
          onChanged={refresh}
          specification={specification}
        />
        <div className="grid gap-6 xl:grid-cols-2">
          <ConstraintsSection onChanged={refresh} specification={specification} />
          <CriteriaSection onChanged={refresh} specification={specification} />
          <DeliverablesSection onChanged={refresh} specification={specification} />
          <TaxonomySection onChanged={refresh} specification={specification} />
        </div>
        <ResourcesSection onChanged={refresh} specification={specification} />
        <SummarySection specification={specification} />
        <AnalysisPanel
          assignmentId={specification.assignment.id}
          refreshToken={specification.specification_version}
        />
        {/*
          The plan sits below the analysis on purpose. Planning reads a frozen
          analysis contract and never the raw brief, so showing it first would
          invite the reader to treat an unreviewed classification as a brief.
        */}
        <PlanPanel assignmentId={specification.assignment.id} />
        <HistorySection
          assignmentId={assignmentId}
          refreshToken={specification.specification_version}
        />
      </div>
    </div>
  );
}
