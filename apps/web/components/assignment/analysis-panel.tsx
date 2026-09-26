"use client";

import { useState } from "react";
import { Alert, LoadingState } from "@/components/ui";
import { useAnalysis, sourceKindLabel } from "@/lib/use-analysis";
import type {
  AssignmentAnalysis,
  AssignmentType,
  ClassifiedDomain,
  ClassifiedType,
  EvaluationAnalysis,
  NormalizedRequirement,
  Objective,
  ScopeAnalysis,
} from "@/lib/types";

/** Show provenance next to each finding. */
function SourceTag({ source }: { source: SourceKind }) {
  return <span className="text-xs font-medium ms-1">{sourceKindLabel(source)}</span>;
}

export function AnalysisPanel({ assignmentId }: { assignmentId: string }) {
  const { data, loading, error, refresh, hasType, hasDomain, confidenceLabel } =
    useAnalysis(assignmentId);

  if (loading) {
    return <LoadingState label="Loading analysis" />;
  }

  if (error) {
    return <Alert tone="error">{error}</Alert>;
  }

  if (!data) {
    return <Alert>No analysis found for this assignment.</Alert>;
  }

  return (
    <section className="card p-6" id="analysis">
      <h2 className="section-title">Analysis</h2>

      {/* Classification */}
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="text-sm font-medium text-slate-600">Assignment type(s)</p>
          <p className="mt-1 text-sm">
            {data.assignment_types
              .map((t) => assignmentTypeLabel(t.type))
              .join(", ")}
            {data.assignment_types.length > 0 ? ` (${data.assignment_types.length} type${data.assignment_types.length > 1 ? "s" : ""})` : ""}
          </p>
        </div>
        <div>
          <p className="text-sm font-medium text-slate-600">Academic domain(s)</p>
          <p className="mt-1 text-sm">
            {data.academic_domains
              .map((d) => {
                const label = hasDomain(d.domain)
                  ? "COMPUTER_SCIENCE" // placeholder - real label from format
                  : d.domain;
                return label;
              })
              .join(", ")}
          </p>
        </div>
      </div>

      {/* Findings section */}
      {data.ambiguities.length > 0 || data.contradictions.length > 0 || data.missing_information.length > 0 && (
        <div className="mt-6">
          <p className="text-sm font-medium text-slate-600">Findings</p>

          {data.ambiguities.length > 0 && (
            <div className="mt-3 p-3 rounded border-slate-200 bg-slate-50">
              <p className="font-semibold text-slate-800">Ambiguities ({data.ambiguities.length})</p>
              <ul className="mt-2 space-y-1 text-sm text-slate-700">
                {data.ambiguities.map((a) => (
                  <li key={a.key}>
                    <span className="font-medium">{a.description}</span>
                    <span className="text-xs ms-2 mt-0.5 block">{SourceTag({ source: a.evidence.length > 0 ? a.evidence[0].source_type ?? "INFERENCE" : "UNCERTAIN" })}</span>
                    {a.suggested_clarification && (
                      <p className="mt-1 text-xs text-slate-500">
                        Suggested: {a.suggested_clarification}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.contradictions.length > 0 && (
            <div className="mt-3 p-3 rounded border-red-200 bg-red-50">
              <p className="font-semibold text-red-800">Contradictions ({data.contradictions.length})</p>
              <ul className="mt-2 space-y-1 text-sm text-red-700">
                {data.contradictions.map((c) => (
                  <li key={c.key}>
                    <span className="font-medium">{c.description}</span>
                    <span className="text-xs ms-2 mt-0.5 block">{SourceTag({ source: c.evidence.length > 0 ? c.evidence[0].source_type ?? "INFERENCE" : "UNCERTAIN" })}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.missing_information.length > 0 && (
            <div className="mt-3 p-3 rounded border-amber-200 bg-amber-50">
              <p className="font-semibold text-amber-800">Missing information ({data.missing_information.length})</p>
              <ul className="mt-2 space-y-1 text-sm text-amber-700">
                {data.missing_information.map((m) => (
                  <li key={m.key}>
                    <span className="font-medium">{m.description}</span>
                    <span className="text-xs ms-2 mt-0.5 block">{SourceTag({ source: m.evidence.length > 0 ? m.evidence[0].source_type ?? "INFERENCE" : "UNCERTAIN" })}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Clarification questions */}
      {data.clarification_questions.length > 0 && (
        <div className="mt-6">
          <p className="text-sm font-medium text-slate-600">Clarification questions ({data.clarification_questions.length})</p>
          <ul className="mt-3 space-y-3 text-sm text-slate-700">
            {data.clarification_questions.map((q) => (
              <li key={q.id}>
                <p className="font-medium">{q.question}</p>
                <p className="text-xs text-slate-500">Priority: {q.priority}</p>
                {q.answer ? (
                  <p className="mt-1 text-xs text-emerald-600">Answered: {q.answer}</p>
                ) : (
                  <div className="mt-1 flex gap-2">
                    <input
                      ref={el => (el?.focus?.() ? el.focus() : undefined)}
                      type="text"
                      placeholder="Answer…"
                      className="flex-1 rounded border px-2 py-1 text-sm"
                    />
                    <button className="btn-secondary px-3 py-1 text-xs">
                      Answer
                    </button>
                    <button className="btn-secondary px-3 py-1 text-xs">
                      Dismiss
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Deliverables */}
      {data.deliverables.length > 0 && (
        <div className="mt-6">
          <p className="text-sm font-medium text-slate-600">Deliverables ({data.deliverables.length})</p>
          <ul className="mt-3 space-y-2 text-sm text-slate-700">
            {data.deliverables.map((d) => (
              <li key={d.key}>
                <p className="font-medium">{d.title}</p>
                <p className="text-xs text-slate-500">
                  Required: {d.required === true ? "Yes" : d.required === false ? "No" : "Unknown"} · Format: {d.format ?? "N/A"}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Uncertainty: {sourceKindLabel(d.uncertainty)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Evaluation */}
      {data.evaluation && (
        <div className="mt-6">
          <p className="text-sm font-medium text-slate-600">Evaluation</p>
          <p className="mt-1 text-sm">
            Rubric available: {data.evaluation.rubric_available ? "Yes" : "No"}
          </p>
          {data.evaluation.missing_rubric_information.length > 0 && (
            <p className="mt-1 text-xs text-amber-600">
              Missing: {data.evaluation.missing_rubric_information.join(", ")}
            </p>
          )}
        </div>
      )}

      {/* Scope */}
      {data.scope && (
        <div className="mt-6">
          <p className="text-sm font-medium text-slate-600">Scope</p>
          <dl className="mt-3 grid grid-cols-2 gap-4 text-sm">
            <dt>Breadth</dt> <dd>{data.scope.breadth.level}</dd>
            <dt>Depth</dt> <dd>{data.scope.depth.level}</dd>
            <dt>Research intensity</dt> <dd>{data.scope.research_intensity.level}</dd>
            <dt>Technical complexity</dt> <dd>{data.scope.technical_complexity.level}</dd>
            <dt>Writing intensity</dt> <dd>{data.scope.writing_intensity.level}</dd>
            <dt>Overall</dt> <dd>{data.scope.overall}</dd>
          </dl>
        </div>
      )}

      {/* Work areas */}
      {data.work_areas.length > 0 && (
        <div className="mt-6">
          <p className="text-sm font-medium text-slate-600">Work areas ({data.work_areas.length})</p>
          <ul className="mt-3 space-y-2 text-sm text-slate-700">
            {data.work_areas.map((w) => (
              <li key={w.key}>
                <p className="font-medium">{w.title}</p>
                <p className="text-xs text-slate-500">
                  Category: {w.category} · Origin: {sourceKindLabel(w.origin)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}