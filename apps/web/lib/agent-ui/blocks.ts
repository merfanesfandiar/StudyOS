/**
 * The Dynamic Agent UI protocol.
 *
 * The agent is a language model, and a language model that can emit arbitrary
 * HTML is a language model that can emit a `<script>`. So the interface the
 * agent drives is not markup: it is a small, closed vocabulary of typed blocks.
 * The agent fills a block in; a renderer in this codebase decides what that
 * looks like. Nothing the agent sends is ever parsed as HTML, evaluated as
 * JavaScript, or used as a component name.
 *
 * The envelope is versioned for the same reason any wire format is: a frontend
 * deploy and a backend deploy are not simultaneous, so a payload from a newer
 * backend must be refused cleanly rather than half-rendered. `version` is checked
 * before a single block is trusted.
 *
 * Every field name below is part of the contract the backend codes against.
 * Adding a field is a minor change; changing the meaning of one, or a block's
 * `type` discriminant, is a new `AGENT_UI_VERSION`.
 */

/**
 * The protocol version this build understands.
 *
 * A payload declaring a *higher* version is refused rather than best-effort
 * rendered: a future block type the agent means as required would otherwise
 * vanish silently, and a silently-dropped instruction is worse than an error the
 * student can see and report.
 */
export const AGENT_UI_VERSION = 1;

/**
 * Hard ceilings on everything that can arrive.
 *
 * The agent's output is untrusted by construction, and "untrusted" includes
 * "large". A run that returns forty thousand table rows is not a rendering
 * problem to solve later; it is a hang, and the validator refuses it at the
 * door rather than letting it reach React.
 */
export const AGENT_UI_LIMITS = {
  blocks: 60,
  options: 30,
  items: 100,
  columns: 12,
  rows: 200,
  text: 4_000,
  code: 20_000,
  url: 2_048,
} as const;

export type AgentUiTone = "info" | "success" | "warning" | "danger";

/** One row of a {@link AgentUiTableBlock}, keyed by the column's `key`. */
export type AgentUiTableRow = Record<string, string>;

export interface AgentUiTextBlock {
  type: "text";
  text: string;
  /** `muted` de-emphasises a fragment without inventing a new colour. */
  tone?: "default" | "muted";
}

export interface AgentUiCalloutBlock {
  type: "callout";
  tone: AgentUiTone;
  title?: string;
  text: string;
}

export interface AgentUiChoiceOption {
  /** What is sent back to the API. Never a translated label. */
  value: string;
  label: string;
  description?: string;
}

export interface AgentUiChoiceBlock {
  type: "choice";
  /** Stable id so the answer can be attributed to this block. */
  id: string;
  prompt: string;
  help?: string;
  /** Checkboxes rather than radios. Defaults to single-select. */
  multiple?: boolean;
  /** Whether the student may answer with free text instead of an option. */
  allow_other?: boolean;
  options: AgentUiChoiceOption[];
}

export interface AgentUiApprovalBlock {
  type: "approval";
  id: string;
  prompt: string;
  detail?: string;
  approve_label?: string;
  reject_label?: string;
}

export interface AgentUiProgressBlock {
  type: "progress";
  label: string;
  value: number;
  max?: number;
}

export interface AgentUiTaskItem {
  key: string;
  title: string;
  status: string;
  note?: string;
}

export interface AgentUiTaskListBlock {
  type: "task_list";
  title?: string;
  items: AgentUiTaskItem[];
}

export interface AgentUiTableColumn {
  key: string;
  label: string;
  align?: "start" | "end";
}

export interface AgentUiTableBlock {
  type: "table";
  caption?: string;
  columns: AgentUiTableColumn[];
  rows: AgentUiTableRow[];
}

export interface AgentUiCodeBlock {
  type: "code";
  title?: string;
  language?: string;
  code: string;
}

export interface AgentUiCitationItem {
  label: string;
  detail?: string;
  /** Only `http`, `https`, and `mailto` survive validation. */
  url?: string;
}

export interface AgentUiCitationBlock {
  type: "citation";
  title?: string;
  items: AgentUiCitationItem[];
}

export interface AgentUiCoverageItem {
  label: string;
  covered: boolean;
  detail?: string;
}

export interface AgentUiCoverageBlock {
  type: "coverage";
  title?: string;
  items: AgentUiCoverageItem[];
}

/**
 * A formula, carried as LaTeX source.
 *
 * Rendered as selectable text, not typeset maths, because this build ships no
 * maths renderer and a half-rendered formula is worse than an honest source
 * string. The block exists so the agent can label a formula as a formula.
 */
export interface AgentUiMathBlock {
  type: "math";
  title?: string;
  latex: string;
}

/**
 * What an unrecognised block type becomes.
 *
 * Unknown block types are *kept* rather than dropped. Dropping them would let a
 * newer backend silently lose a step of its interface on an older client; the
 * fallback names the type so the gap is visible and reportable.
 */
export interface AgentUiUnsupportedBlock {
  type: "unsupported";
  blockType: string;
}

export type AgentUiBlock =
  | AgentUiTextBlock
  | AgentUiCalloutBlock
  | AgentUiChoiceBlock
  | AgentUiApprovalBlock
  | AgentUiProgressBlock
  | AgentUiTaskListBlock
  | AgentUiTableBlock
  | AgentUiCodeBlock
  | AgentUiCitationBlock
  | AgentUiCoverageBlock
  | AgentUiMathBlock
  | AgentUiUnsupportedBlock;

/** Every block `type` this build can render, including the fallback. */
export const AGENT_UI_BLOCK_TYPES = [
  "text",
  "callout",
  "choice",
  "approval",
  "progress",
  "task_list",
  "table",
  "code",
  "citation",
  "coverage",
  "unsupported",
] as const;

/** The known block discriminants. `AgentUiBlockType` is derived from the union. */
export type AgentUiBlockType = AgentUiBlock["type"];

export interface AgentUiEnvelope {
  /** Always the version the renderer understood, after validation. */
  version: number;
  blocks: AgentUiBlock[];
}

/** What an interactive block reports back to the host surface. */
export interface AgentUiSubmission {
  /** The block's own id. */
  id: string;
  /** Chosen option values, for `choice`. */
  values?: string[];
  /** Free text, for `choice` with `allow_other`. */
  other?: string;
  /** The decision, for `approval`. */
  approved?: boolean;
}
