"use client";

import { useSyncExternalStore } from "react";
import type { AssignmentStatus } from "@/lib/types";
import { statusLabel } from "@/lib/format";

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

export function StatusBadge({ status }: { status: AssignmentStatus }) {
  const styles: Record<AssignmentStatus, string> = {
    DRAFT: "bg-slate-100 text-slate-700 ring-slate-200",
    ACTIVE: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    COMPLETED: "bg-blue-50 text-blue-700 ring-blue-200",
    ARCHIVED: "bg-amber-50 text-amber-800 ring-amber-200",
  };
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${styles[status]}`}
    >
      {statusLabel(status)}
    </span>
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
