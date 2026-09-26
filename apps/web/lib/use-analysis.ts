"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type {
  AssignmentAnalysis,
  AssignmentType,
  ClassifiedDomain,
  ClassifiedType,
  EvaluationAnalysis,
  NormalizedRequirement,
  Objective,
  ScopeAnalysis,
  SourceKind,
} from "@/lib/types";
import { assignmentTypeLabel, sourceKindLabel } from "@/lib/format";

interface AnalysisState {
  data: AssignmentAnalysis | null;
  loading: boolean;
  error: string | null;
  /** True when the assignment has at least one analysis that has been reviewed or reviewed-pending. */
  reviewed: boolean;
}

export function useAnalysis(assignmentId: string): AnalysisState {
  const [state, setState] = useState<AnalysisState>({
    data: null,
    loading: true,
    error: "",
    reviewed: false,
  });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const result = await api.analysis(assignmentId, "latest");
      setState({
        data: result,
        loading: false,
        error: null,
        reviewed: result.status !== "PENDING",
      });
    } catch (caught: unknown) {
      const msg =
        caught instanceof ApiError
          ? caught.message
          : "Could not load the analysis.";
      setState((s) => ({ ...s, loading: false, error: msg }));
    }
  }, [assignmentId]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = useCallback(() => {
    load();
  }, [load]);

  const hasType = useCallback(
    (type: AssignmentType) => {
      if (!state.data) return false;
      return state.data.assignment_types.some((t) => t.type === type);
    },
    [state.data],
  );

  const hasDomain = useCallback(
    (domain: ClassifiedDomain["domain"]) => {
      if (!state.data) return false;
      return state.data.academic_domains.some(
        (d) => d.domain === domain,
      );
    },
    [state.data],
  );

  const confidenceLabel = useCallback(
    (c: number) => {
      if (c >= 0.85) return "High";
      if (c >= 0.6) return "Moderate";
      if (c > 0) return "Low";
      return "Not reported";
    },
    [],
  );

  return {
    ...state,
    load,
    refresh,
    hasType,
    hasDomain,
    confidenceLabel,
    sourceKindLabel,
  };
}