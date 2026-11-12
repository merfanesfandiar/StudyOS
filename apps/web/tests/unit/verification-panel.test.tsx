import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VerificationPanel } from "@/components/assignment/verification-panel";
import type { VerificationReport } from "@/lib/verification-types";
import { renderWithPreferences } from "./render";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function report(overrides: Partial<VerificationReport> = {}): VerificationReport {
  return {
    id: "r1",
    assignment_id: "a1",
    status: "COMPLETED",
    scope_kind: "FULL",
    trigger: "MANUAL",
    verdict: "FAILED",
    completion_percentage: 50,
    created_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    previous_run_id: null,
    summary: { limitations: ["No network access: DOI resolution skipped."], rubric: { weighted_total: 0.5, ambiguities: [] } },
    findings: [
      {
        id: "f1",
        validator: "mathematics",
        level: "DOMAIN",
        severity: "CRITICAL",
        title: "Incorrect arithmetic: 2+2 = 5",
        description: "Recomputation gives 4.",
        recommendation: "Correct to 4.",
        requirement_codes: ["REQ-001"],
        artifact_ids: [],
        heuristic: false,
      },
    ],
    evidence: [],
    requirements: [
      {
        requirement_id: "q1",
        code: "REQ-001",
        status: "FAILED",
        explanation: "Not traceable.",
      },
    ],
    rubric: [],
    comparison: null,
    ...overrides,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("VerificationPanel", () => {
  it("renders the verdict, requirement statuses and findings of the latest report", async () => {
    fetchMock.mockImplementation((url) => {
      const path = String(url);
      if (path.includes("/verification?")) {
        return Promise.resolve(
          jsonResponse({ items: [{ id: "r1", status: "COMPLETED" }], total: 1 }),
        );
      }
      if (path.endsWith("/verification/r1")) {
        return Promise.resolve(jsonResponse(report()));
      }
      return Promise.resolve(jsonResponse({}, 404));
    });

    renderWithPreferences(<VerificationPanel assignmentId="a1" />);

    await waitFor(() => {
      expect(screen.getByTestId("verification-panel")).toBeTruthy();
    });
    expect(screen.getByTestId("verification-verdict").textContent).toContain("FAILED");
    expect(screen.getByTestId("verification-requirements").textContent).toContain("REQ-001");
    expect(screen.getByTestId("verification-findings").textContent).toContain("Incorrect arithmetic");
    // Honesty rule rendered, not hidden.
    expect(screen.getByTestId("verification-verdict").textContent).toContain("not an instructor grade");
  });

  it("shows the empty state when there are no runs", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ items: [], total: 0 })),
    );
    renderWithPreferences(<VerificationPanel assignmentId="a1" />);
    await waitFor(() => {
      expect(screen.getByTestId("verification-panel").textContent).toContain("No verification yet");
    });
  });
});
