"use client";

import { useState } from "react";
import { Alert, LoadingState } from "@/components/ui";
import { useAnalysis } from "@/lib/use-analysis";
import {
  ACADEMIC_DOMAIN_OPTIONS,
  ASSIGNMENT_TYPE_OPTIONS,
  academicDomainLabel,
  assignmentTypeLabel,
  confidenceLabel,
  findingSeverityLabel,
  isExplicit,
  questionPriorityLabel,
  requirementCategoryLabel,
  scopeLevelLabel,
  sourceKindLabel,
  sourceKindShort,
} from "@/lib/format";
import type {
  AcademicDomain,
  AnalysisQuestion,
  AssignmentAnalysis,
  AssignmentType,
  Evidence,
  FindingSeverity,
  SpecializedAnalysis,
} from "@/lib/types";

/** Everything the AI asserts is tagged, so explicit facts are never confused with guesses. */
function OriginTag({ source }: { source: Evidence["source_type"] | string }) {
  return (
    <span
      data-testid="origin-tag"
      className="ms-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600"
    >
      {sourceKindShort(source as never)}
    </span>
  );
}

function ConfidenceTag({ confidence }: { confidence: number }) {
  return (
    <span
      data-testid="confidence"
      className="ms-1.5 text-xs text-slate-500"
      title={`Confidence ${confidence.toFixed(2)}`}
    >
      {confidenceLabel(confidence)}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 first:mt-0">
      <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return <li className="text-sm text-slate-700">{children}</li>;
}

/** One evidence entry, collapsed by default so provenance stays optional. */
function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) {
    return <p className="mt-1 text-xs text-slate-500">No supporting evidence recorded.</p>;
  }
  return (
    <ul className="mt-1 space-y-1">
      {evidence.map((item, index) => (
        <li key={index} className="text-xs text-slate-500">
          <span className="font-medium">{sourceKindLabel(item.source_type as never)}</span>
          {item.location ? ` · ${item.location}` : ""}
          {item.supports ? ` · ${item.supports}` : ""}
        </li>
      ))}
    </ul>
  );
}

const SEVERITY_TONE: Record<FindingSeverity, string> = {
  INFO: "border-slate-200 bg-slate-50 text-slate-700",
  WARNING: "border-amber-200 bg-amber-50 text-amber-800",
  IMPORTANT: "border-orange-200 bg-orange-50 text-orange-800",
  CRITICAL: "border-red-200 bg-red-50 text-red-800",
};

/**
 * The specialized payload is intentionally untyped, so only well-known keys are
 * rendered as a definition list and anything else falls back to plain text.
 */
