"use client";

import { useSyncExternalStore } from "react";
import type { AssignmentStatus, CheckStatus } from "@/lib/types";
import { CHECK_LABELS, statusLabel } from "@/lib/format";

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
        <h1 className="text-2xl font-bold tracking-tight text-slate-950 sm:text-3xl">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-slate-600">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

const STATUS_STYLES: Record<AssignmentStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-700 ring-slate-200",
  INCOMPLETE: "bg-orange-50 text-orange-800 ring-orange-200",
  READY_FOR_ANALYSIS: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  ANALYSIS_IN_PROGRESS: "bg-cyan-50 text-cyan-800 ring-cyan-200",
  ANALYZED: "bg-teal-50 text-teal-800 ring-teal-200",
  COMPLETED: "bg-blue-50 text-blue-700 ring-blue-200",
  ARCHIVED: "bg-amber-50 text-amber-800 ring-amber-200",
  // Rows migrated from the previous phase can still hold this value.
  ACTIVE: "bg-emerald-50 text-emerald-700 ring-emerald-200",
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
  PASS: "bg-emerald-100 text-emerald-800",
  WARNING: "bg-amber-100 text-amber-900",
  FAIL: "bg-red-100 text-red-800",
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
    score >= bar ? "bg-emerald-500" : score >= bar / 2 ? "bg-amber-500" : "bg-red-500";
  return (
    <div
      aria-label={`Readiness ${score} percent`}
      aria-valuemax={100}
      aria-valuemin={0}
      aria-valuenow={score}
      className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
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
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    info: "border-blue-200 bg-blue-50 text-blue-800",
  };
  return <div className={`rounded-xl border px-4 py-3 text-sm ${styles[tone]}`}>{children}</div>;
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center" role="status">
      <div className="flex items-center gap-3 text-sm font-medium text-slate-600">
        <span className="size-5 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" />
        {label}…
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
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function SubmitButton({
  pending,
  pendingLabel = "Working…",
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

  return (
    <button className={className} disabled={pending || disabled || !hydrated} type="submit">
      {pending ? pendingLabel : children}
    </button>
  );
}
