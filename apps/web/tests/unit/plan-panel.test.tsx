import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PlanPanel } from "@/components/planning/plan-panel";
import { PreferencesProvider } from "@/components/preferences-provider";
import type { PlanTask, WorkPlan } from "@/lib/planning-types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/assignments/a1",
}));

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function page<T>(items: T[]) {
  return { items, page: { page: 1, page_size: 20, total: items.length, pages: 1 } };
}

function task(overrides: Partial<PlanTask> = {}): PlanTask {
  return {
    id: "t1",
    key: "T1",
    title: "Read the brief",
    description: "Read the assignment brief end to end.",
    type: "READ",
    status: "PENDING",
    priority: "HIGH",
    position: 0,
    estimated_effort: "LOW",
    min_minutes: 45,
    max_minutes: 90,
    verification_method: null,
    acceptance_criteria: ["Can summarise the ask"],
    resources: [],
    notes: null,
    is_user_authored: false,
    depends_on: [],
    related_requirements: ["R1"],
    related_deliverables: [],
    blocked_by: [],
    ...overrides,
  };
}

function plan(overrides: Partial<WorkPlan> = {}): WorkPlan {
  return {
    id: "p1",
    assignment_id: "a1",
    analysis_id: "an1",
    version: 1,
    trigger: "GENERATED",
    reason: "",
    changed_sections: null,
    title: "Research report plan",
    summary: "Four tasks across two milestones.",
    status: "READY_FOR_REVIEW",
    objectives: ["Argue a position"],
    estimated_effort: "MEDIUM",
    min_minutes: 240,
    max_minutes: 480,
    is_stale: false,
    approved_at: null,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    tasks: [task()],
    milestones: [
      {
        id: "m1",
        key: "M1",
        title: "Understand",
        description: null,
        position: 0,
        status: "PENDING",
        task_keys: ["T1"],
        completed_task_count: 0,
        task_count: 1,
      },
    ],
    verification_points: [],
    risks: [],
    schedule_risk: {
      level: "MEDIUM",
      estimated_minutes: 480,
      available_minutes: 300,
      is_overcommitted: true,
      summary: "6 to 8 estimated hours against 5 hours remaining.",
      factors: ["2 requirements"],
    },
    progress_percentage: 0,
    validation_warnings: [],
    used_fallback: false,
    rejection_reasons: [],
    ...overrides,
  };
}

/** Route fetches by method and path so a test only declares what it cares about. */
function route(handlers: Record<string, () => Response | Promise<Response>>) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const key = `${method} ${url.replace(/^https?:\/\/[^/]+/, "")}`;
    const handler = handlers[key];
    if (!handler) {
      return jsonResponse({ error: { code: "NOT_FOUND", message: `no route for ${key}` } }, 404);
    }
    return handler();
  });
}

