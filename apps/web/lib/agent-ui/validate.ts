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
 * The envelope is versioned because the two sides deploy independently. A
 * version this build does not understand is refused wholesale rather than
 * half-rendered, because a block the agent meant as a gate is exactly the one a
 * best-effort renderer would silently skip.
 */

import {
  AGENT_UI_LIMITS,
  AGENT_UI_VERSION,
  type AgentUiApprovalBlock,
  type AgentUiBlock,
  type AgentUiCalloutBlock,
  type AgentUiChoiceBlock,
  type AgentUiCitationBlock,
  type AgentUiCodeBlock,
  type AgentUiCoverageBlock,
  type AgentUiEnvelope,
  type AgentUiProgressBlock,
  type AgentUiTableBlock,
  type AgentUiTaskListBlock,
  type AgentUiTextBlock,
  type AgentUiTone,
} from "./blocks";

export interface AgentUiParseSuccess {
  ok: true;
  envelope: AgentUiEnvelope;
  /** Non-fatal problems: dropped blocks, truncated fields, unknown types. */
  errors: string[];
}

export interface AgentUiParseFailure {
  ok: false;
  errors: string[];
}

export type AgentUiParseResult = AgentUiParseSuccess | AgentUiParseFailure;

type BlockResult = { ok: true; block: AgentUiBlock } | { ok: false; error: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * A bounded, control-character-free string, or `null` when there is nothing
 * usable.
 *
 * Control characters are stripped rather than escaped because there is nowhere
 * for them to go: this value is rendered as text by React, which already escapes
 * markup, and a stray NUL or bidi-override character in a string about to be
 * read is at best noise and at worst a spoofing aid. Over-long content is
 * truncated with an ellipsis: a length bound is a rendering guard, and rejecting
 * a whole block over one long paragraph would cost more than it protects.
 */
function cleanText(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const stripped = value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").trim();
  if (stripped.length === 0) return null;
  return stripped.length > max ? `${stripped.slice(0, max)}…` : stripped;
}

/** A required string: absent or blank is a block-level error. */
function requiredText(
  record: Record<string, unknown>,
  key: string,
  max: number,
): { ok: true; value: string } | { ok: false; error: string } {
  const value = cleanText(record[key], max);
  if (value === null) return { ok: false, error: `"${key}" must be a non-empty string` };
  return { ok: true, value };
}

function optionalText(record: Record<string, unknown>, key: string, max: number): string | undefined {
  return cleanText(record[key], max) ?? undefined;
}

function optionalBool(record: Record<string, unknown>, key: string): boolean | undefined {
  return record[key] === true ? true : record[key] === false ? false : undefined;
}

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

/**
 * Only the schemes the app can link to safely.
 *
 * `javascript:` and `data:` are exactly what an attacker-controlled string would
 * carry, and an `<a href>` is where they would land. An unusable URL is dropped
 * from the item rather than failing the block: a citation without its link is
 * still a citation.
 */
function safeUrl(value: unknown): string | undefined {
  const text = cleanText(value, AGENT_UI_LIMITS.url);
  if (text === null) return undefined;
  try {
    const url = new URL(text);
    if (url.protocol === "http:" || url.protocol === "https:" || url.protocol === "mailto:") {
      return url.toString();
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function boundedArray(value: unknown, max: number): { items: unknown[]; truncated: boolean } {
  if (!Array.isArray(value)) return { items: [], truncated: false };
  return { items: value.slice(0, max), truncated: value.length > max };
}

const TONES: readonly AgentUiTone[] = ["info", "success", "warning", "danger"];

function parseText(record: Record<string, unknown>): BlockResult {
  const text = requiredText(record, "text", AGENT_UI_LIMITS.text);
  if (!text.ok) return text;
  const block: AgentUiTextBlock = { type: "text", text: text.value };
  if (record.tone === "muted" || record.tone === "default") block.tone = record.tone;
  return { ok: true, block };
}

function parseCallout(record: Record<string, unknown>): BlockResult {
  const text = requiredText(record, "text", AGENT_UI_LIMITS.text);
  if (!text.ok) return text;
  const tone = TONES.includes(record.tone as AgentUiTone) ? (record.tone as AgentUiTone) : "info";
  const block: AgentUiCalloutBlock = { type: "callout", tone, text: text.value };
  const title = optionalText(record, "title", AGENT_UI_LIMITS.text);
  if (title) block.title = title;
  return { ok: true, block };
}

function parseChoice(record: Record<string, unknown>): BlockResult {
  const id = requiredText(record, "id", 128);
  if (!id.ok) return id;
  const prompt = requiredText(record, "prompt", AGENT_UI_LIMITS.text);
  if (!prompt.ok) return prompt;
  const rawOptions = boundedArray(record.options, AGENT_UI_LIMITS.options);
  const options: AgentUiChoiceBlock["options"] = [];
  for (const raw of rawOptions.items) {
    if (!isRecord(raw)) continue;
    const value = cleanText(raw.value, 256);
    const label = cleanText(raw.label, 512);
    // An option with no value cannot be answered or attributed, so it is dropped
    // rather than rendered as a dead choice.
    if (value === null || label === null) continue;
    const option: AgentUiChoiceBlock["options"][number] = { value, label };
    const description = optionalText(raw, "description", AGENT_UI_LIMITS.text);
    if (description) option.description = description;
    options.push(option);
  }
  if (options.length === 0) return { ok: false, error: "no usable options" };
  const block: AgentUiChoiceBlock = { type: "choice", id: id.value, prompt: prompt.value, options };
  const help = optionalText(record, "help", AGENT_UI_LIMITS.text);
  if (help) block.help = help;
  const multiple = optionalBool(record, "multiple");
  if (multiple !== undefined) block.multiple = multiple;
  const allowOther = optionalBool(record, "allow_other");
  if (allowOther !== undefined) block.allow_other = allowOther;
  return { ok: true, block };
}

function parseApproval(record: Record<string, unknown>): BlockResult {
  const id = requiredText(record, "id", 128);
  if (!id.ok) return id;
  const prompt = requiredText(record, "prompt", AGENT_UI_LIMITS.text);
  if (!prompt.ok) return prompt;
  const block: AgentUiApprovalBlock = { type: "approval", id: id.value, prompt: prompt.value };
  const detail = optionalText(record, "detail", AGENT_UI_LIMITS.text);
  if (detail) block.detail = detail;
  const approveLabel = optionalText(record, "approve_label", 128);
  if (approveLabel) block.approve_label = approveLabel;
  const rejectLabel = optionalText(record, "reject_label", 128);
  if (rejectLabel) block.reject_label = rejectLabel;
  return { ok: true, block };
}

function parseProgress(record: Record<string, unknown>): BlockResult {
  const label = requiredText(record, "label", AGENT_UI_LIMITS.text);
  if (!label.ok) return label;
  const max = clampNumber(record.max, 1, Number.MAX_SAFE_INTEGER, 100);
  const block: AgentUiProgressBlock = {
    type: "progress",
    label: label.value,
    value: clampNumber(record.value, 0, max, 0),
    max,
  };
  return { ok: true, block };
}

function parseTaskList(record: Record<string, unknown>): BlockResult {
  const raw = boundedArray(record.items, AGENT_UI_LIMITS.items);
  const items: AgentUiTaskListBlock["items"] = [];
  for (const entry of raw.items) {
    if (!isRecord(entry)) continue;
    const key = cleanText(entry.key, 64);
    const title = cleanText(entry.title, AGENT_UI_LIMITS.text);
    const status = cleanText(entry.status, 64);
    if (key === null || title === null || status === null) continue;
    const item: AgentUiTaskListBlock["items"][number] = { key, title, status };
    const note = optionalText(entry, "note", AGENT_UI_LIMITS.text);
    if (note) item.note = note;
    items.push(item);
  }
  if (items.length === 0) return { ok: false, error: "no usable items" };
  const block: AgentUiTaskListBlock = { type: "task_list", items };
  const title = optionalText(record, "title", AGENT_UI_LIMITS.text);
  if (title) block.title = title;
  return { ok: true, block };
}

function parseTable(record: Record<string, unknown>): BlockResult {
  const rawColumns = boundedArray(record.columns, AGENT_UI_LIMITS.columns);
  const columns: AgentUiTableBlock["columns"] = [];
  for (const entry of rawColumns.items) {
    if (!isRecord(entry)) continue;
    const key = cleanText(entry.key, 128);
    const label = cleanText(entry.label, 256);
    if (key === null || label === null) continue;
    const column: AgentUiTableBlock["columns"][number] = { key, label };
    if (entry.align === "end" || entry.align === "start") column.align = entry.align;
    columns.push(column);
  }
  if (columns.length === 0) return { ok: false, error: "no usable columns" };
  const keys = columns.map((column) => column.key);
  const rawRows = boundedArray(record.rows, AGENT_UI_LIMITS.rows);
  const rows: AgentUiTableBlock["rows"] = [];
  for (const entry of rawRows.items) {
    if (!isRecord(entry)) continue;
    // Only declared columns are read. An undeclared key is not "extra data"; it
    // is a cell with no header, which the reader has no way to interpret.
    const row: Record<string, string> = {};
    for (const key of keys) row[key] = cleanText(entry[key], AGENT_UI_LIMITS.text) ?? "";
    rows.push(row);
  }
  const block: AgentUiTableBlock = { type: "table", columns, rows };
  const caption = optionalText(record, "caption", AGENT_UI_LIMITS.text);
  if (caption) block.caption = caption;
  return { ok: true, block };
}

function parseCode(record: Record<string, unknown>): BlockResult {
  const code = requiredText(record, "code", AGENT_UI_LIMITS.code);
  if (!code.ok) return code;
  const block: AgentUiCodeBlock = { type: "code", code: code.value };
  const title = optionalText(record, "title", AGENT_UI_LIMITS.text);
  if (title) block.title = title;
  const language = optionalText(record, "language", 64);
  if (language) block.language = language;
  return { ok: true, block };
}

function parseCitation(record: Record<string, unknown>): BlockResult {
  const raw = boundedArray(record.items, AGENT_UI_LIMITS.items);
  const items: AgentUiCitationBlock["items"] = [];
  for (const entry of raw.items) {
    if (!isRecord(entry)) continue;
    const label = cleanText(entry.label, 512);
    if (label === null) continue;
    const item: AgentUiCitationBlock["items"][number] = { label };
    const detail = optionalText(entry, "detail", AGENT_UI_LIMITS.text);
    if (detail) item.detail = detail;
    const url = safeUrl(entry.url);
    if (url) item.url = url;
    items.push(item);
  }
  if (items.length === 0) return { ok: false, error: "no usable items" };
  const block: AgentUiCitationBlock = { type: "citation", items };
  const title = optionalText(record, "title", AGENT_UI_LIMITS.text);
  if (title) block.title = title;
  return { ok: true, block };
}

function parseCoverage(record: Record<string, unknown>): BlockResult {
  const raw = boundedArray(record.items, AGENT_UI_LIMITS.items);
  const items: AgentUiCoverageBlock["items"] = [];
  for (const entry of raw.items) {
    if (!isRecord(entry)) continue;
    const label = cleanText(entry.label, AGENT_UI_LIMITS.text);
    if (label === null) continue;
    // `covered` defaults to false. An item whose coverage was not stated is not
    // covered, and a green tick the payload never claimed would be a lie.
    const item: AgentUiCoverageBlock["items"][number] = { label, covered: entry.covered === true };
    const detail = optionalText(entry, "detail", AGENT_UI_LIMITS.text);
    if (detail) item.detail = detail;
    items.push(item);
  }
  if (items.length === 0) return { ok: false, error: "no usable items" };
  const block: AgentUiCoverageBlock = { type: "coverage", items };
  const title = optionalText(record, "title", AGENT_UI_LIMITS.text);
  if (title) block.title = title;
  return { ok: true, block };
}

/** Dispatch a known block type, or `null` when the type is not in the vocabulary. */
function parseKnownBlock(value: Record<string, unknown>): BlockResult | null {
  switch (value.type) {
    case "text":
      return parseText(value);
    case "callout":
      return parseCallout(value);
    case "choice":
      return parseChoice(value);
    case "approval":
      return parseApproval(value);
    case "progress":
      return parseProgress(value);
    case "task_list":
      return parseTaskList(value);
    case "table":
      return parseTable(value);
    case "code":
      return parseCode(value);
    case "citation":
      return parseCitation(value);
    case "coverage":
      return parseCoverage(value);
    default:
      return null;
  }
}

function parseBlock(value: unknown): { block: AgentUiBlock; errors: string[] } {
  if (!isRecord(value)) {
    return { block: { type: "unsupported", blockType: "?" }, errors: ["a block was not an object"] };
  }
  const declaredType = typeof value.type === "string" ? value.type : "?";
  const parsed = parseKnownBlock(value);
  // Unknown type: keep it visible as a gap rather than dropping it silently.
  if (parsed === null) {
    return { block: { type: "unsupported", blockType: declaredType }, errors: [] };
  }
  if (!parsed.ok) {
    return {
      block: { type: "unsupported", blockType: declaredType },
      errors: [`${declaredType} block dropped: ${parsed.error}`],
    };
  }
  return { block: parsed.block, errors: [] };
}

export function parseAgentUi(value: unknown): AgentUiParseResult {
  if (!isRecord(value)) {
    return { ok: false, errors: ["the payload was not an object"] };
  }
  const version = value.version;
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1) {
    return { ok: false, errors: ["the payload had no usable version"] };
  }
  if (version > AGENT_UI_VERSION) {
    return {
      ok: false,
      errors: [`unsupported version ${version} (this build renders version ${AGENT_UI_VERSION})`],
    };
  }
  if (!Array.isArray(value.blocks)) {
    return { ok: false, errors: ["the envelope had no blocks array"] };
  }

  const errors: string[] = [];
  const blocks: AgentUiBlock[] = [];
  for (const raw of value.blocks.slice(0, AGENT_UI_LIMITS.blocks)) {
    const parsed = parseBlock(raw);
    errors.push(...parsed.errors);
    blocks.push(parsed.block);
  }
  if (value.blocks.length > AGENT_UI_LIMITS.blocks) {
    errors.push(`only the first ${AGENT_UI_LIMITS.blocks} blocks were rendered`);
  }

  return { ok: true, envelope: { version: AGENT_UI_VERSION, blocks }, errors };
}

/** The version of the load-bearing envelope for a payload that failed structurally. */
export const AGENT_UI_UNSUPPORTED_VERSION = AGENT_UI_VERSION;

/** Parse `unknown` and return `null` on any failure, for call sites that prefer silence. */
export function parseAgentUiOrNull(value: unknown): AgentUiEnvelope | null {
  const result = parseAgentUi(value);
  return result.ok ? result.envelope : null;
}
