import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExecutionPanel } from "@/components/assignment/execution-panel";
import type { ExecutionAttempt, ExecutionCapabilities, ExecutionJob } from "@/lib/execution-types";
import { renderWithPreferences } from "./render";

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

const JOBS = "/api/v1/assignments/a1/executions";
const CAPABILITIES = "/api/v1/executions/capabilities";

const CAPS: ExecutionCapabilities = {
  enabled: true,
  backend: "MOCK",
  available: true,
  execution_types: ["PYTHON", "JAVA"],
  resource_profiles: {
    LIGHT_COMPUTATION: { timeout_seconds: 10, memory_mb: 256 },
    STANDARD_CODE_EXECUTION: { timeout_seconds: 30, memory_mb: 512 },
  },
  default_profile: { PYTHON: "LIGHT_COMPUTATION" },
  limits: {},
  // The point of the panel: the negative list is rendered, not implied.
  absent_capabilities: ["host_code_execution", "network_access", "filesystem_write_outside_sandbox"],
};

function job(overrides: Partial<ExecutionJob> = {}): ExecutionJob {
  return {
    id: "j1",
    workspace_id: "w1",
    assignment_id: "a1",
    agent_run_id: null,
    task_id: null,
    execution_type: "PYTHON",
    backend: "MOCK",
    status: "SUCCEEDED",
    resource_profile: "LIGHT_COMPUTATION",
    entrypoint: "main.py",
    attempt_count: 1,
    max_attempts: 1,
    exit_code: 0,
    duration_ms: 12,
    failure_class: null,
    error_code: null,
    error_message: null,
    result_excerpt: "Hello from the sandbox",
    cleanup_status: "CLEANED",
    created_at: "2026-01-01T10:00:00Z",
    queued_at: null,
    started_at: "2026-01-01T10:00:00Z",
    completed_at: "2026-01-01T10:00:00Z",
    failed_at: null,
    cancelled_at: null,
    ...overrides,
  };
}

