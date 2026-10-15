"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import {
  isExecutionJobActive,
  type ExecutionCapabilities,
  type ExecutionCreateInput,
  type ExecutionJob,
  type ExecutionJobDetail,
} from "@/lib/execution-types";
import type { Translate } from "@/lib/i18n/translate";

/**
 * How often a live job is re-read while the panel is open.
 *
 * A queued job is worked on by a worker process the panel cannot see, so the
 * only way to show its progress is to ask. Two seconds is fast enough that a
 * short run feels responsive without turning an open tab into a load test; the
 * browser's own tab throttling handles the hidden case.
 */
const EXECUTION_POLL_INTERVAL_MS = 2_000;

interface ExecutionState {
  assignmentId: string;
  capabilities: ExecutionCapabilities | null;
  jobs: ExecutionJob[];
  selectedId: string | null;
  detail: ExecutionJobDetail | null;
  loading: boolean;
  busy: ExecutionAction | null;
  /** A failure to read. Distinct from a failure to act. */
  error: string;
  actionError: string;
}

/** One in-flight request, rendered as the disabled state of a control. */
type ExecutionAction = "submit" | "cancel";

/**
 * Shape-check a capability list before rendering it.
 *
 * Cheap rather than a schema validator: the data is rendered, not executed, and
 * the cost of being wrong is a missing disclosure rather than a wrong action.
 * Anything unrecognised becomes "unavailable", which the panel already handles.
 */
function validCapabilities(value: ExecutionCapabilities | null): ExecutionCapabilities | null {
  if (!value) return null;
  return Array.isArray(value.execution_types) ? value : null;
}

const INITIAL: ExecutionState = {
  assignmentId: "",
  capabilities: null,
  jobs: [],
  selectedId: null,
  detail: null,
  loading: true,
  busy: null,
  error: "",
  actionError: "",
};

/**
 * The execution plane for one assignment, plus the actions a student may take.
 *
 * Follows `useAgent` in the ways that matter: reads and mutations are separate,
 * the server's response is authoritative after every action, and a failed action
 * leaves the last good job on screen rather than blanking the workspace.
 */
export function useExecution(assignmentId: string, t: Translate) {
  const [state, setState] = useState<ExecutionState>(INITIAL);
  // Read inside callbacks without forcing them to depend on the selected id, so
  // a poll does not tear down and rebuild its timer every time the selection
  // changes.
  const selectedRef = useRef<string | null>(null);

  const read = useCallback(async (id: string, jobId: string | null) => {
    const [jobs, capabilities] = await Promise.all([
      api.executionJobs(id),
      // The capability list is static per deployment and a nice-to-have: if it
      // is missing or malformed the workspace must still work. `.catch` alone is
      // not enough -- a 200 with an unexpected body would otherwise reach the
      // panel and crash it.
      api.executionCapabilities().catch(() => null).then(validCapabilities),
    ]);
    const chosen = jobId ?? jobs.items[0]?.id ?? null;
    const detail = chosen ? await api.executionJob(id, chosen).catch(() => null) : null;
    selectedRef.current = chosen;
    setState((previous) => ({
      ...previous,
      assignmentId: id,
      jobs: jobs.items,
      capabilities,
      selectedId: chosen,
      // Keep the richer payload when a refresh races with an action; a null
      // would blank a workspace the student is reading.
      detail: detail ?? (chosen === previous.selectedId ? previous.detail : null),
      loading: false,
      error: "",
    }));
  }, []);

  useEffect(() => {
    let active = true;
    selectedRef.current = null;
    setState((previous) =>
      previous.assignmentId === assignmentId
        ? { ...previous, loading: true, error: "" }
        : { ...INITIAL, assignmentId },
    );
    read(assignmentId, null).then(
      () => {
        if (active) setState((previous) => ({ ...previous, loading: false }));
      },
      (caught: unknown) => {
        if (!active) return;
        setState((previous) => ({
          ...previous,
          loading: false,
          error: errorMessage(caught, t, "execution.loadFailed"),
        }));
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId, read, t]);

  const current = state.assignmentId === assignmentId ? state : INITIAL;

  /**
   * Re-read a live job on a timer.
   *
   * Only while something is moving: queued, running or cleaning up. A terminal
   * job changes only when the student acts, and every action already re-reads,
   * so polling it would be traffic for nothing.
   */
  const anyActive = current.jobs.some((job) => isExecutionJobActive(job.status));
  const pollRef = useRef(false);
  useEffect(() => {
    if (!anyActive) return;
    let disposed = false;
    const tick = () => {
      if (pollRef.current || disposed) return;
      pollRef.current = true;
      void read(assignmentId, selectedRef.current)
        .catch(() => undefined)
        .finally(() => {
          pollRef.current = false;
        });
    };
    const timer = window.setInterval(tick, EXECUTION_POLL_INTERVAL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [assignmentId, anyActive, read]);

  const submit = useCallback(
    async (input: ExecutionCreateInput) => {
      setState((previous) => ({ ...previous, busy: "submit", actionError: "" }));
      try {
        const job = await api.createExecution(assignmentId, input);
        await read(assignmentId, job.id);
      } catch (caught) {
        setState((previous) => ({
          ...previous,
          actionError: errorMessage(caught, t, "execution.submitFailed"),
        }));
      } finally {
        setState((previous) => ({ ...previous, busy: null }));
      }
    },
    [assignmentId, read, t],
  );

  const cancel = useCallback(
    async (reason?: string) => {
      const jobId = selectedRef.current;
      if (!jobId) return;
      setState((previous) => ({ ...previous, busy: "cancel", actionError: "" }));
      try {
        await api.cancelExecution(assignmentId, jobId, reason);
        await read(assignmentId, jobId);
      } catch (caught) {
        setState((previous) => ({
          ...previous,
          actionError: errorMessage(caught, t, "execution.cancelFailed"),
        }));
      } finally {
        setState((previous) => ({ ...previous, busy: null }));
      }
    },
    [assignmentId, read, t],
  );

  const select = useCallback(
    (jobId: string) => {
      void read(assignmentId, jobId).catch(() => undefined);
    },
    [assignmentId, read],
  );

  const detail = current.detail;
  const selectedStatus = detail?.job.status ?? null;

  return {
    capabilities: current.capabilities,
    jobs: current.jobs,
    detail,
    selectedId: current.selectedId,
    loading: current.loading,
    busy: current.busy,
    error: current.error,
    actionError: current.actionError,
    isActive: selectedStatus !== null && isExecutionJobActive(selectedStatus),
    select,
    submit,
    cancel,
    refresh: () => read(assignmentId, selectedRef.current),
  };
}