function renderPanel() {
  return render(
    <PreferencesProvider>
      <PlanPanel assignmentId="a1" />
    </PreferencesProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
  // jsdom has no matchMedia, and the provider probes for it.
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PlanPanel: empty state", () => {
  it("offers generation rather than an error when nothing is planned", async () => {
    route({ "GET /api/v1/assignments/a1/plans": () => jsonResponse(null) });
    renderPanel();

    // A null plan is a normal state, not a failure: nothing here should be an alert.
    expect(await screen.findByRole("button", { name: /generate plan/i })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("PlanPanel: reading a plan", () => {
  beforeEach(() => {
    route({
      "GET /api/v1/assignments/a1/plans": () => jsonResponse(plan()),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () => jsonResponse(page([])),
    });
  });

  it("groups tasks under the milestone that claims them", async () => {
    renderPanel();
    expect(await screen.findByText("Research report plan")).toBeInTheDocument();
    // The milestone heading and the task both render; a flat list would only
    // show the task, which is the difference between a list and a schedule.
    expect(screen.getByText("Understand")).toBeInTheDocument();
    expect(screen.getByText("Read the brief")).toBeInTheDocument();
  });

  it("keeps a task's detail out of the list until the task is selected", async () => {
    renderPanel();
    const button = await screen.findByRole("button", { name: /read the brief/i });

    // Acceptance criteria are only meaningful beside the task they belong to,
    // so the list alone must not surface them.
    expect(screen.queryByText("Can summarise the ask")).not.toBeInTheDocument();
    expect(screen.getByText(/select a task to see its detail/i)).toBeInTheDocument();

    fireEvent.click(button);
    expect(await screen.findByText("Can summarise the ask")).toBeInTheDocument();
  });

  it("reports the schedule risk as arithmetic, not as a verdict", async () => {
    renderPanel();
    await screen.findByText("Research report plan");
    fireEvent.click(screen.getByRole("button", { name: /^risks$/i }));

    // The server's own wording is shown. The panel must not turn "8 hours
    // against 5 remaining" into a claim that the deadline will be missed.
    expect(
      screen.getByText("6 to 8 estimated hours against 5 hours remaining."),
    ).toBeInTheDocument();
  });

  it("counts hours from the plan's own minute range", async () => {
    renderPanel();
    await screen.findByText("Research report plan");
    // 240-480 minutes is 4-8 hours, and the estimate is labelled as one.
    expect(screen.getByText("4–8")).toBeInTheDocument();
  });
});

describe("PlanPanel: a fallback is always stated", () => {
  it("says the engine answered and lists why the model's plan was rejected", async () => {
    route({
      "GET /api/v1/assignments/a1/plans": () =>
        jsonResponse(
          plan({
            used_fallback: true,
            rejection_reasons: ["the dependency graph contains a cycle"],
            validation_warnings: [
              "this plan was produced by the planning engine, not the model " +
                "(the dependency graph contains a cycle)",
            ],
          }),
        ),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () => jsonResponse(page([])),
    });
    renderPanel();

    expect(await screen.findByText(/generated without a model response/i)).toBeInTheDocument();
    // The reason comes from the plan as data and is rendered through the
    // translator, so it reads as a labelled reason rather than as the server's
    // English sentence.
    expect(
      screen.getByText(/fallback reason: the dependency graph contains a cycle/i),
    ).toBeInTheDocument();
    // ...and the raw prose is not repeated beside it.
    expect(screen.queryByText(/not the model/)).not.toBeInTheDocument();
  });

  it("says nothing about a fallback when the model produced the plan", async () => {
    route({
      "GET /api/v1/assignments/a1/plans": () => jsonResponse(plan()),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () => jsonResponse(page([])),
    });
    renderPanel();
    await screen.findByText("Research report plan");
    expect(screen.queryByText(/without a model response/i)).not.toBeInTheDocument();
  });
});

describe("PlanPanel: approval", () => {
  it("refuses to offer approval for a stale plan", async () => {
    route({
      "GET /api/v1/assignments/a1/plans": () => jsonResponse(plan({ is_stale: true })),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () => jsonResponse(page([])),
    });
    renderPanel();
    await screen.findByText("Research report plan");

    // The server refuses a stale plan, so the button is disabled rather than
    // offering an action that cannot succeed.
    expect(screen.getByRole("button", { name: /approve plan/i })).toBeDisabled();
    expect(screen.getByText(/changed after this plan was generated/i)).toBeInTheDocument();
  });

  it("does not offer editing an approved plan", async () => {
    route({
      "GET /api/v1/assignments/a1/plans": () =>
        jsonResponse(plan({ status: "APPROVED", approved_at: "2026-01-02T10:00:00Z" })),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () => jsonResponse(page([])),
    });
    renderPanel();
    await screen.findByText("Research report plan");
    expect(screen.getByRole("button", { name: /approve plan/i })).toBeDisabled();
  });

  it("posts the approval and reflects the server's result", async () => {
    const approved = plan({ status: "APPROVED", approved_at: "2026-01-02T10:00:00Z" });
    const calls: string[] = [];
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input).replace(/^https?:\/\/[^/]+/, "");
      const method = init?.method ?? "GET";
      calls.push(`${method} ${url}`);
      if (method === "POST" && url.endsWith("/approve")) return jsonResponse(approved);
      if (url.endsWith("/plans/runs?page=1&page_size=5")) return jsonResponse(page([]));
      if (url.endsWith("/plans")) return jsonResponse(plan());
      return jsonResponse({ error: { code: "NOT_FOUND", message: url } }, 404);
    });

    renderPanel();
    const button = await screen.findByRole("button", { name: /approve plan/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(calls).toContain("POST /api/v1/assignments/a1/plans/p1/approve");
    });
  });

  it("shows the server's refusal when approval is rejected", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input).replace(/^https?:\/\/[^/]+/, "");
      const method = init?.method ?? "GET";
      if (method === "POST" && url.endsWith("/approve")) {
        return jsonResponse(
          {
            error: {
              code: "PLAN_STALE",
              message: "This plan was built on a superseded analysis.",
            },
          },
          409,
        );
      }
      if (url.endsWith("/plans/runs?page=1&page_size=5")) return jsonResponse(page([]));
      if (url.endsWith("/plans")) return jsonResponse(plan());
      return jsonResponse({ error: { code: "NOT_FOUND", message: url } }, 404);
    });

    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /approve plan/i }));

    // The refusal is stated, and the plan the student was reading stays on
    // screen: losing it because an approval failed would be a bad trade.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/superseded analysis/i);
    expect(screen.getByText("Research report plan")).toBeInTheDocument();
  });
});

