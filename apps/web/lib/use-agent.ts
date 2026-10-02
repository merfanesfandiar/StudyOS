"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  isAgentRunActive,
  isAgentRunFinished,
  pendingAgentCheckpoint,
  type AgentCapabilities,
  type AgentRun,
  type AgentRunCreateInput,
  type AgentRunDetail,
  type RecoveryReport,
} from "@/lib/agent-types";
import { errorMessage } from "@/lib/error-message";
import type { MessageKey } from "@/lib/i18n/messages";
import type { Translate } from "@/lib/i18n/translate";

interface AgentState {
  assignmentId: string;
  run: AgentRunDetail | null;
  runs: AgentRun[];
  capabilities: AgentCapabilities | null;
  loading: boolean;
  busy: AgentAction | null;
  /** A failure to read. Distinct from a failure to act. */
  error: string;
  actionError: string;
  recovery: RecoveryReport | null;
}

/** One in-flight request. Rendered as the disabled state of a control. */
type AgentAction =
  | "create"
  | "start"
  | "pause"
  | "resume"
  | "cancel"
  | "resolve"
  | "recover";

/**
 * Keep a capability list only if it actually looks like one.
 *
 * Cheap shape check rather than a schema validator: this data is rendered, not
 * executed, and the cost of being wrong here is a missing disclosure rather than
 * a wrong action. Anything unrecognised becomes "unavailable", which the panel
 * already handles.
 */
function validCapabilities(value: AgentCapabilities | null): AgentCapabilities | null {
  if (!value) return null;
  const ok =
    Array.isArray(value.absent_capabilities) &&
    Array.isArray(value.tools) &&
    Array.isArray(value.modes);
  return ok ? value : null;
}

const INITIAL: AgentState = {
  assignmentId: "",
  run: null,
  runs: [],
  capabilities: null,
  loading: true,
  busy: null,
  error: "",
  actionError: "",
  recovery: null,
};

/**
 * The agent runtime for one assignment, plus the actions a student may take.
 *
 * Follows `usePlan` in the ways that matter: reads and mutations are separate,
 * the server's response is authoritative after every action, and a failed
 * action leaves the last good run on screen. That last point is worth the
 * repetition here — a run mid-flight is expensive in effort as well as money,
 * and blanking the workspace because a *pause* failed would be a poor trade.
 *
 * The view never infers a run's state. It reads `paused_reason`,
 * `awaiting_checkpoint_id` and `can_resume` from the server, because the
 * difference between "waiting on you" and "merely slow" is the sort of thing
 * that must not be guessed in a UI.
 */