function attempt(overrides: Partial<ExecutionAttempt> = {}): ExecutionAttempt {
  return {
    id: "at1",
    attempt: 1,
    status: "SUCCEEDED",
    backend: "MOCK",
    exit_code: 0,
    failure_class: null,
    error_code: null,
    error_message: null,
    duration_ms: 12,
    stdout_excerpt: "Hello from the sandbox",
    stderr_excerpt: null,
    started_at: "2026-01-01T10:00:00Z",
    completed_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

/** Stub fetch by "METHOD path". An unexpected request fails the test loudly. */
function pathOf(input: RequestInfo | URL): string {
  return String(input).replace(/^https?:\/\/[^/]+/, "");
}

function route(handlers: Record<string, () => Response>): void {
  fetchMock.mockImplementation((input, init) => {
    const key = `${init?.method ?? "GET"} ${pathOf(input)}`;
    const handler = handlers[key];
    if (!handler) throw new Error(`unexpected request: ${key}`);
    return Promise.resolve(handler());
  });
}

function baseHandlers(extra: Record<string, () => Response> = {}): Record<string, () => Response> {
  return {
    [`GET ${CAPABILITIES}`]: () => jsonResponse(CAPS),
    [`GET ${JOBS}`]: () =>
      jsonResponse({ items: [], page: { page: 1, page_size: 20, total: 0, pages: 1 } }),
    ...extra,
  };
}

function renderPanel() {
  return renderWithPreferences(<ExecutionPanel assignmentId="a1" />);
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
});

describe("ExecutionPanel", () => {
  it("renders the sandbox boundary the server publishes, and does not invent one", async () => {
    route(baseHandlers());
    renderPanel();

    const label = await screen.findByText("What the sandbox cannot reach");
    const boundary = label.closest("details")!;
    expect(boundary).toHaveTextContent("network_access");
    expect(boundary).toHaveTextContent("host_code_execution");
    // Not a settings panel: there is no control for anything on the negative list.
    expect(boundary.querySelectorAll("input, select, button")).toHaveLength(0);
  });

  it("says running code is off when no backend is configured, with no submit control", async () => {
    route(
      baseHandlers({
        [`GET ${CAPABILITIES}`]: () =>
          jsonResponse({
            ...CAPS,
            enabled: false,
            backend: "DISABLED",
            available: false,
            execution_types: [],
          }),
      }),
    );
    renderPanel();

    expect(await screen.findByText("Running code is turned off")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
  });

  it("distinguishes a configured-but-unreachable backend from a disabled one", async () => {
    route(
      baseHandlers({
        [`GET ${CAPABILITIES}`]: () => jsonResponse({ ...CAPS, available: false }),
      }),
    );
    renderPanel();

    expect(
      await screen.findByText(/A sandbox is configured but is not reachable/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
  });

  it("submits source and a runtime, never a command", async () => {
    let body: Record<string, unknown> | null = null;
    route(
      baseHandlers({
        [`POST ${JOBS}`]: () => {
          body = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body)) as Record<string, unknown>;
          return jsonResponse(job(), 201);
        },
        [`GET ${JOBS}/j1`]: () => jsonResponse({ job: job(), attempts: [attempt()], artifacts: [], events: [] }),
      }),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Run" }));

    await waitFor(() => expect(body).not.toBeNull());
    // The request names a runtime and carries source. It has no field for an
    // image, a binary or a command line, because the API has none either.
    expect(body).toMatchObject({ execution_type: "PYTHON" });
    expect(body).not.toHaveProperty("command");
    expect(body).not.toHaveProperty("image");
  });

  it("keeps a failed run's exit code and stderr on screen", async () => {
    const failed = job({
      status: "FAILED",
      exit_code: 1,
      failure_class: "USER_CODE_FAILED",
      result_excerpt: null,
    });
    route(
      baseHandlers({
        [`GET ${JOBS}`]: () =>
          jsonResponse({ items: [failed], page: { page: 1, page_size: 20, total: 1, pages: 1 } }),
        [`GET ${JOBS}/j1`]: () =>
          jsonResponse({
            job: failed,
            attempts: [
              attempt({
                status: "FAILED",
                exit_code: 1,
                failure_class: "USER_CODE_FAILED",
                stdout_excerpt: null,
                stderr_excerpt: "NameError: name 'x' is not defined",
              }),
            ],
            artifacts: [],
            events: [],
          }),
      }),
    );
    renderPanel();

    // "The compiler said this" is the whole point of running it. The exit code
    // shows on both the job and the attempt, so both are expected.
    expect((await screen.findAllByText("exit 1")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("USER_CODE_FAILED").length).toBeGreaterThan(0);
    expect(screen.getByText(/NameError/)).toBeInTheDocument();
  });

  it("does not offer to stop a job that has already finished", async () => {
    route(
      baseHandlers({
        [`GET ${JOBS}`]: () =>
          jsonResponse({ items: [job()], page: { page: 1, page_size: 20, total: 1, pages: 1 } }),
        [`GET ${JOBS}/j1`]: () => jsonResponse({ job: job(), attempts: [attempt()], artifacts: [], events: [] }),
      }),
    );
    renderPanel();

    await screen.findAllByText("Finished");
    // A stop button on a terminal job would be a lie.
    expect(screen.queryByRole("button", { name: "Stop run" })).not.toBeInTheDocument();
  });

  it("polls a running job so the result moves without a click", async () => {
    route(
      baseHandlers({
        [`GET ${JOBS}`]: () =>
          jsonResponse({
            items: [job({ status: "RUNNING" })],
            page: { page: 1, page_size: 20, total: 1, pages: 1 },
          }),
        [`GET ${JOBS}/j1`]: () =>
          jsonResponse({
            job: job({ status: "RUNNING", exit_code: null, result_excerpt: null }),
            attempts: [attempt({ status: "RUNNING", exit_code: null, completed_at: null })],
            artifacts: [],
            events: [],
          }),
      }),
    );
    renderPanel();

    await waitFor(
      () => {
        const reads = fetchMock.mock.calls.filter(([input]) =>
          pathOf(input).endsWith("/executions/j1"),
        );
        expect(reads.length).toBeGreaterThanOrEqual(2);
      },
      // The mount read is one call; the poll timer is what makes it two. Give
      // the timer room to fire rather than racing it at the default timeout.
      { timeout: 4000 },
    );
  });

  it("reports a read failure instead of showing an empty workspace", async () => {
    route(
      baseHandlers({
        [`GET ${JOBS}`]: () => errorResponse("EXECUTION_UNAVAILABLE", "The sandbox is down.", 503),
      }),
    );
    renderPanel();

    expect(await screen.findByText("The sandbox is down.")).toBeInTheDocument();
  });

  it("keeps the last good job on screen when an action fails", async () => {
    route(
      baseHandlers({
        [`GET ${JOBS}`]: () =>
          jsonResponse({
            items: [job({ status: "RUNNING", exit_code: null, result_excerpt: null })],
            page: { page: 1, page_size: 20, total: 1, pages: 1 },
          }),
        [`GET ${JOBS}/j1`]: () =>
          jsonResponse({
            job: job({ status: "RUNNING", exit_code: null, result_excerpt: null }),
            attempts: [attempt({ status: "RUNNING", exit_code: null, completed_at: null })],
            artifacts: [],
            events: [],
          }),
        [`POST ${JOBS}/j1/cancel`]: () =>
          errorResponse("EXECUTION_NOT_CANCELLABLE", "This run cannot be stopped right now."),
      }),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Stop run" }));
    expect(await screen.findByText("This run cannot be stopped right now.")).toBeInTheDocument();
    // The workspace survives the failure.
    expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
  });

  it("still works when the capability list comes back unusable", async () => {
    route(
      baseHandlers({
        [`GET ${CAPABILITIES}`]: () => jsonResponse({ items: [] }),
      }),
    );
    renderPanel();

    // The workspace is intact; only the disclosures are absent.
    expect(await screen.findByRole("button", { name: "Run" })).toBeInTheDocument();
    expect(screen.queryByText("What the sandbox cannot reach")).not.toBeInTheDocument();
  });

  it("renders Persian labels when the locale is Persian", async () => {
    route(baseHandlers());
    window.localStorage.setItem("studyos.locale", "fa");
    renderPanel();

    expect(await screen.findByRole("button", { name: "اجرا" })).toBeInTheDocument();
    window.localStorage.removeItem("studyos.locale");
  });
});
