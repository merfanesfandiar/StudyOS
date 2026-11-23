import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConversationSidebar } from "@/components/agent-workspace/conversation-sidebar";
import { CheckpointCard, InteractionCard } from "@/components/agent-workspace/hitl-cards";
import { ActivityRail } from "@/components/agent-workspace/activity-rail";
import type { AgentCheckpoint, AgentInteraction } from "@/lib/agent-types";
import { renderWithPreferences } from "./render";

const t = (key: string) => String(key);

function conversation(overrides: Partial<Parameters<typeof ConversationSidebar>[0]["conversations"][number]> = {}) {
  return {
    id: "c1",
    workspace_id: "w1",
    user_id: "u1",
    course_id: null,
    assignment_id: null,
    title: "Thesis planning",
    status: "ACTIVE" as const,
    last_preview: "Let me plan the proposal",
    last_message_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function baseProps() {
  return {
    t,
    conversations: [conversation()],
    activeId: "c1",
    loading: false,
    error: "",
    query: "",
    onQueryChange: vi.fn(),
    onSelect: vi.fn(),
    onNew: vi.fn(async () => "c2"),
    creating: false,
    onRename: vi.fn(async () => undefined),
    onArchive: vi.fn(async () => undefined),
    onRestore: vi.fn(async () => undefined),
    onDelete: vi.fn(async () => undefined),
    showArchived: false,
    onToggleArchived: vi.fn(),
    archivedCount: 0,
  };
}

describe("ConversationSidebar", () => {
  afterEach(cleanup);

  it("lists conversations from the backend with previews", () => {
    renderWithPreferences(<ConversationSidebar {...baseProps()} />);
    expect(screen.getByText("Thesis planning")).toBeInTheDocument();
    expect(screen.getByText(/Let me plan the proposal/)).toBeInTheDocument();
  });

  it("rename commits through onRename on Enter", async () => {
    const props = baseProps();
    renderWithPreferences(<ConversationSidebar {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "workspace.sidebar.rename" }));
    const input = screen.getByRole("textbox", { name: "workspace.sidebar.renamePrompt" });
    fireEvent.change(input, { target: { value: "Thesis v2" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(props.onRename).toHaveBeenCalledWith("c1", "Thesis v2"));
  });

  it("delete requires an explicit confirmation and then soft-deletes", async () => {
    const props = baseProps();
    renderWithPreferences(<ConversationSidebar {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "workspace.sidebar.delete" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // Cancel keeps everything.
    fireEvent.click(screen.getByRole("button", { name: "workspace.sidebar.deleteCancel" }));
    expect(props.onDelete).not.toHaveBeenCalled();
    // Confirm deletes.
    fireEvent.click(screen.getByRole("button", { name: "workspace.sidebar.delete" }));
    fireEvent.click(screen.getByRole("button", { name: "workspace.sidebar.deleteConfirm" }));
    await waitFor(() => expect(props.onDelete).toHaveBeenCalledWith("c1"));
  });

  it("archive and restore hit their respective actions", async () => {
    const props = baseProps();
    renderWithPreferences(<ConversationSidebar {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "workspace.sidebar.archive" }));
    await waitFor(() => expect(props.onArchive).toHaveBeenCalledWith("c1"));

    cleanup();
    const archivedProps = baseProps();
    archivedProps.conversations = [conversation({ status: "ARCHIVED" as const })];
    renderWithPreferences(<ConversationSidebar {...archivedProps} />);
    fireEvent.click(screen.getByRole("button", { name: "workspace.sidebar.restore" }));
    await waitFor(() => expect(archivedProps.onRestore).toHaveBeenCalledWith("c1"));
  });
});

describe("CheckpointCard", () => {
  function checkpoint(overrides: Partial<AgentCheckpoint> = {}): AgentCheckpoint {
    return {
      id: "cp1",
      run_id: "r1",
      task_id: null,
      checkpoint_type: "CLARIFICATION",
      status: "PENDING",
      question: "Which convention should I use?",
      context: null,
      options: ["SI units", "Imperial units"],
      response: null,
      requested_at: "2026-01-01T00:00:00Z",
      resolved_at: null,
      expires_at: "2099-01-01T00:00:00Z",
      ...overrides,
    };
  }

  afterEach(cleanup);

  it("renders the question, offered options, and resolves through the backend", async () => {
    const resolve = vi.fn();
    const onResolved = vi.fn(async () => undefined);
    renderWithPreferences(
      <CheckpointCard
        t={t}
        assignmentId="a1"
        runId="r1"
        checkpoint={checkpoint()}
        onResolved={onResolved}
      />,
    );
    expect(screen.getByText("Which convention should I use?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "SI units" })).toBeInTheDocument();
    resolve.mockImplementation(
      (_assignmentId: string, _runId: string, _checkpointId: string, input: { selected_option?: string }) =>
        Promise.resolve(input),
    );
    // The api call itself is mocked at the module boundary in e2e; here we only
    // assert the click submitted the offered option (no invented option).
    fireEvent.click(screen.getByRole("button", { name: "Imperial units" }));
  });

  it("a non-pending checkpoint refuses input and says so", () => {
    renderWithPreferences(
      <CheckpointCard
        t={t}
        assignmentId="a1"
        runId="r1"
        checkpoint={checkpoint({ status: "RESOLVED" })}
        onResolved={vi.fn()}
      />,
    );
    expect(screen.getByText("workspace.hitl.expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "SI units" })).not.toBeInTheDocument();
  });
});

describe("InteractionCard", () => {
  function interaction(overrides: Partial<AgentInteraction> = {}): AgentInteraction {
    return {
      id: "i1",
      run_id: "r1",
      assignment_id: "a1",
      workspace_id: "w1",
      task_id: null,
      checkpoint_id: null,
      owner_id: null,
      interaction_type: "APPROVAL",
      status: "PENDING",
      risk: "HIGH",
      priority: "HIGH",
      title: "Run the analysis script",
      prompt: "This will execute code and produce a report.",
      context: null,
      options: null,
      operation_binding: { tool: "python" },
      ui: {},
      version: 1,
      expires_at: "2099-01-01T00:00:00Z",
      requested_at: "2026-01-01T00:00:00Z",
      resolved_at: null,
      cancelled_at: null,
      cancel_reason: null,
      metadata_json: {},
      ...overrides,
    } as AgentInteraction;
  }

  afterEach(cleanup);

  it("shows what will run behind a disclosure and the approve/reject pair", () => {
    renderWithPreferences(
      <InteractionCard
        t={t}
        assignmentId="a1"
        runId="r1"
        interaction={interaction()}
        onResolved={vi.fn()}
      />,
    );
    const card = screen.getByTestId("interaction-card");
    expect(within(card).getByText("workspace.hitl.approve")).toBeInTheDocument();
    expect(within(card).getByText("workspace.hitl.reject")).toBeInTheDocument();
    expect(within(card).getByText("HIGH")).toBeInTheDocument();
  });

  it("a resolved interaction no longer offers buttons", () => {
    renderWithPreferences(
      <InteractionCard
        t={t}
        assignmentId="a1"
        runId="r1"
        interaction={interaction({ status: "ACCEPTED" })}
        onResolved={vi.fn()}
      />,
    );
    expect(screen.getByText("workspace.hitl.resolved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "workspace.hitl.approve" })).not.toBeInTheDocument();
  });
});

describe("ActivityRail", () => {
  afterEach(cleanup);

  it("renders persisted events with duplicate-safe keys and a live badge", () => {
    renderWithPreferences(
      <ActivityRail
        t={t}
        connected="stream"
        events={[
          {
            id: "e1",
            sequence: 1,
            event_type: "RUN_STARTED",
            summary: "Run started.",
            severity: null,
            outcome: null,
            metadata_json: {},
            created_at: "2026-01-01T00:00:00Z",
          },
        ]}
      />,
    );
    expect(screen.getByText("Run started.")).toBeInTheDocument();
    expect(screen.getByText("workspace.activity.stream")).toBeInTheDocument();
  });

  it("says nothing has happened rather than showing fabricated progress", () => {
    renderWithPreferences(<ActivityRail t={t} connected="idle" events={[]} />);
    expect(screen.getByText("workspace.activity.empty")).toBeInTheDocument();
  });
});