describe("PlanPanel: regeneration scope", () => {
  beforeEach(() => {
    route({
      "GET /api/v1/assignments/a1/plans": () => jsonResponse(plan()),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () => jsonResponse(page([])),
    });
  });

  it("sends the chosen scope with the regeneration", async () => {
    const bodies: string[] = [];
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input).replace(/^https?:\/\/[^/]+/, "");
      const method = init?.method ?? "GET";
      if (method === "POST" && url.endsWith("/plans/regenerate")) {
        bodies.push(String(init?.body ?? ""));
        return jsonResponse(plan({ version: 2, trigger: "REGENERATED" }));
      }
      if (url.endsWith("/plans/runs?page=1&page_size=5")) return jsonResponse(page([]));
      if (url.endsWith("/plans")) return jsonResponse(plan());
      return jsonResponse({ error: { code: "NOT_FOUND", message: url } }, 404);
    });

    renderPanel();
    await screen.findByText("Research report plan");
    const select = screen.getByLabelText(/regenerate scope/i);
    fireEvent.change(select, { target: { value: "MILESTONES" } });
    fireEvent.click(screen.getByRole("button", { name: /regenerate/i }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(JSON.parse(bodies[0])).toMatchObject({ scope: "MILESTONES" });
  });

  it("explains what the milestone-only scope does before it is used", async () => {
    renderPanel();
    await screen.findByText("Research report plan");
    fireEvent.change(screen.getByLabelText(/regenerate scope/i), {
      target: { value: "MILESTONES" },
    });
    // "Regenerate" is ambiguous on its own; the scope has to say what it keeps.
    expect(screen.getByText(/keep every task and rebuild the checkpoints/i)).toBeInTheDocument();
  });
});

describe("PlanPanel: generation history", () => {
  it("shows a failed attempt with its error rather than hiding it", async () => {
    route({
      "GET /api/v1/assignments/a1/plans": () => jsonResponse(plan()),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () =>
        jsonResponse(
          page([
            {
              id: "r1",
              assignment_id: "a1",
              plan_id: null,
              status: "FAILED",
              provider: "openai",
              model: "gpt-4o",
              model_tier: "ADVANCED",
              routing_reason: "High complexity.",
              routing_confidence: 0.8,
              complexity: "HIGH",
              fell_back_from_tier: null,
              prompt_version: "academic_planner_v1",
              duration_ms: 120,
              token_usage: null,
              estimated_cost: null,
              error_code: "LLM_UNAVAILABLE",
              error_message: "no route to host",
              started_at: "2026-01-01T10:00:00Z",
              completed_at: "2026-01-01T10:00:02Z",
            },
          ]),
        ),
    });

    renderPanel();
    await screen.findByText("Research report plan");
    fireEvent.click(screen.getByRole("button", { name: /version history/i }));

    // A failed generation that leaves no visible reason is indistinguishable
    // from one that never ran.
    expect(await screen.findByText("LLM_UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText(/no route to host/)).toBeInTheDocument();
  });
});

describe("PlanPanel: language", () => {
  it("renders in Persian and mirrors the document direction", async () => {
    window.localStorage.setItem("studyos.locale", "fa");
    route({
      "GET /api/v1/assignments/a1/plans": () => jsonResponse(plan()),
      "GET /api/v1/assignments/a1/plans/runs?page=1&page_size=5": () => jsonResponse(page([])),
    });
    renderPanel();

    // The interface is translated; the plan's own content is the server's and
    // is left alone, because translating a student's task titles would be
    // inventing content rather than presenting it.
    expect(await screen.findByRole("button", { name: /تأیید برنامه/ })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("fa-IR");
  });
});
