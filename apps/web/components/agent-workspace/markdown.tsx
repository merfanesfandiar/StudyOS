"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Safe markdown rendering for conversation messages.
 *
 * `react-markdown` maps markdown to React elements — there is no
 * `dangerouslySetInnerHTML` anywhere in this path, so markup that arrives in a
 * message is text, not executable content. Links get `rel="noreferrer
 * noopener"` and only http(s)/mailto schemes can be produced by markdown
 * syntax in the first place. Code blocks are pinned LTR: mixed-direction
 * content must not re-order program text.
 */

export function Markdown({ children }: { children: string }) {
  return (
    <div className="space-y-3 break-words text-[15px] leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="text-[var(--color-accent-ink)] underline decoration-[var(--color-line)] underline-offset-2 hover:decoration-[var(--color-accent-ink)]"
            >
              {children}
            </a>
          ),
          pre: ({ children }) => (
            <div dir="ltr" className="overflow-x-auto rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface-sunken)] p-3 text-left">
              <pre className="font-mono text-[13px] leading-relaxed">{children}</pre>
            </div>
          ),
          code: ({ children }) => (
            <code dir="ltr" className="rounded-md border border-[var(--color-line)] bg-[var(--color-surface-sunken)] px-1 py-0.5 font-mono text-[13px]">
              {children}
            </code>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto" dir="ltr">
              <table className="w-full border-collapse text-left text-[13px]">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-[var(--color-line)] bg-[var(--color-surface-sunken)] px-2 py-1.5 font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-[var(--color-line)] px-2 py-1.5 align-top">{children}</td>
          ),
          ul: ({ children }) => (
            <ul className="ms-5 list-disc space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="ms-5 list-decimal space-y-1">{children}</ol>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-s-2 border-[var(--color-line-strong)] ps-3 text-[var(--color-ink-muted)]">
              {children}
            </blockquote>
          ),
          h1: ({ children }) => (
            <h3 className="text-base font-semibold">{children}</h3>
          ),
          h2: ({ children }) => (
            <h3 className="text-base font-semibold">{children}</h3>
          ),
          h3: ({ children }) => <h4 className="text-sm font-semibold">{children}</h4>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
