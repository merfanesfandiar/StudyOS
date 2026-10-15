"use client";

import { useState, type ReactNode } from "react";
import { usePreferences } from "@/components/preferences-provider";
import {
  type AgentUiApprovalBlock,
  type AgentUiBlock,
  type AgentUiCalloutBlock,
  type AgentUiChoiceBlock,
  type AgentUiCitationBlock,
  type AgentUiCodeBlock,
  type AgentUiCoverageBlock,
  type AgentUiEnvelope,
  type AgentUiProgressBlock,
  type AgentUiSubmission,
  type AgentUiTableBlock,
  type AgentUiTaskListBlock,
  type AgentUiTextBlock,
  type AgentUiTone,
  type AgentUiUnsupportedBlock,
} from "@/lib/agent-ui/blocks";

/**
 * The Dynamic Agent UI renderer.
 *
 * Every block is a fixed component. The agent chooses *which* block and fills in
 * its fields; it never chooses a component, a class name, or a script. That is
 * the whole safety argument, and it is the reason unknown block types render as
 * a named gap rather than being guessed at or executed.
 *
 * The dispatch below is a closed `switch` on purpose. A runtime-extensible
 * registry would let a payload name a renderer that does not exist in this
 * build; the vocabulary is closed by design, so the renderer is too -- and the
 * `never` return is the compiler checking that every block type has a case.
 */

interface BlockContext {
  disabled: boolean;
  /** `null` on a read-only surface: interactive blocks render inert. */
  onSubmit: ((submission: AgentUiSubmission) => void) | null;
}

const TONE_CLASS: Record<AgentUiTone, string> = {
  info: "border-[var(--color-info)] bg-[var(--color-info-soft)] text-[var(--color-info)]",
  success:
    "border-[var(--color-positive)] bg-[var(--color-positive-soft)] text-[var(--color-positive)]",
  warning:
    "border-[var(--color-caution)] bg-[var(--color-caution-soft)] text-[var(--color-caution)]",
  danger:
    "border-[var(--color-critical)] bg-[var(--color-critical-soft)] text-[var(--color-critical)]",
};

function TextBlock({ block }: { block: AgentUiTextBlock }) {
  const className =
    block.tone === "muted" ? "text-sm text-[var(--color-ink-muted)]" : "text-sm text-[var(--color-ink)]";
  return <p className={className}>{block.text}</p>;
}

