"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type {
  AnalysisEditRequest,
  AssignmentAnalysis,
  AssignmentType,
  AcademicDomain,
} from "@/lib/types";

interface AnalysisState {
  id: string;
  analysis: AssignmentAnalysis | null;
  error: string;
  /** True until the first read for this assignment resolves. */
  loading: boolean;
  /** An action is in flight, or an analysis is being generated. */
  busy: boolean;
  actionError: string;
}

function messageFor(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback;
}

/** An assignment that was never analyzed is an empty state, not a failure. */
function isNotAnalyzed(caught: unknown): boolean {
  return caught instanceof ApiError && caught.code === "ANALYSIS_NOT_FOUND";
}

const INITIAL: AnalysisState = {
  id: "",
  analysis: null,
  error: "",
  loading: true,
  busy: false,
  actionError: "",
};

/**
 * The AI analysis of one assignment, plus every action a student may take on it.
 *
 * Read actions and mutations are deliberately separated: the server returns the
 * whole analysis from every review action, so accepting, rejecting, answering a
 * question, or correcting the classification updates the view from the
 * authoritative response instead of guessing locally. Nothing here writes to
 * the assignment specification; the AI can never edit the brief.
 *
 * `ANALYSIS_NOT_FOUND` simply means "not analyzed yet", so it is reported as an
 * empty state rather than an error.
 */
export function useAnalysis(assignmentId: string, refreshToken?: number | string) {
  const [state, setState] = useState<AnalysisState>(INITIAL);

  const applyResult = useCallback((analysis: AssignmentAnalysis) => {
    setState((previous) => ({
      ...previous,
      id: analysis.assignment_id,
      analysis,
      error: "",
      loading: false,
      busy: false,
      actionError: "",
    }));
  }, []);

  const failAction = useCallback((caught: unknown, fallback: string) => {
    setState((previous) => ({
      ...previous,
      busy: false,
      actionError: messageFor(caught, fallback),
    }));
  }, []);

  /** Every mutation goes through here so the busy flag and errors stay uniform. */
  const run = useCallback(
    async (operation: () => Promise<AssignmentAnalysis>, fallback: string) => {
      setState((previous) => ({ ...previous, busy: true, actionError: "" }));
      try {
        applyResult(await operation());
      } catch (caught) {
        failAction(caught, fallback);
      }
    },
    [applyResult, failAction],
  );

  const refresh = useCallback(async () => {
    setState((previous) => ({ ...previous, loading: true, error: "" }));
    try {
      applyResult(await api.analysis(assignmentId, "latest"));
    } catch (caught) {
      if (isNotAnalyzed(caught)) {
        setState((previous) => ({ ...previous, analysis: null, loading: false, error: "" }));
        return;
      }
      setState((previous) => ({
        ...previous,
        loading: false,
        error: messageFor(caught, "Could not load the analysis."),
      }));
    }
  }, [assignmentId, applyResult]);

  useEffect(() => {
    let active = true;
    setState((previous) =>
      previous.id === assignmentId ? { ...previous, loading: true } : { ...INITIAL, id: assignmentId },
    );
    api.analysis(assignmentId, "latest").then(
      (analysis) => {
        if (active) applyResult(analysis);
      },
      (caught: unknown) => {
        if (!active) return;
        if (isNotAnalyzed(caught)) {
          setState((previous) => ({ ...previous, loading: false, analysis: null, error: "" }));
          return;
        }
        setState((previous) => ({
          ...previous,
          loading: false,
          error: messageFor(caught, "Could not load the analysis."),
        }));
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId, refreshToken, applyResult]);

  const analyze = useCallback(
    (options: { force?: boolean; userNotes?: string } = {}) =>
      run(
        () =>
          api.analyzeAssignment(assignmentId, {
            force: options.force ?? false,
            user_notes: options.userNotes ?? null,
          }),
        "The analysis could not be generated.",
      ),
    [assignmentId, run],
  );

  const accept = useCallback(
    (note?: string) =>
      run(() => {
        const id = state.analysis?.id;
        if (!id) throw new Error("No analysis to accept.");
        return api.acceptAnalysis(assignmentId, id, note);
      }, "The analysis could not be accepted."),
    [assignmentId, run, state.analysis?.id],
  );

  const reject = useCallback(
    (note?: string) =>
      run(() => {
        const id = state.analysis?.id;
        if (!id) throw new Error("No analysis to reject.");
        return api.rejectAnalysis(assignmentId, id, note);
      }, "The analysis could not be rejected."),
    [assignmentId, run, state.analysis?.id],
  );

  const answerQuestion = useCallback(
    (questionId: string, answer: string) =>
      run(() => {
        const id = state.analysis?.id;
        if (!id) throw new Error("No analysis to answer in.");
        return api.answerQuestion(assignmentId, id, questionId, answer);
      }, "The answer could not be saved."),
    [assignmentId, run, state.analysis?.id],
  );

  const dismissQuestion = useCallback(
    (questionId: string, reason?: string) =>
      run(() => {
        const id = state.analysis?.id;
        if (!id) throw new Error("No analysis to update.");
        return api.dismissQuestion(assignmentId, id, questionId, reason);
      }, "The question could not be dismissed."),
    [assignmentId, run, state.analysis?.id],
  );

  const correct = useCallback(
    (input: Omit<AnalysisEditRequest, "note">) =>
      run(() => {
        const id = state.analysis?.id;
        if (!id) throw new Error("No analysis to correct.");
        return api.editAnalysis(assignmentId, id, input);
      }, "The correction could not be saved."),
    [assignmentId, run, state.analysis?.id],
  );

  const setTypes = useCallback(
    (types: AssignmentType[]) => correct({ types }),
    [correct],
  );
  const setDomains = useCallback(
    (domains: AcademicDomain[]) => correct({ domains }),
    [correct],
  );

  const current = state.id === assignmentId ? state : INITIAL;

  return {
    analysis: current.analysis,
    loading: current.loading,
    busy: current.busy,
    error: current.error,
    actionError: current.actionError,
    isStale: current.analysis?.is_stale ?? false,
    /** True once a student has accepted or rejected the analysis. */
    isReviewed: (current.analysis?.status ?? "PENDING") !== "PENDING",
    refresh,
    analyze,
    accept,
    reject,
    answerQuestion,
    dismissQuestion,
    correct,
    setTypes,
    setDomains,
  };
}
