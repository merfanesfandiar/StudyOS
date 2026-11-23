import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MessageItem } from "@/components/agent-workspace/message-item";
import { Markdown } from "@/components/agent-workspace/markdown";
import type { ConversationMessage } from "@/lib/conversations-types";
import { renderWithPreferences } from "./render";

function message(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "m1",
    conversation_id: "c1",
    role: "USER",
    kind: "TEXT",
    content: "hello **world**",
    metadata_json: {},
    edited_revision: 1,
    edit_history_json: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("Markdown", () => {
  afterEach(cleanup);

  it("renders markdown to React elements without raw HTML", () => {
    renderWithPreferences(
      <Markdown>{"<img src=x onerror=alert(1)> **bold**"}</Markdown>,
    );
    // The tag must be text, not an element: no img may exist.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("bold")).toBeInTheDocument();
    expect(document.querySelector("strong")).toBeInTheDocument();
  });

  it("keeps code blocks LTR", () => {
    renderWithPreferences(<Markdown>{"```\nconst x = 1;\n```"}</Markdown>);
    const pre = document.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.closest("[dir='ltr']")).not.toBeNull();
  });

  it("renders GFM tables", () => {
    renderWithPreferences(
      <Markdown>{"| a | b |\n| - | - |\n| 1 | 2 |"}</Markdown>,
    );
    expect(document.querySelector("table")).not.toBeNull();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});

describe("MessageItem", () => {
  const onEdit = vi.fn(async () => true);

  beforeEach(() => {
    onEdit.mockClear();
  });

  afterEach(cleanup);

  it("renders a user message with copy and edit actions", async () => {
    renderWithPreferences(
      <MessageItem message={message()} t={(key) => String(key)} canEdit onEdit={onEdit} />,
    );
    expect(screen.getByText("world")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "workspace.message.copy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "workspace.message.edit" })).toBeInTheDocument();

    // Agent and system messages are not editable: they are records of what the
    // backend did.
    cleanup();
    renderWithPreferences(
      <MessageItem
        message={message({ role: "AGENT" })}
        t={(key) => String(key)}
        canEdit
        onEdit={onEdit}
      />,
    );
    expect(screen.queryByRole("button", { name: "workspace.message.edit" })).not.toBeInTheDocument();
  });

  it("editing applies explicit semantics and shows history", async () => {
    const edited = message({
      edited_revision: 2,
      edit_history_json: [{ revision: 1, content: "original" }],
      content: "corrected",
    });
    renderWithPreferences(
      <MessageItem message={edited} t={(key) => String(key)} canEdit onEdit={onEdit} />,
    );
    expect(screen.getByText("corrected")).toBeInTheDocument();

    fireEvent.click(screen.getByText("workspace.message.edited", { exact: false }));
    expect(await screen.findByText(/original/)).toBeInTheDocument();
  });

  it("edit flow calls onEdit with the draft and exits edit mode on success", async () => {
    renderWithPreferences(
      <MessageItem message={message()} t={(key) => String(key)} canEdit onEdit={onEdit} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "workspace.message.edit" }));
    const textarea = await screen.findByRole("textbox");
    fireEvent.change(textarea, { target: { value: "rewritten" } });
    fireEvent.click(screen.getByRole("button", { name: "workspace.message.saveEdit" }));
    await waitFor(() => expect(onEdit).toHaveBeenCalledWith("m1", "rewritten"));
    // Back to reading view: the save/cancel pair is gone.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "workspace.message.saveEdit" }),
      ).not.toBeInTheDocument(),
    );
  });
});
