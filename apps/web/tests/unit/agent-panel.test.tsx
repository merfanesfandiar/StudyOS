import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPanel } from "@/components/agent/agent-panel";
import type {
  AgentCapabilities,
  AgentCheckpoint,
  AgentRun,
  AgentRunDetail,
  AgentTask,
} from "@/lib/agent-types";
import { renderWithPreferences } from "./render";

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

function errorResponse(code: string, message: string, status = 409): Response {
  return jsonResponse({ error: { code, message } }, status);
}

const BASE = "/api/v1/assignments/a1/agent";

const CAPABILITIES: AgentCapabilities = {
  tools: [
    { name: "read_context", description: "Read assembled context.", permissions: ["read"] },
    { name: "write_artifact", description: "Write a draft.", permissions: ["write"] },
  ],
  executors: ["DETERMINISTIC"],
  modes: ["SUPERVISED", "AUTONOMOUS"],
  actions: ["CREATE_ARTIFACT", "COMPLETE_TASK"],
  // The point of the panel: the negative list is rendered, not implied.
  absent_capabilities: ["execute_code", "shell", "network_access", "filesystem_write"],
  limits: { max_iterations: 12 },
};

function task(overrides: Partial<AgentTask> = {}): AgentTask {
  return {
    id: "t1",
    key: "T1",
    title: "Draft the introduction",
    type: "READ",
    status: "PENDING",
    priority: "HIGH",
    position: 0,
    attempted: false,
    attempts: 0,
    last_status: null,
    last_summary: null,
    artifact_ids: [],
    can_auto_complete: true,
    ...overrides,
  };
}

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "r1",
    assignment_id: "a1",
    plan_id: "p1",
    plan_version: 2,
    status: "CREATED",
    mode: "SUPERVISED",
    paused_reason: null,
    error_code: null,
    error_message: null,
    error_category: null,
    model: "efficient",
    model_tier: "EFFICIENT",
    routing_reason: "Small scope.",
    iteration_count: 0,
    max_iterations: 12,
    max_cost: 1,
    estimated_cost: 0,
    token_usage: null,
    started_at: null,
    completed_at: null,
    duration_ms: null,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

function detail(overrides: Partial<AgentRunDetail> = {}): AgentRunDetail {
  return {
    ...run(),
    progress: { total: 2, completed: 0, skipped: 0, in_progress: 0, blocked: 0, remaining: 2, percent: 0 },
    awaiting_checkpoint_id: null,
    can_resume: false,
    can_retry: false,
    tasks: [task()],
    executions: [],
    artifacts: [],
    checkpoints: [],
    events: [],
    decisions: [],
    context_provenance: [],
    ...overrides,
  };
}

function checkpoint(overrides: Partial<AgentCheckpoint> = {}): AgentCheckpoint {
  return {
    id: "cp1",
    run_id: "r1",
    task_id: null,
    checkpoint_type: "CLARIFICATION",
    status: "PENDING",
    question: "Which notation should I use?",
    context: null,
    options: ["Knopp", "Other"],
    response: null,
    requested_at: "2026-01-01T10:01:00Z",
    resolved_at: null,
    expires_at: null,
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
      throw new Error(`unrouted request: ${key}`);
    }
    return handler();
  });
}

