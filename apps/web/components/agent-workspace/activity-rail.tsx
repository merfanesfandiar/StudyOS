"use client";

import { useState } from "react";
import type { Translate } from "@/lib/i18n/translate";

/**
 * The live activity rail: what the agent is doing right now, rendered from
 * persisted events only. No timers, no fabricated progress — an entry appears
 * because the backend wrote one. Technical metadata is behind a disclosure.
 */
export function ActivityRail({
  events,
  connected,
  t,
}: {
  events: {
    id: string;
    sequence: number;
    event_type: string;
    summary: string;
    severity: string | null;
    outcome: string | null;
    metadata_json: Record<string, unknown>;
    created_at: string | null;
  }[];
  connected: "idle" | "stream" | "poll";
  t: Translate;
}) {
  const [open, setOpen] = useState(true);
  const visible = events.slice(-30);

  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)]">
      <header className="flex items-center justify-between gap-2 px-4 py-2">
        <h3 className="text-sm font-semibold">{t("workspace.activity.title")}</h3>
        <div className="flex items-center gap-2 text-xs text-[var(--color-ink-subtle)]">
          <span
            className="inline-block size-1.5 rounded-full bg-[var(--color-positive)]"
            aria-hidden="true"
          />
          {t(
            `workspace.activity.${connected}` as "workspace.activity.stream" | "workspace.activity.poll" | "workspace.activity.idle",
          )}
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="rounded-md px-1.5 py-0.5 hover:bg-[var(--color-surface-sunken)]"
          >
            {open ? t("workspace.activity.hide") : t("workspace.activity.show")}
          </button>
        </div>
      </header>
      {open && (
        <ol className="max-h-64 space-y-1 overflow-y-auto border-t border-[var(--color-line)] px-4 py-2 text-sm">
          {visible.length === 0 && (
            <li className="text-[var(--color-ink-muted)]">{t("workspace.activity.empty")}</li>
          )}
          {visible.map((event) => (
            <li key={`${event.sequence}-${event.id}`} className="flex items-start gap-2">
              <span
                className={`mt-1 inline-block size-1.5 shrink-0 rounded-full ${
                  event.outcome === "FAILED" || event.severity === "ERROR"
                    ? "bg-[var(--color-critical)]"
                    : "bg-[var(--color-info)]"
                }`}
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="truncate">{event.summary}</p>
                <details>
                  <summary className="cursor-pointer text-xs text-[var(--color-ink-subtle)]">
                    {t("workspace.activity.details")}
                  </summary>
                  <p className="mt-1 font-mono text-xs text-[var(--color-ink-muted)]" dir="ltr">
                    {event.event_type}
                  </p>
                </details>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