function CalloutBlock({ block }: { block: AgentUiCalloutBlock }) {
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${TONE_CLASS[block.tone]}`} role="note">
      {block.title ? <p className="font-semibold">{block.title}</p> : null}
      <p className={block.title ? "mt-1" : ""}>{block.text}</p>
    </div>
  );
}

function ChoiceBlock({ block, ctx }: { block: AgentUiChoiceBlock; ctx: BlockContext }) {
  const { t } = usePreferences();
  const [selected, setSelected] = useState<string[]>([]);
  const [other, setOther] = useState("");

  return (
    <fieldset className="rounded-xl border border-[var(--color-line)] p-4">
      <legend className="px-1 text-sm font-medium text-[var(--color-ink)]">{block.prompt}</legend>
      {block.help ? <p className="mb-2 text-xs text-[var(--color-ink-muted)]">{block.help}</p> : null}
      {ctx.onSubmit === null ? (
        // Read-only: a static list, not disabled radios. A disabled radio reads
        // as "you may not answer this yet", which is a different claim.
        <ul className="space-y-2">
          {block.options.map((option) => (
            <li key={option.value} className="text-sm">
              <span className="font-medium text-[var(--color-ink)]">{option.label}</span>
              {option.description ? (
                <span className="block text-xs text-[var(--color-ink-subtle)]">{option.description}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <>
          <div className="space-y-2">
            {block.options.map((option) => (
              <label className="flex items-start gap-2 text-sm" key={option.value}>
                <input
                  checked={selected.includes(option.value)}
                  className="mt-1"
                  disabled={ctx.disabled}
                  name={block.id}
                  onChange={() => setSelected(toggleValue(block.multiple === true, selected, option.value))}
                  type={block.multiple === true ? "checkbox" : "radio"}
                  value={option.value}
                />
                <span>
                  <span className="font-medium text-[var(--color-ink)]">{option.label}</span>
                  {option.description ? (
                    <span className="block text-xs text-[var(--color-ink-subtle)]">
                      {option.description}
                    </span>
                  ) : null}
                </span>
              </label>
            ))}
          </div>
          {block.allow_other ? (
            <label className="mt-3 block text-sm">
              <span className="font-medium text-[var(--color-ink)]">{t("agentUi.other")}</span>
              <textarea
                className="mt-1 w-full rounded-lg border border-[var(--color-line-strong)] px-3 py-2 text-sm"
                disabled={ctx.disabled}
                onChange={(event) => setOther(event.target.value)}
                rows={2}
                value={other}
              />
            </label>
          ) : null}
          <button
            className="btn-secondary mt-3"
            disabled={ctx.disabled || (selected.length === 0 && other.trim().length === 0)}
            onClick={() =>
              ctx.onSubmit?.({ id: block.id, values: selected, other: other.trim() || undefined })
            }
            type="button"
          >
            {t("agentUi.submit")}
          </button>
        </>
      )}
    </fieldset>
  );
}

/** Radio semantics replace the selection; checkbox semantics toggle it. */
function toggleValue(multiple: boolean, current: string[], value: string): string[] {
  if (!multiple) return [value];
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}

function ApprovalBlock({ block, ctx }: { block: AgentUiApprovalBlock; ctx: BlockContext }) {
  const { t } = usePreferences();
  const interactive = ctx.onSubmit !== null;
  return (
    <div className="rounded-xl border border-[var(--color-line)] p-4">
      <p className="text-sm font-medium text-[var(--color-ink)]">{block.prompt}</p>
      {block.detail ? <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{block.detail}</p> : null}
      {interactive ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="btn-primary"
            disabled={ctx.disabled}
            onClick={() => ctx.onSubmit?.({ id: block.id, approved: true })}
            type="button"
          >
            {block.approve_label ?? t("agentUi.approve")}
          </button>
          <button
            className="btn-secondary"
            disabled={ctx.disabled}
            onClick={() => ctx.onSubmit?.({ id: block.id, approved: false })}
            type="button"
          >
            {block.reject_label ?? t("agentUi.reject")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ProgressBlock({ block }: { block: AgentUiProgressBlock }) {
  const { t, formatNumber } = usePreferences();
  const max = block.max ?? 100;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="font-medium text-[var(--color-ink)]">{block.label}</span>
        <span className="text-[var(--color-ink-muted)]">
          {t("agentUi.progressOf", { value: formatNumber(block.value), max: formatNumber(max) })}
        </span>
      </div>
      <progress aria-label={block.label} className="h-2 w-full" max={max} value={block.value} />
    </div>
  );
}

function TaskListBlock({ block }: { block: AgentUiTaskListBlock }) {
  return (
    <div className="space-y-2">
      {block.title ? <p className="text-sm font-medium text-[var(--color-ink)]">{block.title}</p> : null}
      <ul className="space-y-1">
        {block.items.map((item) => (
          <li
            className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--color-line)] px-3 py-2 text-sm"
            key={item.key}
          >
            <span className="font-mono text-xs text-[var(--color-ink-subtle)]">{item.key}</span>
            <span className="text-[var(--color-ink)]">{item.title}</span>
            <span className="ms-auto text-xs text-[var(--color-ink-muted)]">{item.status}</span>
            {item.note ? (
              <span className="w-full text-xs text-[var(--color-ink-subtle)]">{item.note}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function TableBlock({ block }: { block: AgentUiTableBlock }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-[var(--color-line)]">
      <table className="w-full border-collapse text-sm">
        {block.caption ? (
          <caption className="border-b border-[var(--color-line)] px-3 py-2 text-start text-xs text-[var(--color-ink-muted)]">
            {block.caption}
          </caption>
        ) : null}
        <thead>
          <tr>
            {block.columns.map((column) => (
              <th
                className={`border-b border-[var(--color-line-strong)] px-3 py-2 font-semibold text-[var(--color-ink)] ${
                  column.align === "end" ? "text-end" : "text-start"
                }`}
                key={column.key}
                scope="col"
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, index) => (
            // Rows carry no id, and this list never reorders on its own, so the
            // position is the identity.
            <tr key={index}>
              {block.columns.map((column) => (
                <td
                  className={`border-b border-[var(--color-line)] px-3 py-2 text-[var(--color-ink-muted)] ${
                    column.align === "end" ? "text-end" : "text-start"
                  }`}
                  key={column.key}
                >
                  {row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CodeBlock({ block }: { block: AgentUiCodeBlock }) {
  const { t } = usePreferences();
  return (
    <figure className="overflow-hidden rounded-xl border border-[var(--color-line)]">
      {block.title || block.language ? (
        <figcaption className="flex items-center justify-between gap-2 border-b border-[var(--color-line)] bg-[var(--color-surface-sunken)] px-3 py-2 text-xs text-[var(--color-ink-muted)]">
          <span className="font-medium text-[var(--color-ink)]">{block.title ?? t("agentUi.code")}</span>
          {block.language ? <span className="font-mono">{block.language}</span> : null}
        </figcaption>
      ) : null}
      <pre className="overflow-x-auto px-3 py-3 text-sm text-[var(--color-ink)]">
        <code>{block.code}</code>
      </pre>
    </figure>
  );
}

function CitationBlock({ block }: { block: AgentUiCitationBlock }) {
  const { t } = usePreferences();
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-[var(--color-ink)]">{block.title ?? t("agentUi.references")}</p>
      <ol className="list-decimal space-y-1 ps-5">
        {block.items.map((item, index) => (
          <li className="text-sm text-[var(--color-ink-muted)]" key={index}>
            {item.url ? (
              <a
                className="font-medium text-[var(--color-accent-hover)] underline underline-offset-2"
                href={item.url}
                rel="noreferrer noopener"
                target="_blank"
              >
                {item.label}
              </a>
            ) : (
              <span className="font-medium text-[var(--color-ink)]">{item.label}</span>
            )}
            {item.detail ? (
              <span className="block text-xs text-[var(--color-ink-subtle)]">{item.detail}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

function CoverageBlock({ block }: { block: AgentUiCoverageBlock }) {
  const { t } = usePreferences();
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-[var(--color-ink)]">
        {block.title ?? t("agentUi.coverage")}
      </p>
      <ul className="space-y-1">
        {block.items.map((item, index) => (
          <li className="flex items-start gap-2 text-sm" key={index}>
            {/* The glyph is decoration; the state is in the text beside it, so
                the meaning survives a screen reader and a greyscale print. */}
            <span
              aria-hidden="true"
              className={item.covered ? "text-[var(--color-positive)]" : "text-[var(--color-critical)]"}
            >
              {item.covered ? "✓" : "✕"}
            </span>
            <span className="text-[var(--color-ink)]">
              {item.label}
              <span className="sr-only">
                {item.covered ? ` (${t("agentUi.covered")})` : ` (${t("agentUi.notCovered")})`}
              </span>
              {item.detail ? (
                <span className="block text-xs text-[var(--color-ink-subtle)]">{item.detail}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function UnsupportedBlock({ block }: { block: AgentUiUnsupportedBlock }) {
  const { t } = usePreferences();
  return (
    <div
      className="rounded-xl border border-dashed border-[var(--color-line-strong)] bg-[var(--color-surface-sunken)] px-4 py-3 text-xs text-[var(--color-ink-muted)]"
      data-unsupported-block={block.blockType}
    >
      {t("agentUi.unsupported", { type: block.blockType })}
    </div>
  );
}

/** The registry: one entry per block type, checked exhaustively by TypeScript. */
function renderBlock(block: AgentUiBlock, ctx: BlockContext): ReactNode {
  switch (block.type) {
    case "text":
      return <TextBlock block={block} />;
    case "callout":
      return <CalloutBlock block={block} />;
    case "choice":
      return <ChoiceBlock block={block} ctx={ctx} />;
    case "approval":
      return <ApprovalBlock block={block} ctx={ctx} />;
    case "progress":
      return <ProgressBlock block={block} />;
    case "task_list":
      return <TaskListBlock block={block} />;
    case "table":
      return <TableBlock block={block} />;
    case "code":
      return <CodeBlock block={block} />;
    case "citation":
      return <CitationBlock block={block} />;
    case "coverage":
      return <CoverageBlock block={block} />;
    case "unsupported":
      return <UnsupportedBlock block={block} />;
  }
}

export function AgentUiView({
  envelope,
  onSubmit,
  disabled = false,
  errors = [],
}: {
  envelope: AgentUiEnvelope;
  /** Supplying this makes interactive blocks live. Omit it for a read-only view. */
  onSubmit?: (submission: AgentUiSubmission) => void;
  disabled?: boolean;
  /** Non-fatal validation problems, rendered rather than swallowed. */
  errors?: string[];
}) {
  const { t } = usePreferences();
  const ctx: BlockContext = { disabled, onSubmit: onSubmit ?? null };
  if (envelope.blocks.length === 0 && errors.length === 0) return null;
  return (
    <div className="space-y-3" data-testid="agent-ui">
      {envelope.blocks.map((block, index) => (
        // A block has no identity of its own beyond its type and position, and
        // this list is static once rendered.
        <div key={`${block.type}-${index}`}>{renderBlock(block, ctx)}</div>
      ))}
      {errors.length > 0 ? (
        <p className="text-xs text-[var(--color-ink-subtle)]" role="status">
          {t("agentUi.notice")}
        </p>
      ) : null}
    </div>
  );
}