export function useAgent(assignmentId: string, t: Translate) {
  const [state, setState] = useState<AgentState>(INITIAL);

  const applyRun = useCallback((run: AgentRunDetail | null) => {
    setState((previous) => ({
      ...previous,
      run,
      loading: false,
      busy: null,
      error: "",
      actionError: "",
    }));
  }, []);

  /** Re-read the newest run, its history, and the capability boundary. */
  const read = useCallback(
    async (id: string) => {
      const [runs, capabilities] = await Promise.all([
        api.agentRuns(id),
        // The capability list is static per deployment, and it is a
        // nice-to-have: if it is missing or malformed the workspace must still
        // work. `.catch` alone is not enough -- a 200 with an unexpected body
        // would otherwise reach the panel and crash it, taking the whole
        // assignment page with it.
        api.agentCapabilities(id).catch(() => null).then(validCapabilities),
      ]);
      const newest = runs.items[0] ?? null;
      const detail = newest ? await api.agentRun(id, newest.id).catch(() => null) : null;
      setState((previous) => ({
        ...previous,
        assignmentId: id,
        runs: runs.items,
        capabilities,
        // Keep the richer payload when a refresh races with an action; a null
        // would blank a workspace the student is reading.
        run: detail ?? previous.run ?? null,
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
          error: errorMessage(caught, t, "agent.loadFailed"),
        }));
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId, read, t]);

  /** Every mutation returns the whole run, so the view follows the server. */
  const run = useCallback(
    async (
      busy: AgentAction,
      operation: () => Promise<AgentRunDetail>,
      fallback: MessageKey,
    ) => {
      setState((previous) => ({ ...previous, busy, actionError: "", recovery: null }));
      try {
        applyRun(await operation());
        // The history just changed. A failure to refresh it is not worth
        // interrupting the student over, so it is swallowed.
        void read(assignmentId).catch(() => undefined);
      } catch (caught) {
        setState((previous) => ({
          ...previous,
          busy: null,
          actionError: errorMessage(caught, t, fallback),
        }));
      }
    },
    [applyRun, assignmentId, read, t],
  );

  const create = useCallback(
    (input: AgentRunCreateInput = {}) => {
      let created: AgentRun | null = null;
      return run(
        "create",
        async () => {
          created = await api.createAgentRun(assignmentId, input);
          return api.agentRun(assignmentId, created.id);
        },
        "agent.createFailed",
      ).then(() => created);
    },
    [assignmentId, run],
  );

  const act = useCallback(
    (
      busy: Extract<AgentAction, "start" | "pause" | "resume" | "cancel">,
      operation: (runId: string) => Promise<AgentRunDetail>,
      fallback: MessageKey,
    ) => {
      const runId = state.run?.id;
      if (!runId) return Promise.resolve();
      return run(busy, () => operation(runId), fallback);
    },
    [run, state.run?.id],
  );

  const start = useCallback(
    () => act("start", (id) => api.startAgentRun(assignmentId, id), "agent.startFailed"),
    [act, assignmentId],
  );
  const pause = useCallback(
    (note?: string) =>
      act("pause", (id) => api.pauseAgentRun(assignmentId, id, note), "agent.pauseFailed"),
    [act, assignmentId],
  );
  const resume = useCallback(
    (note?: string) =>
      act("resume", (id) => api.resumeAgentRun(assignmentId, id, note), "agent.resumeFailed"),
    [act, assignmentId],
  );
  const cancel = useCallback(
    (note?: string) =>
      act("cancel", (id) => api.cancelAgentRun(assignmentId, id, note), "agent.cancelFailed"),
    [act, assignmentId],
  );

  const answer = useCallback(
    async (
      checkpointId: string,
      input: { response?: string; selected_option?: string; approved?: boolean; retry?: boolean },
    ) => {
      const runId = state.run?.id;
      if (!runId) return;
      await run(
        "resolve",
        () => api.resolveAgentCheckpoint(assignmentId, runId, checkpointId, input),
        "agent.resolveFailed",
      );
    },
    [assignmentId, run, state.run?.id],
  );

  /**
   * Reclaim runs abandoned by a crash or a closed laptop.
   *
   * The report is kept in state rather than thrown away, because "I reclaimed 2
   * runs" is information a student wants after clicking, not a flash of text.
   */
  const recover = useCallback(async () => {
    setState((previous) => ({ ...previous, busy: "recover", actionError: "", recovery: null }));
    try {
      const report = await api.recoverAgentRuns(assignmentId);
      setState((previous) => ({ ...previous, busy: null, recovery: report }));
      await read(assignmentId);
    } catch (caught) {
      setState((previous) => ({
        ...previous,
        busy: null,
        actionError: errorMessage(caught, t, "agent.recoverFailed"),
      }));
    }
  }, [assignmentId, read, t]);

  const current = state.assignmentId === assignmentId ? state : INITIAL;
  const runDetail = current.run;
  const status = runDetail?.status ?? null;

  return {
    run: runDetail,
    runs: current.runs,
    capabilities: current.capabilities,
    loading: current.loading,
    busy: current.busy,
    error: current.error,
    actionError: current.actionError,
    recovery: current.recovery,
    /** The question being asked right now, or null. */
    pendingCheckpoint: pendingAgentCheckpoint(runDetail),
    isActive: status !== null && isAgentRunActive(status),
    isFinished: status !== null && isAgentRunFinished(status),
    isWaiting: status === "WAITING_FOR_USER" || status === "BLOCKED",
    /** Nothing to act on until a run exists. */
    hasRun: Boolean(runDetail),
    create,
    start,
    pause,
    resume,
    cancel,
    answer,
    recover,
    refresh: () => read(assignmentId),
  };
}