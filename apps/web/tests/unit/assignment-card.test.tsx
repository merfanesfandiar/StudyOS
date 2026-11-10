import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AssignmentCard } from "@/components/assignment-card";
import type { AssignmentListItem } from "@/lib/types";
import { renderWithPreferences } from "./render";

function assignment(overrides: Partial<AssignmentListItem> = {}): AssignmentListItem {
  return {
    id: "a1",
    title: "Prove monotone convergence",
    deadline: "2026-11-15T23:59:00Z",
    status: "ANALYZED",
    course_id: "c1",
    course_name: "Real Analysis",
    course_code: "MATH201",
    description: null,
    readiness_score: 48,
    readiness_state: "DRAFT",
    requirements_count: 4,
    completed_requirements_count: 1,
    criteria_total: "0.00",
    deadline_state: "upcoming",
    updated_at: "2026-11-01T10:00:00Z",
    ...overrides,
  };
}

describe("AssignmentCard", () => {
  /**
   * `readiness_score` is already a percentage (0-100), not a fraction. Passing
   * it to `Intl.NumberFormat` with `style: "percent"` multiplied it by 100, so a
   * half-ready assignment rendered "4,800% ready" on the dashboard.
   */
  it("renders the readiness score as a percentage, not a fraction of a percent", () => {
    renderWithPreferences(<AssignmentCard assignment={assignment()} />);

    expect(screen.getByText(/48%/)).toBeInTheDocument();
    expect(screen.queryByText(/4,800%/)).not.toBeInTheDocument();
  });
});
