"use client";

import { useSyncExternalStore } from "react";
import type { AssignmentStatus, CheckStatus } from "@/lib/types";
import { CHECK_LABELS, statusLabel } from "@/lib/format";
import { usePreferences } from "./preferences-provider";

const subscribeToNothing = () => () => {};
const clientHydrated = () => true;
const serverHydrated = () => false;

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[var(--color-ink)] sm:text-3xl">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-[var(--color-ink-muted)]">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

const STATUS_STYLES: Record<AssignmentStatus, string> = {
  DRAFT: "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)] ring-[var(--color-line)]",
  INCOMPLETE: "bg-[var(--color-caution)] text-[var(--color-caution)] ring-[var(--color-caution)]",
  READY_FOR_ANALYSIS: "bg-[var(--color-positive-soft)] text-[var(--color-positive)] ring-[var(--color-positive)]",
  ANALYSIS_IN_PROGRESS: "bg-[var(--color-info)] text-[var(--color-info)] ring-[var(--color-info)]",
  ANALYZED: "bg-[var(--color-positive)] text-[var(--color-positive)] ring-[var(--color-positive)]",
  COMPLETED: "bg-[var(--color-info-soft)] text-[var(--color-info)] ring-[var(--color-info-soft)]",
  ARCHIVED: "bg-[var(--color-caution-soft)] text-[var(--color-caution)] ring-[var(--color-caution-soft)]",
  // Rows migrated from the previous phase can still hold this value.
  ACTIVE: "bg-[var(--color-positive-soft)] text-[var(--color-positive)] ring-[var(--color-positive)]",
};

export function StatusBadge({ status }: { status: AssignmentStatus }) {
  const styles = STATUS_STYLES;
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${styles[status]}`}
    >
      {statusLabel(status)}
    </span>
  );
}

const CHECK_STYLES: Record<CheckStatus, string> = {
  PASS: "bg-[var(--color-positive-soft)] text-[var(--color-positive)]",
  WARNING: "bg-[var(--color-caution-soft)] text-[var(--color-caution)]",
  FAIL: "bg-[var(--color-critical-soft)] text-[var(--color-critical)]",
};

export function CheckDot({ status }: { status: CheckStatus }) {
  return (
    <span
      aria-label={CHECK_LABELS[status]}
      className={`inline-flex size-2.5 shrink-0 rounded-full ${CHECK_STYLES[status]}`}
      title={CHECK_LABELS[status]}
    />
  );
}

export function ReadinessMeter({ score, bar = 90 }: { score: number; bar?: number }) {
  const tone =
    score >= bar ? "bg-[var(--color-positive)]" : score >= bar / 2 ? "bg-[var(--color-caution)]" : "bg-[var(--color-critical)]";
  return (
    <div
      aria-label={`Readiness ${score} percent`}
      aria-valuemax={100}
      aria-valuemin={0}
      aria-valuenow={score}
      className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-surface-sunken)]"
      role="progressbar"
    >
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(100, Math.max(0, score))}%` }} />
    </div>
  );
}

export function Alert({
  children,
  tone = "error",
}: {
  children: React.ReactNode;
  tone?: "error" | "success" | "info";
}) {
  const styles = {
    error: "border-[var(--color-critical-soft)] bg-[var(--color-critical-soft)] text-[var(--color-critical)]",
    success: "border-[var(--color-positive)] bg-[var(--color-positive-soft)] text-[var(--color-positive)]",
    info: "border-[var(--color-info-soft)] bg-[var(--color-info-soft)] text-[var(--color-info)]",
  };
  return <div className={`rounded-xl border px-4 py-3 text-sm ${styles[tone]}`}>{children}</div>;
}

export function LoadingState({ label }: { label?: string }) {
  const { t } = usePreferences();
  return (
    <div className="flex min-h-40 items-center justify-center" role="status">
      <div className="flex items-center gap-3 text-sm font-medium text-[var(--color-ink-muted)]">
        <span className="size-5 animate-spin rounded-full border-2 border-[var(--color-line-strong)] border-t-[var(--color-accent)]" />
        {label ?? t("common.loading")}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-[var(--color-line-strong)] bg-[var(--color-surface)] px-6 py-10 text-center">
      <h2 className="text-base font-semibold text-[var(--color-ink)]">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-[var(--color-ink-muted)]">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function SubmitButton({
  pending,
  pendingLabel,
  disabled = false,
  children,
  className = "btn-primary",
}: {
  pending: boolean;
  pendingLabel?: string;
  disabled?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const hydrated = useSyncExternalStore(subscribeToNothing, clientHydrated, serverHydrated);
  const { t } = usePreferences();

  return (
    <button className={className} disabled={pending || disabled || !hydrated} type="submit">
      {pending ? (pendingLabel ?? t("common.working")) : children}
    </button>
  );
}
