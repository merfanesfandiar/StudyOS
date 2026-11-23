import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Composer } from "@/components/agent-workspace/composer";
import { renderWithPreferences } from "./render";

const t = (key: string) => String(key);
const onSend = vi.fn(async () => true);
const onStop = vi.fn(async () => undefined);

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(cleanup);

function renderComposer(overrides: Partial<Parameters<typeof Composer>[0]> = {}) {
  const props: Parameters<typeof Composer>[0] = {
    t,
    disabled: false,
    sending: false,
    canStop: false,
    onStop,
    onSend,
    assignmentId: "a1",
    canAttach: true,
    ...overrides,
  };
  return renderWithPreferences(<Composer {...props} />);
}

describe("Composer", () => {
  it("sends on Enter and inserts a newline on Shift+Enter", async () => {
    renderComposer();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "first message" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });
    await waitFor(() => expect(onSend).toHaveBeenCalledWith("first message"));

    fireEvent.change(input, { target: { value: "line one" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("disables send while sending and shows the stop control only when a run is live", async () => {
    renderComposer({ sending: true, canStop: true });
    expect(screen.getByRole("button", { name: "workspace.composer.sending" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "workspace.composer.stop" })).toBeInTheDocument();
  });

  it("uploads an attachment through the documents API and marks it uploaded", async () => {
    // POST /assignments/a1/documents → 201
    fetchMock.mockImplementation(async () =>
      jsonResponse(
        { id: "d1", assignment_id: "a1", filename: "notes.pdf", mime_type: "application/pdf", size: 4, created_at: "2026-01-01T00:00:00Z" },
        201,
      ),
    );
    renderComposer();
    fireEvent.click(screen.getByRole("button", { name: "workspace.composer.attach" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    const file = new File(["data"], "notes.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText("workspace.composer.uploaded"),
    ).toBeInTheDocument();
    expect(screen.getByText(/notes\.pdf/)).toBeInTheDocument();
  });

  it("shows a failed upload with its reason and refuses to fake success", async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse({ error: { code: "UNSUPPORTED_FILE_TYPE", message: "nope" } }, 422),
    );
    renderComposer();
    fireEvent.click(screen.getByRole("button", { name: "workspace.composer.attach" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["data"], "thing.exe", { type: "application/octet-stream" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(
      await screen.findByText("workspace.composer.unsupportedType"),
    ).toBeInTheDocument();
    expect(screen.queryByText("workspace.composer.uploaded")).not.toBeInTheDocument();
  });

  it("cannot open the file picker without a bound assignment", () => {
    renderComposer({ assignmentId: null, canAttach: false });
    const attach = screen.getByRole("button", { name: "workspace.composer.attach" });
    expect(attach).toBeDisabled();
  });
});
