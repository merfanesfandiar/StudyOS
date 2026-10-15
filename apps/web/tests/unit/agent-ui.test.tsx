import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentUiView } from "@/components/agent/agent-ui";
import { AGENT_UI_VERSION, type AgentUiEnvelope } from "@/lib/agent-ui/blocks";
import { parseAgentUi } from "@/lib/agent-ui/validate";
import { renderWithPreferences } from "./render";

afterEach(cleanup);

/** A raw payload for the validator, which accepts anything. */
function raw(blocks: unknown[], version: number = AGENT_UI_VERSION): unknown {
  return { version, blocks };
}

/** A typed envelope for the renderer, where the shape is already trusted. */
function env(blocks: AgentUiEnvelope["blocks"]): AgentUiEnvelope {
  return { version: AGENT_UI_VERSION, blocks };
}

describe("parseAgentUi", () => {
  it("accepts a well-formed envelope", () => {
    const result = parseAgentUi(
      raw([
        { type: "text", text: "Here is what I found." },
        { type: "callout", tone: "warning", text: "Check the margin." },
      ]),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.envelope.version).toBe(AGENT_UI_VERSION);
    expect(result.envelope.blocks).toHaveLength(2);
    expect(result.errors).toHaveLength(0);
  });

  it("rejects a payload that is not an object", () => {
    expect(parseAgentUi("<script>alert(1)</script>").ok).toBe(false);
    expect(parseAgentUi(null).ok).toBe(false);
    expect(parseAgentUi([{ type: "text", text: "x" }]).ok).toBe(false);
  });

  it("rejects a version it does not understand rather than guessing", () => {
    const result = parseAgentUi(raw([{ type: "text", text: "future" }], AGENT_UI_VERSION + 1));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors[0]).toMatch(/unsupported version/);
  });

  it("rejects an envelope with no blocks array", () => {
    expect(parseAgentUi({ version: AGENT_UI_VERSION }).ok).toBe(false);
  });

  it("keeps an unknown block type visible instead of dropping it", () => {
    const result = parseAgentUi(raw([{ type: "hologram", data: "?" }]));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.envelope.blocks[0]).toEqual({ type: "unsupported", blockType: "hologram" });
  });

  it("drops a malformed known block and records why", () => {
    const result = parseAgentUi(raw([{ type: "choice", id: "c1", prompt: "Pick", options: [] }]));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.envelope.blocks[0].type).toBe("unsupported");
    expect(result.errors.join(" ")).toMatch(/no usable options/);
  });

  it("truncates over-long text rather than rendering it whole", () => {
    const result = parseAgentUi(raw([{ type: "text", text: "a".repeat(10_000) }]));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const block = result.envelope.blocks[0];
    if (block.type !== "text") throw new Error("expected text block");
    expect(block.text.length).toBeLessThanOrEqual(4_001);
    expect(block.text.endsWith("…")).toBe(true);
  });

  it("drops an unsafe citation URL but keeps the citation", () => {
    const result = parseAgentUi(
      raw([
        {
          type: "citation",
          items: [
            { label: "Unsafe", url: "javascript:alert(1)" },
            { label: "Safe", url: "https://example.edu/paper" },
          ],
        },
      ]),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const block = result.envelope.blocks[0];
    if (block.type !== "citation") throw new Error("expected citation block");
    expect(block.items[0].url).toBeUndefined();
    expect(block.items[1].url).toBe("https://example.edu/paper");
  });

  it("reads only the declared columns of a table", () => {
    const result = parseAgentUi(
      raw([
        {
          type: "table",
          columns: [{ key: "name", label: "Name" }],
          rows: [{ name: "Ada", secret: "should not appear" }],
        },
      ]),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const block = result.envelope.blocks[0];
    if (block.type !== "table") throw new Error("expected table block");
    expect(block.rows[0]).toEqual({ name: "Ada" });
  });

  it("treats an item as uncovered unless the payload says otherwise", () => {
    const result = parseAgentUi(
      raw([{ type: "coverage", items: [{ label: "Tests" }, { label: "Docs", covered: true }] }]),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const block = result.envelope.blocks[0];
    if (block.type !== "coverage") throw new Error("expected coverage block");
    expect(block.items[0].covered).toBe(false);
    expect(block.items[1].covered).toBe(true);
  });

  it("strips control characters from text", () => {
    const result = parseAgentUi(raw([{ type: "text", text: "a\u0000b\u001f c" }]));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const block = result.envelope.blocks[0];
    if (block.type !== "text") throw new Error("expected text block");
    expect(block.text).toBe("ab c");
  });
});

describe("AgentUiView", () => {
  it("renders text and callouts", () => {
    renderWithPreferences(
      <AgentUiView
        envelope={env([
          { type: "text", text: "Here is what I found." },
          { type: "callout", tone: "warning", title: "Heads up", text: "Check the margin." },
        ])}
      />,
    );

    expect(screen.getByText("Here is what I found.")).toBeInTheDocument();
    expect(screen.getByText("Check the margin.")).toBeInTheDocument();
  });

  it("sends the option's value, not its label, when a choice is submitted", () => {
    const onSubmit = vi.fn();
    renderWithPreferences(
      <AgentUiView
        envelope={env([
          {
            type: "choice",
            id: "c1",
            prompt: "Which notation?",
            options: [
              { value: "Knopp", label: "Knopp notation" },
              { value: "other", label: "Something else" },
            ],
          },
        ])}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByLabelText("Knopp notation"));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(onSubmit).toHaveBeenCalledWith({ id: "c1", values: ["Knopp"], other: undefined });
  });

  it("renders a read-only choice as a static list, not disabled controls", () => {
    renderWithPreferences(
      <AgentUiView
        envelope={env([
          {
            type: "choice",
            id: "c1",
            prompt: "Which notation?",
            options: [{ value: "knopp", label: "Knopp notation" }],
          },
        ])}
      />,
    );

    expect(screen.getByText("Knopp notation")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit" })).not.toBeInTheDocument();
  });

  it("reports an approval decision", () => {
    const onSubmit = vi.fn();
    renderWithPreferences(
      <AgentUiView
        envelope={env([{ type: "approval", id: "a1", prompt: "Submit the draft?" }])}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onSubmit).toHaveBeenCalledWith({ id: "a1", approved: true });
  });

  it("renders an unsupported block as a named gap", () => {
    renderWithPreferences(
      <AgentUiView envelope={env([{ type: "unsupported", blockType: "hologram" }])} />,
    );

    expect(screen.getByText(/block: hologram/)).toBeInTheDocument();
  });

  it("translates its chrome in Persian", () => {
    window.localStorage.setItem("studyos.locale", "fa");
    renderWithPreferences(
      <AgentUiView
        envelope={env([
          {
            type: "choice",
            id: "c1",
            prompt: "کدام نمادگذاری؟",
            options: [{ value: "knopp", label: "نمادگذاری کنوپ" }],
          },
        ])}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "ارسال" })).toBeInTheDocument();
    window.localStorage.removeItem("studyos.locale");
  });
});
