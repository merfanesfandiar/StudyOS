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
  workers: [
    {
      id: "MATHEMATICS",
      name: "mathematics",
      description: "Analyses numbers: statistics and fits.",
      academic_task_types: ["SOLVE", "PROVE"],
      tools: ["calculate", "read_context"],
      output_artifact_types: ["SOLUTION"],
    },
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
    tool_invocations: [],
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

  it("names the worker boundaries it publishes", async () => {
    route(baseHandlers());
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    await screen.findByRole("button", { name: "Create run" });
    fireEvent.click(screen.getByText("What this agent cannot do"));
    // The boundary is the worker and its toolset, not just a flat tool list.
    expect(screen.getByText("Task workers")).toBeInTheDocument();
    expect(screen.getByText("MATHEMATICS")).toBeInTheDocument();
    expect(screen.getByText(/calculate/)).toBeInTheDocument();
  });

  it("shows refused tool calls rather than hiding them", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "COMPLETED" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "COMPLETED",
              tool_invocations: [
                {
                  id: "i1",
                  run_id: "r1",
                  task_id: "t1",
                  task_key: "T1",
                  worker_kind: "MATHEMATICS",
                  tool_name: "calculate",
                  iteration: 1,
                  status: "SUCCESS",
                  args: { expression: "2+2" },
                  result: { value: 4 },
                  error: null,
                  duration_ms: 3,
                  created_at: "2026-01-01T10:04:00Z",
                },
                {
                  id: "i2",
                  run_id: "r1",
                  task_id: "t1",
                  task_key: "T1",
                  worker_kind: "MATHEMATICS",
                  tool_name: "solve_linear_system",
                  iteration: 2,
                  status: "BLOCKED",
                  args: {},
                  result: null,
                  error: "That tool is not allowed for this task.",
                  duration_ms: null,
                  created_at: "2026-01-01T10:05:00Z",
                },
              ],
            }),
          ),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("tab", { name: "Activity" }));
    expect(screen.getByText("Tool calls")).toBeInTheDocument();
    expect(screen.getByText("calculate")).toBeInTheDocument();
    // The refusal is kept on the log, with the server's reason.
    expect(screen.getByText("Refused")).toBeInTheDocument();
    expect(screen.getByText("That tool is not allowed for this task.")).toBeInTheDocument();
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

  it("sends an explicit approval decision for a REVIEW checkpoint", async () => {
    let body: unknown = null;
    let resolved = false;
    const review = checkpoint({
      checkpoint_type: "REVIEW",
      question: "Is this introduction ready to keep?",
      // The runtime's own sentinels. Offering them as radios beside the two
      // buttons that mean the same thing is how a student ends up submitting a
      // string the API will not accept as a decision.
      options: ["approve", "reject"],
    });
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () =>
          jsonResponse({ items: [run({ status: resolved ? "COMPLETED" : "WAITING_FOR_USER" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: resolved ? "COMPLETED" : "WAITING_FOR_USER",
              awaiting_checkpoint_id: resolved ? null : "cp1",
              checkpoints: resolved ? [] : [review],
            }),
          ),
        [`POST ${BASE}/runs/r1/checkpoints/cp1/resolve`]: () => {
          body = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body));
          resolved = true;
          return jsonResponse(detail({ status: "COMPLETED" }));
        },
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    // A decision checkpoint requires `approved`; without it the server answers
    // AGENT_CHECKPOINT_DECISION_REQUIRED and the run never moves.
    expect(await screen.findByText("Is this introduction ready to keep?")).toBeInTheDocument();
    expect(screen.queryByLabelText("approve")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.getByText("Finished")).toBeInTheDocument());
    expect(body).toMatchObject({ approved: true });
  });

  it("sends a rejection decision without inventing a text answer", async () => {
    let body: unknown = null;
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "WAITING_FOR_USER" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "WAITING_FOR_USER",
              awaiting_checkpoint_id: "cp1",
              checkpoints: [checkpoint({ checkpoint_type: "APPROVAL" })],
            }),
          ),
        [`POST ${BASE}/runs/r1/checkpoints/cp1/resolve`]: () => {
          body = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body));
          return jsonResponse(detail({ status: "WAITING_FOR_USER" }));
        },
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ approved: false });
    expect(body).not.toHaveProperty("response");
  });

  it("stops the run from the checkpoint instead of submitting an empty answer", async () => {
    let cancelled = false;
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () =>
          jsonResponse({ items: [run({ status: "WAITING_FOR_USER" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "WAITING_FOR_USER",
              awaiting_checkpoint_id: "cp1",
              can_resume: true,
              checkpoints: [checkpoint()],
            }),
          ),
        [`POST ${BASE}/runs/r1/cancel`]: () => {
          cancelled = true;
          return jsonResponse(detail({ status: "CANCELLED" }));
        },
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    fireEvent.click(await screen.findByRole("button", { name: "Stop the run" }));

    // "Stop" is a cancellation, not an empty answer. The old button posted a
    // blank response, which the API correctly refused with 422.
    await waitFor(() => expect(cancelled).toBe(true));
    const resolveCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/checkpoints/cp1/resolve"),
    );
    expect(resolveCalls).toHaveLength(0);
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
                  artifact_type: "MARKDOWN",
                  status: "ACTIVE",
                  ownership: "AGENT_OWNED",
                  content: "Second attempt, better opening.",
                  metadata_json: null,
                  revision: 2,
                  deliverable_key: null,
                  worker_name: "MATHEMATICS",
                  created_at: "2026-01-01T10:05:00Z",
                  updated_at: "2026-01-01T10:05:00Z",
                },
                {
                  id: "a1",
                  run_id: "r1",
                  task_id: "t1",
                  title: "Introduction",
                  artifact_type: "MARKDOWN",
                  status: "ACTIVE",
                  ownership: "AGENT_OWNED",
                  content: "First attempt.",
                  metadata_json: null,
                  revision: 1,
                  deliverable_key: null,
                  worker_name: null,
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

  it("polls a running run so the progress moves without a click", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "RUNNING" })] }),
        [`GET ${BASE}/runs/r1`]: () => jsonResponse(detail({ status: "RUNNING", iteration_count: 1 })),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    // The panel asks on its own while the run is live: the activation poll
    // re-reads the detail endpoint with no button pressed. The mount read alone
    // would be one call; two means the poll already fired.
    await waitFor(() => {
      const detailCalls = fetchMock.mock.calls.filter(
        ([input, init]) => String(input).endsWith("/runs/r1") && (init?.method ?? "GET") === "GET",
      );
      expect(detailCalls.length).toBeGreaterThanOrEqual(2);
    });
    expect(screen.getByText("Progress")).toBeInTheDocument();
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

  it("moves between tabs with the keyboard and keeps one tab stop", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "COMPLETED" })] }),
        [`GET ${BASE}/runs/r1`]: () => jsonResponse(detail({ status: "COMPLETED" })),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    const tabs = await screen.findAllByRole("tab");
    expect(tabs).toHaveLength(4);
    // Roving tabindex: the selected tab is the only one Tab reaches.
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");

    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("tabindex", "0");
    expect(tabs[0]).toHaveAttribute("tabindex", "-1");
    expect(document.activeElement).toBe(tabs[1]);

    fireEvent.keyDown(tabs[1], { key: "End" });
    expect(tabs[3]).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tabs[3]);

    // Arrows wrap, so forward from the last tab returns to the first.
    fireEvent.keyDown(tabs[3], { key: "ArrowRight" });
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tabs[0]);
  });

  it("follows writing direction when arrowing through tabs", async () => {
    window.localStorage.setItem("studyos.locale", "fa");
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "COMPLETED" })] }),
        [`GET ${BASE}/runs/r1`]: () => jsonResponse(detail({ status: "COMPLETED" })),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    const tabs = await screen.findAllByRole("tab");
    tabs[0].focus();
    // In RTL the next tab is to the left; ArrowRight would move backwards.
    fireEvent.keyDown(tabs[0], { key: "ArrowLeft" });
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(tabs[1]);
    window.localStorage.removeItem("studyos.locale");
  });

  it("localizes the runtime's own review question and options in Persian", async () => {
    window.localStorage.setItem("studyos.locale", "fa");
    const review = checkpoint({
      checkpoint_type: "REVIEW",
      question:
        "I have drafted T1 3 times without finishing it. Would you like me to keep revising, move on, or stop?",
      context:
        "Repeated drafting usually means the task is missing information rather than that another pass will fix it.",
      options: ["Keep revising", "Move on and leave the draft", "Stop this run"],
    });
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () =>
          jsonResponse({ items: [run({ status: "WAITING_FOR_USER" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "WAITING_FOR_USER",
              awaiting_checkpoint_id: "cp1",
              checkpoints: [review],
            }),
          ),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    // The runtime's revision-limit question is product copy, not model output,
    // so the Persian UI must not show it in English.
    expect(
      await screen.findByText(/من T1 را 3 بار بدون تمام‌کردن پیش‌نویس نوشته‌ام/),
    ).toBeInTheDocument();
    expect(screen.getByText("ادامهٔ بازنویسی")).toBeInTheDocument();
    expect(screen.getByText("رفتن به مرحلهٔ بعد و نگه‌داشتن پیش‌نویس")).toBeInTheDocument();
    expect(screen.getByText("متوقف کردن این اجرا")).toBeInTheDocument();
    expect(
      screen.getByText(/تکرار پیش‌نویس معمولاً یعنی کار به اطلاعات بیشتری نیاز دارد/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/I have drafted T1/)).not.toBeInTheDocument();
    window.localStorage.removeItem("studyos.locale");
  });
});