function SpecializedSection({ item }: { item: SpecializedAnalysis }) {
  const rows = Object.entries(item.data).filter(([, value]) => value !== null && value !== undefined);
  return (
    <div
      key={item.analyzer}
      data-testid="specialized-analysis"
      className="mt-3 rounded border border-slate-200 bg-white p-3"
    >
      <p className="text-sm font-semibold text-slate-800">
        {item.analyzer.replace(/_/g, " ").toLowerCase()}
        <ConfidenceTag confidence={item.confidence} />
      </p>
      {item.summary ? <p className="mt-1 text-sm text-slate-700">{item.summary}</p> : null}
      {rows.length > 0 ? (
        <dl className="mt-2 space-y-1 text-xs text-slate-600">
          {rows.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="font-medium">{key.replace(/_/g, " ")}</dt>
              <dd className="flex-1">
                {Array.isArray(value) ? value.map(String).join(", ") || "—" : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function QuestionRow({
  question,
  busy,
  onAnswer,
  onDismiss,
}: {
  question: AnalysisQuestion;
  busy: boolean;
  onAnswer: (id: string, answer: string) => void;
  onDismiss: (id: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const settled = question.status !== "OPEN";

  return (
    <li data-testid="clarification-question" className="rounded border border-slate-200 p-3">
      <p className="text-sm font-medium text-slate-800">
        {question.code}. {question.question}
      </p>
      <p className="mt-1 text-xs text-slate-500">
        {questionPriorityLabel(question.priority)} priority
        {question.related_requirements.length > 0
          ? ` · affects ${question.related_requirements.join(", ")}`
          : ""}
        {settled ? ` · ${question.status.replace(/_/g, " ").toLowerCase()}` : ""}
      </p>
      {question.rationale ? (
        <p className="mt-1 text-xs text-slate-500">Why this matters: {question.rationale}</p>
      ) : null}
      {question.answer ? (
        <p className="mt-2 text-xs text-emerald-700">Your answer: {question.answer}</p>
      ) : null}
      {!settled ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            type="text"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Your answer…"
            aria-label={`Answer to ${question.code}`}
            className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button
            type="button"
            data-testid="answer-question"
            className="btn-secondary px-3 py-1 text-xs"
            disabled={busy || draft.trim().length === 0}
            onClick={() => onAnswer(question.id, draft.trim())}
          >
            Save answer
          </button>
          <button
            type="button"
            className="btn-ghost px-3 py-1 text-xs"
            disabled={busy}
            onClick={() => onDismiss(question.id)}
          >
            Dismiss
          </button>
        </div>
      ) : null}
    </li>
  );
}

/** Human review is the point of Phase 3, so correcting the AI is a first-class action. */
function ClassificationEditor({
  analysis,
  busy,
  onSetTypes,
  onSetDomains,
}: {
  analysis: AssignmentAnalysis;
  busy: boolean;
  onSetTypes: (types: AssignmentType[]) => void;
  onSetDomains: (domains: AcademicDomain[]) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [types, setTypes] = useState<AssignmentType[]>(analysis.assignment_types.map((t) => t.type));
  const [domains, setDomains] = useState<AcademicDomain[]>(
    analysis.academic_domains.map((d) => d.domain),
  );

  const toggle = <T,>(list: T[], value: T, set: (next: T[]) => void) => {
    set(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  };

  if (!editing) {
    return (
      <button
        type="button"
        data-testid="edit-classification"
        className="btn-ghost mt-2 text-xs"
        onClick={() => setEditing(true)}
      >
        Correct this classification
      </button>
    );
  }

  return (
    <div data-testid="classification-editor" className="mt-3 space-y-3 rounded border border-slate-200 p-3">
      <div>
        <p className="text-xs font-medium text-slate-600">Assignment type</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {ASSIGNMENT_TYPE_OPTIONS.map((type) => (
            <label key={type} className="flex items-center gap-1 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={types.includes(type)}
                disabled={busy}
                onChange={() => toggle(types, type, setTypes)}
              />
              {assignmentTypeLabel(type)}
            </label>
          ))}
        </div>
      </div>
      <div>
        <p className="text-xs font-medium text-slate-600">Academic domain</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {ACADEMIC_DOMAIN_OPTIONS.map((domain) => (
            <label key={domain} className="flex items-center gap-1 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={domains.includes(domain)}
                disabled={busy}
                onChange={() => toggle(domains, domain, setDomains)}
              />
              {academicDomainLabel(domain)}
            </label>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          data-testid="save-classification"
          className="btn-secondary px-3 py-1 text-xs"
          disabled={busy || (types.length === 0 && domains.length === 0)}
          onClick={() => {
            if (types.length > 0) onSetTypes(types);
            if (domains.length > 0) onSetDomains(domains);
            setEditing(false);
          }}
        >
          Save
        </button>
        <button
          type="button"
          className="btn-ghost px-3 py-1 text-xs"
          onClick={() => setEditing(false)}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function ReviewBar({
  analysis,
  busy,
  isReviewed,
  onAccept,
  onReject,
  onReanalyze,
}: {
  analysis: AssignmentAnalysis;
  busy: boolean;
  isReviewed: boolean;
  onAccept: (note: string) => void;
  onReject: (note: string) => void;
  onReanalyze: () => void;
}) {
  const [note, setNote] = useState("");

  if (analysis.is_stale) {
    return (
      <Alert tone="info">
        The assignment changed after this analysis was generated, so it is out of date.{" "}
        <button
          type="button"
          data-testid="reanalyze"
          className="underline"
          disabled={busy}
          onClick={onReanalyze}
        >
          Analyze again
        </button>
        . Your previous review stands until a new analysis replaces it.
      </Alert>
    );
  }

  if (isReviewed) {
    return (
      <Alert tone={analysis.status === "ACCEPTED" ? "success" : "info"}>
        You {analysis.status === "ACCEPTED" ? "accepted" : "rejected"} this analysis
        {analysis.reviewed_at ? ` on ${new Date(analysis.reviewed_at).toLocaleString()}` : ""}.
        {analysis.review_note ? ` “${analysis.review_note}”` : ""}{" "}
        <button
          type="button"
          data-testid="reanalyze"
          className="underline"
          disabled={busy}
          onClick={onReanalyze}
        >
          Analyze again
        </button>
        .
      </Alert>
    );
  }

  return (
    <div data-testid="review-bar" className="rounded border border-slate-200 bg-slate-50 p-3">
      <p className="text-sm text-slate-700">
        Review this before you plan anything. Accepting records that it matches your brief;
        rejecting keeps the analysis but marks it as not usable.
      </p>
      <input
        type="text"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Optional note"
        aria-label="Review note"
        className="mt-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
      />
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          data-testid="accept-analysis"
          className="btn-primary px-3 py-1 text-xs"
          disabled={busy}
          onClick={() => onAccept(note.trim())}
        >
          Accept analysis
        </button>
        <button
          type="button"
          data-testid="reject-analysis"
          className="btn-secondary px-3 py-1 text-xs"
          disabled={busy}
          onClick={() => onReject(note.trim())}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

/** Nothing to show yet: explain the action rather than a bare empty container. */
function NotAnalyzed({
  busy,
  onAnalyze,
}: {
  busy: boolean;
  onAnalyze: () => void;
}) {
  return (
    <section className="card p-6" id="analysis">
      <h2 className="section-title">Analysis</h2>
      <p className="mt-2 text-sm text-slate-600">
        Analysis reads your assignment specification, works out what is required and why, and
        shows you what is explicit, inferred, or still missing. It never changes your
        specification.
      </p>
      <button
        type="button"
        data-testid="analyze"
        className="btn-primary mt-4 px-4 py-2 text-sm"
        disabled={busy}
        onClick={onAnalyze}
      >
        {busy ? "Analyzing…" : "Analyze this assignment"}
      </button>
    </section>
  );
}

export function AnalysisPanel({
  assignmentId,
  refreshToken,
}: {
  assignmentId: string;
  refreshToken?: number | string;
}) {
  const {
    analysis,
    loading,
    busy,
    error,
    actionError,
    isReviewed,
    analyze,
    accept,
    reject,
    answerQuestion,
    dismissQuestion,
    setTypes,
    setDomains,
  } = useAnalysis(assignmentId, refreshToken);

  if (loading) {
    return <LoadingState label="Loading analysis" />;
  }

  if (error) {
    return <Alert tone="error">{error}</Alert>;
  }

  if (!analysis) {
    return <NotAnalyzed busy={busy} onAnalyze={() => analyze()} />;
  }

  const openQuestions = analysis.clarification_questions.filter((q) => q.status === "OPEN");
  const findings = [
    ...analysis.ambiguities.map((item) => ({ key: item.key, description: item.description, severity: item.severity, evidence: item.evidence, hint: item.suggested_clarification })),
    ...analysis.contradictions.map((item) => ({ key: item.key, description: item.description, severity: item.severity, evidence: item.evidence, hint: item.clarification_needed ? "Needs clarification" : null })),
    ...analysis.missing_information.map((item) => ({ key: item.key, description: item.description, severity: item.severity, evidence: item.evidence, hint: `Area: ${item.area}` })),
  ];

  return (
    <section className="card p-6" id="analysis">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="section-title">Analysis</h2>
        <p className="text-xs text-slate-500">
          {confidenceLabel(analysis.confidence)} confidence · v{analysis.analysis_version}
          {analysis.edited ? " · corrected" : ""}
        </p>
      </div>

      {actionError ? (
        <div className="mt-3">
          <Alert tone="error">{actionError}</Alert>
        </div>
      ) : null}

      <div className="mt-3">
        <ReviewBar
          analysis={analysis}
          busy={busy}
          isReviewed={isReviewed}
          onAccept={(note) => accept(note)}
          onReject={(note) => reject(note)}
          onReanalyze={() => analyze({ force: true })}
        />
      </div>

      {analysis.summary ? (
        <p data-testid="analysis-summary" className="mt-4 text-sm text-slate-700">
          {analysis.summary}
        </p>
      ) : null}

      {/* Classification */}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div>
          <p className="text-sm font-medium text-slate-600">Assignment type</p>
          <ul data-testid="classification-types" className="mt-1 space-y-1">
            {analysis.assignment_types.length === 0 ? (
              <li className="text-sm text-slate-500">Uncertain</li>
            ) : (
              analysis.assignment_types.map((item) => (
                <li key={item.type} className="text-sm text-slate-700">
                  {assignmentTypeLabel(item.type)}
                  <ConfidenceTag confidence={item.confidence} />
                  {item.source === "USER" ? <OriginTag source="USER_NOTE" /> : null}
                  {item.rationale ? (
                    <span className="block text-xs text-slate-500">{item.rationale}</span>
                  ) : null}
                </li>
              ))
            )}
          </ul>
        </div>
        <div>
          <p className="text-sm font-medium text-slate-600">Academic domain</p>
          <ul data-testid="classification-domains" className="mt-1 space-y-1">
            {analysis.academic_domains.length === 0 ? (
              <li className="text-sm text-slate-500">Uncertain</li>
            ) : (
              analysis.academic_domains.map((item) => (
                <li key={item.domain} className="text-sm text-slate-700">
                  {academicDomainLabel(item.domain)}
                  <ConfidenceTag confidence={item.confidence} />
                  {item.rationale ? (
                    <span className="block text-xs text-slate-500">{item.rationale}</span>
                  ) : null}
                </li>
              ))
            )}
          </ul>
        </div>
      </div>

      <ClassificationEditor
        analysis={analysis}
        busy={busy}
        onSetTypes={setTypes}
        onSetDomains={setDomains}
      />

      {analysis.objectives.length > 0 ? (
        <Section title="Objectives">
          <ul className="space-y-1">
            {analysis.objectives.map((objective, index) => (
              <Bullet key={index}>
                {objective.statement}
                <OriginTag source={objective.source} />
                <ConfidenceTag confidence={objective.confidence} />
              </Bullet>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.normalized_requirements.length > 0 ? (
        <Section title={`What you must do (${analysis.normalized_requirements.length} requirements)`}>
          <ul className="space-y-2">
            {analysis.normalized_requirements.map((requirement) => (
              <li
                key={requirement.key}
                data-testid="requirement"
                className="rounded border border-slate-200 p-2"
              >
                <p className="text-sm font-medium text-slate-800">
                  {requirement.key}. {requirement.title}
                </p>
                {requirement.description ? (
                  <p className="mt-0.5 text-sm text-slate-700">{requirement.description}</p>
                ) : null}
                <p className="mt-0.5 text-xs text-slate-500">
                  {requirementCategoryLabel(requirement.category)} ·{" "}
                  {requirement.priority.toLowerCase()} priority ·{" "}
                  {requirement.required ? "required" : "optional"}
                  {!isExplicit(requirement.source) ? <OriginTag source={requirement.source} /> : null}
                  <ConfidenceTag confidence={requirement.confidence} />
                </p>
                <EvidenceList evidence={requirement.evidence} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.constraints.length > 0 ? (
        <Section title="Constraints from your brief">
          <ul className="space-y-1">
            {analysis.constraints.map((constraint) => (
              <Bullet key={constraint.id}>
                {constraint.title}
                {constraint.value ? `: ${constraint.value}` : ""}
                <span className="ms-1 text-xs text-slate-500">
                  ({constraint.severity.toLowerCase()} {constraint.type.toLowerCase().replace(/_/g, " ")})
                </span>
              </Bullet>
            ))}
          </ul>
        </Section>
      ) : null}

      {findings.length > 0 ? (
        <Section title="What needs your attention">
          <ul className="space-y-2">
            {findings.map((finding) => (
              <li
                key={finding.key}
                data-testid="finding"
                className={`rounded border p-2 text-sm ${SEVERITY_TONE[finding.severity]}`}
              >
                <p className="font-medium">
                  {finding.description}
                  <span className="ms-2 text-xs font-normal">
                    {findingSeverityLabel(finding.severity)}
                  </span>
                </p>
                {finding.hint ? (
                  <p className="mt-0.5 text-xs opacity-80">{finding.hint}</p>
                ) : null}
                <EvidenceList evidence={finding.evidence} />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.risks.length > 0 ? (
        <Section title="Risks">
          <ul className="space-y-1">
            {analysis.risks.map((risk) => (
              <Bullet key={risk.key}>
                {risk.description}
                <span className="ms-1 text-xs text-slate-500">
                  {findingSeverityLabel(risk.severity)} · {risk.affected_area}
                </span>
                {risk.mitigation_hint ? (
                  <span className="block text-xs text-slate-500">{risk.mitigation_hint}</span>
                ) : null}
              </Bullet>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.assumptions.length > 0 ? (
        <Section title="Assumptions this analysis made">
          <ul className="space-y-1">
            {analysis.assumptions.map((assumption) => (
              <Bullet key={assumption.key}>
                {assumption.statement}
                <ConfidenceTag confidence={assumption.confidence} />
                <EvidenceList evidence={assumption.evidence} />
              </Bullet>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.clarification_questions.length > 0 ? (
        <Section
          title={
            openQuestions.length > 0
              ? `Questions only you can answer (${openQuestions.length} open)`
              : "Clarification questions"
          }
        >
          <ul className="space-y-2">
            {analysis.clarification_questions.map((question) => (
              <QuestionRow
                key={question.id}
                question={question}
                busy={busy}
                onAnswer={answerQuestion}
                onDismiss={dismissQuestion}
              />
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.deliverables.length > 0 ? (
        <Section title="What you will hand in">
          <ul className="space-y-2">
            {analysis.deliverables.map((deliverable) => (
              <li
                key={deliverable.key}
                data-testid="deliverable"
                className="rounded border border-slate-200 p-2"
              >
                <p className="text-sm font-medium text-slate-800">
                  {deliverable.title}
                  {deliverable.format ? (
                    <span className="ms-2 text-xs font-normal text-slate-500">
                      {deliverable.format}
                    </span>
                  ) : null}
                </p>
                {deliverable.description ? (
                  <p className="mt-0.5 text-sm text-slate-700">{deliverable.description}</p>
                ) : null}
                <p className="mt-0.5 text-xs text-slate-500">
                  {deliverable.required === null
                    ? "Whether it is required is unknown"
                    : deliverable.required
                      ? "Required"
                      : "Optional"}
                  {" · "}source: {sourceKindLabel(deliverable.uncertainty)}
                  {deliverable.expected_content.length > 0
                    ? ` · expects: ${deliverable.expected_content.join(", ")}`
                    : ""}
                  <ConfidenceTag confidence={deliverable.confidence} />
                </p>
                {deliverable.verification_needs.length > 0 ? (
                  <p className="mt-0.5 text-xs text-slate-500">
                    To verify: {deliverable.verification_needs.join(", ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.evaluation.criteria.length > 0 || analysis.evaluation.implied_quality_expectations.length > 0 ? (
        <Section title="How it will be judged">
          {analysis.evaluation.rubric_available ? (
            <p className="text-sm text-slate-700">A rubric was provided in your brief.</p>
          ) : (
            <p className="text-sm text-slate-700">
              No rubric was provided, so these expectations are inferred and you should confirm
              them with your instructor.
            </p>
          )}
          {analysis.evaluation.criteria.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {analysis.evaluation.criteria.map((criterion, index) => (
                <Bullet key={index}>
                  {criterion.title}
                  {criterion.weight ? ` (${criterion.weight})` : ""}
                  {criterion.implied ? (
                    <OriginTag source="AI_INFERENCE" />
                  ) : null}
                  {criterion.description ? (
                    <span className="block text-xs text-slate-500">{criterion.description}</span>
                  ) : null}
                </Bullet>
              ))}
            </ul>
          ) : null}
          {analysis.evaluation.implied_quality_expectations.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {analysis.evaluation.implied_quality_expectations.map((expectation, index) => (
                <Bullet key={index}>
                  {expectation}
                  <OriginTag source="AI_INFERENCE" />
                </Bullet>
              ))}
            </ul>
          ) : null}
          {analysis.evaluation.missing_rubric_information.length > 0 ? (
            <p className="mt-2 text-xs text-amber-700">
              Still unknown: {analysis.evaluation.missing_rubric_information.join(", ")}
            </p>
          ) : null}
        </Section>
      ) : null}

      {analysis.scope.overall !== "UNKNOWN" ? (
        <Section title="Scope">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <dt className="text-slate-600">Breadth</dt>
            <dd className="text-slate-800">{scopeLevelLabel(analysis.scope.breadth.level)}</dd>
            <dt className="text-slate-600">Depth</dt>
            <dd className="text-slate-800">{scopeLevelLabel(analysis.scope.depth.level)}</dd>
            <dt className="text-slate-600">Research</dt>
            <dd className="text-slate-800">
              {scopeLevelLabel(analysis.scope.research_intensity.level)}
            </dd>
            <dt className="text-slate-600">Writing</dt>
            <dd className="text-slate-800">
              {scopeLevelLabel(analysis.scope.writing_intensity.level)}
            </dd>
            <dt className="text-slate-600">Overall</dt>
            <dd className="text-slate-800">{scopeLevelLabel(analysis.scope.overall)}</dd>
            <dt className="text-slate-600">Requirements</dt>
            <dd className="text-slate-800">{analysis.scope.requirement_count}</dd>
            <dt className="text-slate-600">Deliverables</dt>
            <dd className="text-slate-800">{analysis.scope.deliverable_count}</dd>
          </dl>
        </Section>
      ) : null}

      {analysis.work_areas.length > 0 ? (
        <Section title="Areas of work">
          <ul className="space-y-1">
            {analysis.work_areas.map((area) => (
              <Bullet key={area.key}>
                {area.title}
                <span className="ms-1 text-xs text-slate-500">
                  {requirementCategoryLabel(area.category)} · {sourceKindLabel(area.origin)}
                </span>
                {area.description ? (
                  <span className="block text-xs text-slate-500">{area.description}</span>
                ) : null}
              </Bullet>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.dependencies.length > 0 ? (
        <Section title="Ordering">
          <ul className="space-y-1">
            {analysis.dependencies.map((dependency, index) => (
              <Bullet key={index}>
                {dependency.predecessor} must come before {dependency.successor}
                <span className="ms-1 text-xs text-slate-500">({dependency.kind})</span>
              </Bullet>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.verification.items.length > 0 ? (
        <Section title="How you should check your work">
          <ul className="space-y-1">
            {analysis.verification.items.map((item, index) => (
              <Bullet key={index}>
                {item.title}
                <span className="ms-1 text-xs text-slate-500">via {item.method}</span>
                {item.description ? (
                  <span className="block text-xs text-slate-500">{item.description}</span>
                ) : null}
              </Bullet>
            ))}
          </ul>
        </Section>
      ) : null}

      {analysis.specialized_analysis.length > 0 ? (
        <Section title="Domain-specific analysis">
          {analysis.specialized_analysis.map((item) => (
            <SpecializedSection key={item.analyzer} item={item} />
          ))}
        </Section>
      ) : null}

      <p className="mt-6 text-xs text-slate-400">
        Analysis is generated, not authoritative. Your specification stays the source of truth,
        and {analysis.provider}
        {analysis.model ? `/${analysis.model}` : ""} produced this with prompt{" "}
        {analysis.prompt_version}.
      </p>
    </section>
  );
}
