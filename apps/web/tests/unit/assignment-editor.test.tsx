import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssignmentDetail } from "@/components/assignment-detail";
import type {
  AssignmentSpecification,
  CompletenessCheck,
  Course,
  DependencyGraph,
  ReadinessReport,
} from "@/lib/types";

const { router } = vi.hoisted(() => ({
  router: { push: vi.fn(), refresh: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

const BASE_URL = "http://localhost:8000/api/v1";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function check(field: string, label: string, status: CompletenessCheck["status"]): CompletenessCheck {
  return { field, label, status, message: `${label} message`, weight: 10, blocking: status === "FAIL" };
}

function report(overrides: Partial<ReadinessReport> = {}): ReadinessReport {
  return {
    score: 100,
    is_complete: true,
    is_ready_for_analysis: true,
    completeness_bar: 90,
    failing_checks: [],
    warning_checks: [],
    checks: [
      check("title", "Title", "PASS"),
      check("description", "Description", "PASS"),
      check("deadline", "Deadline", "PASS"),
      check("requirements", "Requirements", "PASS"),
      check("evaluation_criteria", "Evaluation criteria", "PASS"),
      check("course", "Course", "PASS"),
      check("constraints", "Constraints", "WARNING"),
      check("deliverables", "Deliverables", "WARNING"),
      check("technologies", "Technologies", "WARNING"),
      check("resources", "Resources", "WARNING"),
    ],
    ...overrides,
  };
}

function specification(overrides: Partial<AssignmentSpecification> = {}): AssignmentSpecification {
  return {
    assignment: {
      id: "a1",
      title: "Build a Java Strategy Game",
      deadline: "2026-12-01T17:00:00Z",
      status: "DRAFT",
      course_id: "c1",
      course_name: "Advanced Programming",
      course_code: "AP140",
    },
    description: "Create a small strategy game with tests.",
    criteria_total: "100.00",
    requirements: [
      {
        id: "r1",
        assignment_id: "a1",
        code: "REQ-001",
        sequence: 1,
        title: "Implement authentication",
        description: "Users can register and sign in.",
        priority: "HIGH",
        type: "FUNCTIONAL",
        status: "TODO",
        is_required: true,
        position: 0,
        parent_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
    constraints: [],
    evaluation_criteria: [],
    deliverables: [],
    technologies: [],
    tags: [],
    resources: [],
    readiness: report(),
    summary: {
      assignment: {
        id: "a1",
        title: "Build a Java Strategy Game",
        deadline: "2026-12-01T17:00:00Z",
        status: "DRAFT",
        course_id: "c1",
        course_name: "Advanced Programming",
        course_code: "AP140",
      },
      requirements_total: 1,
      requirements_required: 1,
      requirements_completed: 0,
      requirements_verified: 0,
      requirements_by_status: { TODO: 1 },
      critical_requirements: 0,
      constraints_total: 0,
      constraints_by_severity: {},
      criteria_total: "100.00",
      criteria_count: 0,
      criteria_balanced: true,
      deliverables_total: 0,
      deliverables_completed: 0,
      technologies: [],
      tags: [],
      resources_total: 0,
      readiness: "DRAFT",
      readiness_score: 100,
      specification_version: 1,
    },
    specification_version: 1,
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const graph: DependencyGraph = {
  nodes: [],
  edges: [],
  execution_order: [],
  has_cycles: false,
};

const course: Course = {
  id: "c1",
  workspace_id: "w1",
  name: "Advanced Programming",
  code: "AP140",
  description: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  assignment_count: 1,
};

/** Routes the fake server by method and path so each test states only what it needs. */
function route(routes: Record<string, () => Response>) {
  fetchMock.mockImplementation((input, init) => {
    const url = String(input).replace(BASE_URL, "");
    const method = init?.method ?? "GET";
    const key = `${method} ${url.split("?")[0]}`;
    const handler = routes[key];
    if (!handler) {
      return Promise.reject(new Error(`unrouted request: ${key}`));
    }
    return Promise.resolve(handler());
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AssignmentDetail", () => {
  it("renders the specification from a single request", async () => {
    route({
      "GET /assignments/a1/specification": () => jsonResponse(specification()),
      "GET /assignments/a1/requirements/dependency-graph": () => jsonResponse(graph),
      "GET /courses": () => jsonResponse([course]),
      "GET /assignments/a1/activity": () =>
        jsonResponse({ items: [], page: { page: 1, page_size: 20, total: 0, pages: 0 } }),
    });

    render(<AssignmentDetail assignmentId="a1" />);

    expect(
      await screen.findByRole("heading", { name: "Build a Java Strategy Game" }),
    ).toBeInTheDocument();
    expect(await screen.findByTestId("requirements-section")).toHaveTextContent("REQ-001");
    expect(await screen.findByTestId("readiness-panel")).toHaveTextContent("100%");
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/assignments/a1/specification`,
      expect.anything(),
    );
  });

  it("blocks the readiness action while a blocking check fails", async () => {
    const blocked = specification({
      readiness: report({
        score: 40,
        is_complete: false,
        is_ready_for_analysis: false,
        failing_checks: ["description"],
        checks: [
          check("title", "Title", "PASS"),
          check("description", "Description", "FAIL"),
          check("requirements", "Requirements", "PASS"),
        ],
      }),
    });
    route({
      "GET /assignments/a1/specification": () => jsonResponse(blocked),
      "GET /assignments/a1/requirements/dependency-graph": () => jsonResponse(graph),
      "GET /courses": () => jsonResponse([course]),
      "GET /assignments/a1/activity": () =>
        jsonResponse({ items: [], page: { page: 1, page_size: 20, total: 0, pages: 0 } }),
    });

    render(<AssignmentDetail assignmentId="a1" />);

    const panel = await screen.findByTestId("readiness-panel");
    const button = await within(panel).findByRole("button", { name: "Mark ready for analysis" });
    expect(button).toBeDisabled();
    expect(panel).toHaveTextContent("Description");
    expect(panel).toHaveTextContent("cannot be marked ready");
  });

  it("marks the assignment ready and refreshes the specification", async () => {
    const draft = specification();
    const ready = specification();
    ready.assignment.status = "READY_FOR_ANALYSIS";
    let marks = 0;
    route({
      // The refreshed read reflects the new state, which is what the user sees next.
      "GET /assignments/a1/specification": () => jsonResponse(marks > 0 ? ready : draft),
      "GET /assignments/a1/requirements/dependency-graph": () => jsonResponse(graph),
      "GET /courses": () => jsonResponse([course]),
      "GET /assignments/a1/activity": () =>
        jsonResponse({ items: [], page: { page: 1, page_size: 20, total: 0, pages: 0 } }),
      "POST /assignments/a1/readiness/mark-ready": () => {
        marks += 1;
        return jsonResponse({
          ...draft.assignment,
          status: "READY_FOR_ANALYSIS",
          readiness_score: 100,
        });
      },
    });

    render(<AssignmentDetail assignmentId="a1" />);

    const panel = await screen.findByTestId("readiness-panel");
    fireEvent.click(await within(panel).findByRole("button", { name: "Mark ready for analysis" }));

    await waitFor(() => expect(marks).toBe(1));
    expect(await within(panel).findByText("Marked ready for analysis (100%).")).toBeInTheDocument();
    expect(await within(panel).findByRole("button", { name: "Reopen for editing" })).toBeEnabled();
  });

  it("adds a requirement and re-reads the specification", async () => {
    let posts = 0;
    route({
      "GET /assignments/a1/specification": () => jsonResponse(specification()),
      "GET /assignments/a1/requirements/dependency-graph": () => jsonResponse(graph),
      "GET /courses": () => jsonResponse([course]),
      "GET /assignments/a1/activity": () =>
        jsonResponse({ items: [], page: { page: 1, page_size: 20, total: 0, pages: 0 } }),
      "POST /assignments/a1/requirements": (): Response => {
        posts += 1;
        return jsonResponse({ id: "r2" }, 201);
      },
    });

    render(<AssignmentDetail assignmentId="a1" />);

    const section = await screen.findByTestId("requirements-section");
    fireEvent.change(within(section).getByLabelText("Title"), {
      target: { value: "Write the AI heuristic" },
    });
    fireEvent.click(within(section).getByRole("button", { name: "Add requirement" }));

    await waitFor(() => expect(posts).toBe(1));
  });

  it("shows the server message when the assignment is not visible", async () => {
    route({
      "GET /assignments/a1/specification": () =>
        jsonResponse({ error: { code: "NOT_FOUND", message: "Assignment not found." } }, 404),
    });

    render(<AssignmentDetail assignmentId="a1" />);

    expect(await screen.findByText("Assignment not found.")).toBeInTheDocument();
  });
});