describe("AgentPanel dynamic interface", () => {
  it("renders the Dynamic Agent UI attached to a checkpoint", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "WAITING_FOR_USER" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "WAITING_FOR_USER",
              awaiting_checkpoint_id: "cp1",
              can_resume: true,
              checkpoints: [
                checkpoint({
                  ui: {
                    version: 1,
                    blocks: [
                      { type: "text", text: "I compared both conventions." },
                      {
                        type: "table",
                        columns: [{ key: "a", label: "Option" }],
                        rows: [{ a: "Knopp" }],
                      },
                    ],
                  },
                }),
              ],
            }),
          ),
      }),
    );
    renderWithPreferences(<AgentPanel assignmentId="a1" hasApprovedPlan />);

    expect(await screen.findByText("I compared both conventions.")).toBeInTheDocument();
    expect(screen.getByText("Option")).toBeInTheDocument();
    // The plain form still owns the answer, so the structured blocks never
    // become a second submit path.
    expect(screen.getByRole("button", { name: "Send answer" })).toBeInTheDocument();
  });

  it("falls back to the draft's own text when its interface is unusable", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "COMPLETED" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "COMPLETED",
              artifacts: [
                {
                  id: "a1",
                  run_id: "r1",
                  task_id: "t1",
                  title: "Introduction",
                  artifact_type: "MARKDOWN",
                  status: "ACTIVE",
                  ownership: "AGENT_OWNED",
                  content: "Plain draft text.",
                  metadata_json: {
                    ui: { version: 99, blocks: [{ type: "text", text: "ignored" }] },
                  },
                  revision: 1,
                  deliverable_key: null,
                  worker_name: null,
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
    expect(screen.getByText("Plain draft text.")).toBeInTheDocument();
    // A version the app cannot render must not hide the artifact.
    expect(screen.queryByText("ignored")).not.toBeInTheDocument();
  });

  it("renders a structured artifact interface in place of its raw text", async () => {
    route(
      baseHandlers({
        [`GET ${BASE}/runs`]: () => jsonResponse({ items: [run({ status: "COMPLETED" })] }),
        [`GET ${BASE}/runs/r1`]: () =>
          jsonResponse(
            detail({
              status: "COMPLETED",
              artifacts: [
                {
                  id: "a1",
                  run_id: "r1",
                  task_id: "t1",
                  title: "Comparison",
                  artifact_type: "MARKDOWN",
                  status: "ACTIVE",
                  ownership: "AGENT_OWNED",
                  content: "raw fallback",
                  metadata_json: {
                    ui: {
                      version: 1,
                      blocks: [
                        { type: "coverage", title: "Requirements", items: [{ label: "Tests", covered: true }] },
                      ],
                    },
                  },
                  revision: 1,
                  deliverable_key: null,
                  worker_name: null,
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
    expect(screen.getByText("Requirements")).toBeInTheDocument();
    expect(screen.queryByText("raw fallback")).not.toBeInTheDocument();
  });
});