function baseHandlers(extra: Record<string, () => Response | Promise<Response>> = {}) {
  return {
    [`GET ${BASE}/runs`]: () => jsonResponse({ items: [] }),
    [`GET ${BASE}/capabilities`]: () => jsonResponse(CAPABILITIES),
    ...extra,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(cleanup);

describe("AgentPanel", () => {
  it("says why it cannot run yet when the plan is not approved", async () => {
    route(baseHandlers());
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan={false} />);

    expect(await screen.findByText("Needs an approved plan")).toBeInTheDocument();
    // No way to create a run, so the empty state cannot be mistaken for a bug.
    expect(screen.queryByRole("button", { name: "Create run" })).not.toBeInTheDocument();
  });

  it("offers a mode choice when the plan is approved", async () => {
    route(baseHandlers());
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    expect(await screen.findByRole("button", { name: "Create run" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Ask me first/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Keep going/)).toBeInTheDocument();
  });

  it("renders what the runtime cannot do", async () => {
    route(baseHandlers());
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    // The boundary is the server's list, rendered verbatim.
    await screen.findByRole("button", { name: "Create run" });
    fireEvent.click(screen.getByText("What this agent cannot do"));
    expect(screen.getByText("execute_code")).toBeInTheDocument();
    expect(screen.getByText("network_access")).toBeInTheDocument();
  });

  it("does not create a run until asked", async () => {
    route(
      baseHandlers({
        [`POST ${BASE}/runs`]: () => jsonResponse(run(), 201),
        [`GET ${BASE}/runs/r1`]: () => jsonResponse(detail()),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("button", { name: "Create run" }));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
      expect(calls).toHaveLength(1);
    });
    // Creating a run must not also start it. Opening the workspace costs nothing.
    const paths = fetchMock.mock.calls.map(([input, init]) => `${init?.method ?? "GET"} ${input}`);
    expect(paths).not.toContain(`POST ${BASE}/runs/r1/start`);
  });

  it("separates create from start so a click cannot spend money twice", async () => {
    route(
      baseHandlers({
        [`POST ${BASE}/runs`]: () => jsonResponse(run(), 201),
        [`GET ${BASE}/runs/r1`]: () => jsonResponse(detail()),
        [`POST ${BASE}/runs/r1/start`]: () => jsonResponse(detail({ status: "COMPLETED" })),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("button", { name: "Create run" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));

    await waitFor(() => expect(screen.getByText("Finished")).toBeInTheDocument());
    const starts = fetchMock.mock.calls.filter(([input, init]) =>
      String(input).endsWith("/start") && init?.method === "POST",
    );
    expect(starts).toHaveLength(1);
  });

  it("shows the server's reason for a stop rather than a bare status", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "WAITING_FOR_USER" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "WAITING_FOR_USER",
              paused_reason: "clarification: Which notation should I use?",
              awaiting_checkpoint_id: "cp1",
              can_resume: true,
              checkpoints: [checkpoint()],
            }),
          ),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    expect(await screen.findByText("Waiting for you")).toBeInTheDocument();
    expect(
      screen.getByText(/clarification: Which notation should I use\?/),
    ).toBeInTheDocument();
  });

  it("puts the question before the controls and sends the chosen option", async () => {
    let body: unknown = null;
    // The stubs follow one run through the exchange: answering it moves the run
    // on, so the refresh after the answer must not hand back the old state.
    let answered = false;
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () =>
          jsonResponse({ items: [run({ status: answered ? "COMPLETED" : "WAITING_FOR_USER" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: answered ? "COMPLETED" : "WAITING_FOR_USER",
              paused_reason: answered ? null : "clarification",
              awaiting_checkpoint_id: answered ? null : "cp1",
              checkpoints: answered ? [] : [checkpoint()],
            }),
          ),
        [`POST ${BASE}/runs/r1/checkpoints/cp1/resolve`]: () => {
          body = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body));
          answered = true;
          return jsonResponse(detail({ status: "COMPLETED" }));
        },
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    const prompt = await screen.findByText("The agent needs a decision");
    expect(prompt).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Knopp"));
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));

    await waitFor(() => expect(screen.getByText("Finished")).toBeInTheDocument());
    // The option is sent as the server's own value, not a translated label: the
    // API validates it against what was offered.
    expect(body).toMatchObject({ selected_option: "Knopp" });
    // The question is gone once answered, not still on screen.
    expect(screen.queryByText("The agent needs a decision")).not.toBeInTheDocument();
  });

  it("keeps a failed action from blanking the run the student is reading", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run()] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(detail({ status: "RUNNING", iteration_count: 3 })),
        [`POST ${BASE}/runs/r1/pause`]: () =>
          errorResponse("AGENT_RUN_NOT_PAUSABLE", "This run cannot be paused right now."),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    expect(
      await screen.findByText("This run cannot be paused right now."),
    ).toBeInTheDocument();
    // The workspace survives the failure.
    expect(screen.getByText("Draft the introduction")).toBeInTheDocument();
  });

  it("keeps every draft revision rather than showing only the last", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "COMPLETED" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "COMPLETED",
              artifacts: [
                {
                  id: "a2",
                  run_id: "r1",
                  task_id: "t1",
                  title: "Introduction",
                  artifact_type: "DRAFT",
                  status: "DRAFT",
                  content: "Second attempt, better opening.",
                  metadata_json: null,
                  revision: 2,
                  deliverable_key: null,
                  created_at: "2026-01-01T10:05:00Z",
                  updated_at: "2026-01-01T10:05:00Z",
                },
                {
                  id: "a1",
                  run_id: "r1",
                  task_id: "t1",
                  title: "Introduction",
                  artifact_type: "DRAFT",
                  status: "DRAFT",
                  content: "First attempt.",
                  metadata_json: null,
                  revision: 1,
                  deliverable_key: null,
                  created_at: "2026-01-01T10:02:00Z",
                  updated_at: "2026-01-01T10:02:00Z",
                },
              ],
            }),
          ),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("tab", { name: "Drafts" }));
    const panel = screen.getByRole("tabpanel", { hidden: true }) ?? document.body;
    expect(within(panel as HTMLElement).getByText(/First attempt\./)).toBeInTheDocument();
    expect(within(panel as HTMLElement).getByText(/Second attempt/)).toBeInTheDocument();
  });

  it("reports a read failure instead of showing an empty workspace", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => errorResponse("AGENT_UNAVAILABLE", "The runtime is down.", 503),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    expect(await screen.findByText("The runtime is down.")).toBeInTheDocument();
  });

  it("renders the activity trail in the server's order", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "COMPLETED" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "COMPLETED",
              events: [
                {
                  id: "e2",
                  sequence: 2,
                  event_type: "TASK_COMPLETED",
                  summary: "Completed T1.",
                  metadata_json: {},
                  task_id: "t1",
                  created_at: "2026-01-01T10:04:00Z",
                },
                {
                  id: "e1",
                  sequence: 1,
                  event_type: "RUN_CREATED",
                  summary: "Run created.",
                  metadata_json: {},
                  task_id: null,
                  created_at: "2026-01-01T10:03:00Z",
                },
              ],
            }),
          ),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("tab", { name: "Activity" }));
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Run created.");
    expect(items[1]).toHaveTextContent("Completed T1.");
  });

  it("hides the run controls on a finished run", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "CANCELLED" })] }),
        [`GET ${BASE}/runs/r1`]: () => jsonResponse(detail({ status: "CANCELLED" })),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    await screen.findByText("Cancelled");
    // Cancelled is terminal. Offering pause or cancel again would be a lie.
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("reports what recovery reclaimed", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [] }),
        [`POST ${BASE}/recover`]: () =>
          jsonResponse({ runs_paused: 2, checkpoints_expired: 0, run_ids: ["r1", "r2"] }),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("button", { name: "Recover abandoned runs" }));

    expect(await screen.findByText("Recovered 2 abandoned runs.")).toBeInTheDocument();
  });

  it("still works when the capability list comes back unusable", async () => {
    // A 200 with the wrong shape must not take the page with it. This is what a
    // catch-all API stub produces, and it crashed the whole assignment page once.
    route(
      baseHandlers({
        [`GET ${BASE}/capabilities`]: () =>
          jsonResponse({ items: [], page: { page: 1, page_size: 20, total: 0, pages: 1 } }),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    // The workspace is intact; only the disclosure is absent.
    expect(await screen.findByRole("button", { name: "Create run" })).toBeInTheDocument();
    expect(screen.queryByText("What this agent cannot do")).not.toBeInTheDocument();
  });

  it("renders Persian labels when the locale is Persian", async () => {
    route(baseHandlers());
    window.localStorage.setItem("studyos.locale", "fa");
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    expect(await screen.findByRole("button", { name: "ساخت اجرا" })).toBeInTheDocument();
    window.localStorage.removeItem("studyos.locale");
  });
});