"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { PlanningRun, RegenerateScope, WorkPlan } from "@/lib/planning-types";

interface PlanState {
  assignmentId: string;
  plan: WorkPlan | null;
  /** The newest attempts, newest first. Telemetry, not reasoning. */
  runs: PlanningRun[];
  loading: boolean;
  busy: null | "generate" | "regenerate" | "approve";
  /** A failure to read. Distinct from a failure to act. */
  error: string;
  actionError: string;
}

const INITIAL: PlanState = {
  assignmentId: "",
  plan: null,
  runs: [],
  loading: true,
  busy: null,
  error: "",
  actionError: "",
};

/** A failure worth showing the student, with the server's wording. */
function messageFor(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError) return caught.message;
  return fallback;
}

/**
 * The plan for one assignment, plus the actions a student may take on it.
 *
 * Mirrors `useAnalysis` deliberately: reads and mutations are separate, the
 * server's response is authoritative after every action, and an error leaves
 * the last good plan on screen rather than blanking it. Losing a rendered plan
 * because a *regeneration* failed would be a poor trade -- the student still has
 * the plan they were reading.
 *
 * A null plan is an empty state, not a failure: an assignment that was never
 * planned has nothing wrong with it.
 */
export function usePlan(assignmentId: string) {
  const [state, setState] = useState<PlanState>(INITIAL);

  const applyPlan = useCallback((plan: WorkPlan | null) => {
    setState((previous) => ({
      ...previous,
      plan,
      loading: false,
      busy: null,
      error: "",
      actionError: "",
    }));
  }, []);

  /** Re-read the plan and its recent attempts together. */
  const read = useCallback(
    async (id: string) => {
      const [plan, history] = await Promise.all([
        api.plan(id),
        // Telemetry is a nice-to-have; a failure to read it must not take the
        // plan down with it.
        api.planningRuns(id, 1, 5).catch(() => null),
      ]);
      setState((previous) => ({
        ...previous,
        assignmentId: id,
        plan,
        runs: history?.items ?? previous.runs,
        loading: false,
        error: "",
      }));
    },
    [],
  );

  useEffect(() => {
    let active = true;
    setState((previous) =>
      previous.assignmentId === assignmentId
        ? { ...previous, loading: true, error: "" }
        : { ...INITIAL, assignmentId },
    );
    read(assignmentId).then(
      () => {
        if (active) setState((previous) => ({ ...previous, loading: false }));
      },
      (caught: unknown) => {
        if (!active) return;
        setState((previous) => ({
          ...previous,
          loading: false,
          error: messageFor(caught, "The plan could not be loaded."),
        }));
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId, read]);

  /** Every mutation returns the whole plan, so the view follows the server. */
  const run = useCallback(
    async (
      busy: NonNullable<PlanState["busy"]>,
      operation: () => Promise<WorkPlan>,
      fallback: string,
    ) => {
      setState((previous) => ({ ...previous, busy, actionError: "" }));
      try {
        const plan = await operation();
        applyPlan(plan);
        // The run list is now stale: an attempt just happened.
        void read(assignmentId).catch(() => undefined);
      } catch (caught) {
        setState((previous) => ({
          ...previous,
          busy: null,
          actionError: messageFor(caught, fallback),
        }));
      }
    },
    [applyPlan, assignmentId, read],
  );

  const generate = useCallback(
    (force = false) =>
      run("generate", () => api.generatePlan(assignmentId, { force }), "The plan could not be generated."),
    [assignmentId, run],
  );

  const regenerate = useCallback(
    (scope: RegenerateScope) =>
      run(
        "regenerate",
        () => api.regeneratePlan(assignmentId, { scope, force: true }),
        "The plan could not be regenerated.",
      ),
    [assignmentId, run],
  );

  const approve = useCallback(() => {
    const id = state.plan?.id;
    if (!id) return Promise.resolve();
    return run("approve", () => api.approvePlan(assignmentId, id), "The plan could not be approved.");
  }, [assignmentId, run, state.plan?.id]);

  const current = state.assignmentId === assignmentId ? state : INITIAL;
  const plan = current.plan;

  return {
    plan,
    runs: current.runs,
    loading: current.loading,
    busy: current.busy,
    error: current.error,
    actionError: current.actionError,
    isApproved: plan?.status === "APPROVED",
    isStale: plan?.is_stale ?? false,
    /** Blocked when the server would refuse: approved plans and stale plans. */
    canApprove: Boolean(plan) && !current.busy && plan?.status !== "APPROVED" && !plan?.is_stale,
    lastRun: current.runs[0] ?? null,
    generate,
    regenerate,
    approve,
    refresh: () => read(assignmentId),
  };
}
