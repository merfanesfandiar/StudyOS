import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnalysisPanel } from "@/components/assignment/analysis-panel";
import type {
  AnalysisQuestion,
  AssignmentAnalysis,
  Evidence,
  NormalizedRequirement,
} from "@/lib/types";

const { router } = vi.hoisted(() => ({
  router: { push: vi.fn(), refresh: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const NOT_ANALYZED = {
  error: { code: "ANALYSIS_NOT_FOUND", message: "This assignment has not been analyzed yet." },
};

function evidence(supports: string): Evidence {
  return {
    source_type: "DESCRIPTION",
    source_id: null,
    location: "description",
    excerpt_reference: null,
    supports,
    confidence: 0.9,
  };
}

function question(overrides: Partial<AnalysisQuestion> = {}): AnalysisQuestion {
  return {
    id: "q-1",
    code: "Q1",
    priority: "IMPORTANT",
    status: "OPEN",
    question: "How many proof styles are acceptable?",
    rationale: "This changes how much work this is.",
    related_requirements: ["R1"],
    answer: null,
    answered_at: null,
    position: 0,
    ...overrides,
  };
}

function requirement(overrides: Partial<NormalizedRequirement> = {}): NormalizedRequirement {
  return {
    key: "R1",
    title: "State the hypotheses explicitly",
    description: "Every theorem must name its assumptions.",
    category: "CONTENT",
    priority: "HIGH",
    required: true,
    source: "EXPLICIT",
    source_reference: "REQ-001",
    confidence: 0.95,
    evidence: [evidence("state the hypotheses explicitly")],
    ...overrides,
  };
}

function analysis(overrides: Partial<AssignmentAnalysis> = {}): AssignmentAnalysis {
  return {
    id: "an-1",
    assignment_id: "as-1",
    analysis_version: 1,
    specification_version: 1,
    specification_hash: "hash",
    prompt_version: "assignment_analyzer_v1",
    provider: "mock",
    model: "heuristic-v1",
    status: "PENDING",
    is_stale: false,
    stale_at: null,
    summary: "A proof exercise that rewards careful use of the monotone convergence theorem.",
    confidence: 0.82,
    assignment_types: [
      { type: "MATHEMATICAL_PROOF", confidence: 0.91, source: "AI", rationale: "Asks to prove a theorem." },
    ],
    academic_domains: [
      { domain: "MATHEMATICS", confidence: 0.95, source: "AI", rationale: "Convergence of sequences." },
    ],
    objectives: [
      { statement: "Justify each step of the proof.", source: "INFERENCE", confidence: 0.7 },
    ],
    normalized_requirements: [requirement()],
    constraints: [],
    ambiguities: [
      {
        key: "A1",
        description: "The word 'rigorous' is never defined.",
        severity: "WARNING",
        affected_requirements: ["R1"],
        evidence: [evidence("rigorous proofs")],
        suggested_clarification: "Ask whether measure-theoretic rigour is expected.",
        confidence: 0.75,
      },
    ],
    contradictions: [],
    missing_information: [
      {
        key: "M1",
        description: "No page limit is given.",
        area: "formatting",
        severity: "INFO",
        evidence: [],
        confidence: 0.6,
      },
    ],
    assumptions: [],
    clarification_questions: [question()],
    deliverables: [
      {
        key: "D1",
        title: "Written proof",
        description: null,
        required: true,
        expected_content: ["Full derivation"],
        format: "PDF",
        related_requirements: ["R1"],
        verification_needs: ["Re-read each inference"],
        depends_on: [],
        uncertainty: "INFERENCE",
        evidence: [],
        confidence: 0.8,
      },
    ],
    evaluation: {
      rubric_available: false,
      criteria: [
        {
          title: "Correct use of the theorem",
          description: null,
          weight: "40%",
          related_requirements: ["R1"],
          implied: true,
          confidence: 0.7,
        },
      ],
      implied_quality_expectations: ["No unjustified steps"],
      missing_rubric_information: ["Marking scheme not supplied"],
      confidence: 0.6,
    },
    scope: {
      breadth: { level: "LOW", rationale: null },
      depth: { level: "HIGH", rationale: null },
      research_intensity: { level: "NOT_APPLICABLE", rationale: null },
      reasoning_intensity: { level: "HIGH", rationale: null },
      technical_complexity: { level: "MEDIUM", rationale: null },
      writing_intensity: { level: "MEDIUM", rationale: null },
      experimental_complexity: { level: "NOT_APPLICABLE", rationale: null },
      presentation_complexity: { level: "LOW", rationale: null },
      dependency_complexity: { level: "NOT_APPLICABLE", rationale: null },
      deliverable_count: 1,
      requirement_count: 1,
      overall: "MEDIUM",
      confidence: 0.7,
    },
    work_areas: [
      {
        key: "W1",
        title: "Set up the hypotheses",
        description: null,
        category: "CONTENT",
        related_requirements: ["R1"],
        depends_on: [],
        origin: "EXPLICIT",
        confidence: 0.8,
      },
    ],
    resources: { resources: [], notes: [], confidence: 0.5 },
    dependencies: [],
    verification: {
      items: [
        {
          title: "Check every inference",
          description: null,
          method: "manual review",
          applies_to: ["D1"],
          confidence: 0.7,
        },
      ],
      notes: [],
      confidence: 0.7,
    },
    risks: [
      {
        key: "K1",
        description: "Dropping monotonicity makes the statement false.",
        severity: "CRITICAL",
        affected_area: "correctness",
        evidence: [],
        mitigation_hint: "Check the hypothesis is used.",
        confidence: 0.85,
      },
    ],
    specialized_analysis: [
      {
        analyzer: "mathematics",
        assignment_types: ["MATHEMATICAL_PROOF"],
        data: { key_theorems: ["monotone convergence theorem"], proof_methods: ["epsilon-N"] },
        summary: "Requires a named theorem rather than a citation.",
        confidence: 0.8,
      },
    ],
    evidence: [],
    edited: false,
    reviewed_at: null,
    review_note: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as AssignmentAnalysis;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AnalysisPanel", () => {
  it("offers to analyze an assignment that has never been analyzed", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(NOT_ANALYZED, 404));

    render(<AnalysisPanel assignmentId="as-1" />);

    expect(await screen.findByTestId("analyze")).toBeEnabled();
    expect(screen.getByText(/never changes your specification/i)).toBeInTheDocument();
  });

  it("runs the analysis and renders the result", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(NOT_ANALYZED, 404))
      .mockResolvedValueOnce(jsonResponse(analysis(), 201));

    render(<AnalysisPanel assignmentId="as-1" />);
    fireEvent.click(await screen.findByTestId("analyze"));

    expect(await screen.findByTestId("analysis-summary")).toHaveTextContent(
      /monotone convergence theorem/i,
    );
    // Universal classification, not programming-centric.
    expect(within(screen.getByTestId("classification-types")).getByText(/mathematical proof/i))
      .toBeInTheDocument();
    expect(within(screen.getByTestId("classification-domains")).getByText(/mathematics/i))
      .toBeInTheDocument();
    expect(screen.getAllByTestId("requirement").length).toBe(1);
    expect(screen.getByTestId("deliverable")).toHaveTextContent(/written proof/i);
    expect(screen.getByTestId("specialized-analysis")).toHaveTextContent(/key theorems/i);
    // §45: explicit, inferred, uncertain and missing must be visibly distinct.
    expect(screen.getByText(/inferred and you should confirm/i)).toBeInTheDocument();
    expect(screen.getByText(/dropping monotonicity/i)).toBeInTheDocument();
  });

  it("surfaces a load failure without pretending the assignment is unanalyzed", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ error: { code: "ASSIGNMENT_NOT_FOUND", message: "Not found." } }, 404),
    );

    render(<AnalysisPanel assignmentId="as-1" />);

    expect(await screen.findByText("Not found.")).toBeInTheDocument();
    expect(screen.queryByTestId("analyze")).not.toBeInTheDocument();
  });

  it("lets the student accept the analysis and shows the recorded decision", async () => {
    const accepted = analysis({
      status: "ACCEPTED",
      reviewed_at: "2026-02-02T10:00:00Z",
      review_note: "Matches the sheet I was given.",
    });
    fetchMock
      .mockResolvedValueOnce(jsonResponse(analysis()))
      .mockResolvedValueOnce(jsonResponse(accepted));

    render(<AnalysisPanel assignmentId="as-1" />);
    fireEvent.click(await screen.findByTestId("accept-analysis"));

    expect(await screen.findByText(/You accepted this analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/Matches the sheet I was given/)).toBeInTheDocument();
    expect(screen.queryByTestId("review-bar")).not.toBeInTheDocument();
  });

  it("records a rejection instead of silently discarding the analysis", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(analysis()))
      .mockResolvedValueOnce(jsonResponse(analysis({ status: "REJECTED" })));

    render(<AnalysisPanel assignmentId="as-1" />);
    fireEvent.click(await screen.findByTestId("reject-analysis"));

    expect(await screen.findByText(/You rejected this analysis/i)).toBeInTheDocument();
    // The analysis itself is still visible so the student can reconsider.
    expect(screen.getByTestId("analysis-summary")).toBeInTheDocument();
  });

  it("surfaces an action failure without losing the current analysis", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(analysis()))
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "ANALYSIS_ALREADY_RUNNING", message: "Already running." } }, 409),
      );

    render(<AnalysisPanel assignmentId="as-1" />);
    fireEvent.click(await screen.findByTestId("accept-analysis"));

    expect(await screen.findByText("Already running.")).toBeInTheDocument();
    expect(screen.getByTestId("analysis-summary")).toBeInTheDocument();
  });

  it("answers a clarification question through the API", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(analysis()))
      .mockResolvedValueOnce(
        jsonResponse(
          analysis({
            clarification_questions: [
              question({ status: "ANSWERED", answer: "Epsilon-N only.", answered_at: "2026-02-02T00:00:00Z" }),
            ],
          }),
        ),
      );

    render(<AnalysisPanel assignmentId="as-1" />);
    const input = await screen.findByLabelText("Answer to Q1");
    fireEvent.change(input, { target: { value: "Epsilon-N only." } });
    fireEvent.click(screen.getByTestId("answer-question"));

    expect(await screen.findByText(/Your answer: Epsilon-N only/)).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((call) => String(call[0]).includes("questions/q-1/answer")),
      ).toBe(true),
    );
    expect(
      fetchMock.mock.calls.find((call) => String(call[0]).includes("questions/q-1/answer"))?.[1]
        ?.body,
    ).toContain("Epsilon-N only.");
  });

  it("warns that a stale analysis must be regenerated before use", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(analysis({ is_stale: true, stale_at: "2026-02-03T00:00:00Z" })),
    );

    render(<AnalysisPanel assignmentId="as-1" />);

    expect(await screen.findByText(/out of date/i)).toBeInTheDocument();
    expect(screen.getByTestId("reanalyze")).toBeEnabled();
  });

  it("lets the student correct the classification, which marks it as their edit", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(analysis()))
      .mockResolvedValueOnce(jsonResponse(analysis({ edited: true })));

    render(<AnalysisPanel assignmentId="as-1" />);
    fireEvent.click(await screen.findByTestId("edit-classification"));

    const editor = screen.getByTestId("classification-editor");
    fireEvent.click(within(editor).getByLabelText(/research/i));
    fireEvent.click(screen.getByTestId("save-classification"));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((call) => String(call[1]?.body ?? "").includes('"RESEARCH"')),
      ).toBe(true),
    );
    expect(await screen.findByText(/corrected/i)).toBeInTheDocument();
  });

  it("reloads when the specification version changes, so staleness appears", async () => {
    // Editing the brief bumps the specification version. Without reloading on
    // that change the panel kept showing the old analysis as fresh.
    fetchMock.mockResolvedValueOnce(jsonResponse(analysis()));

    const { rerender } = render(<AnalysisPanel assignmentId="as-1" refreshToken={4} />);
    expect(await screen.findByTestId("analysis-summary")).toBeInTheDocument();

    fetchMock.mockResolvedValueOnce(jsonResponse(analysis({ is_stale: true })));
    rerender(<AnalysisPanel assignmentId="as-1" refreshToken={5} />);

    expect(await screen.findByTestId("reanalyze")).toBeInTheDocument();
    expect(screen.getByText(/out of date/i)).toBeInTheDocument();
  });
});
