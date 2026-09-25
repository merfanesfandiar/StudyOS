"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { AssignmentSpecification, DependencyGraph } from "@/lib/types";

interface SpecificationState {
  id: string;
  specification: AssignmentSpecification | null;
  graph: DependencyGraph | null;
  error: string;
}

interface Loaded {
  specification: AssignmentSpecification;
  graph: DependencyGraph | null;
}

function messageFor(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback;
}

/** The graph is supporting detail, so its failure must not blank the editor. */
async function loadSpecification(assignmentId: string): Promise<Loaded> {
  const specification = await api.specification(assignmentId);
  let graph: DependencyGraph | null = null;
  try {
    graph = await api.dependencyGraph(assignmentId);
  } catch {
    graph = null;
  }
  return { specification, graph };
}

function toState(
  assignmentId: string,
  loaded: Loaded | null,
  error: string,
  previous: SpecificationState | null,
): SpecificationState {
  const sameAssignment = previous?.id === assignmentId;
  return {
    id: assignmentId,
    specification: loaded?.specification ?? (sameAssignment ? previous.specification : null),
    graph: loaded?.graph ?? (sameAssignment ? previous.graph : null),
    error,
  };
}

/**
 * One specification, one request.
 *
 * `GET /assignments/{id}/specification` returns every section plus the
 * readiness report and the summary, so the editor never assembles a
 * half-updated view from several calls. Sections mutate through the API and then
 * call `refresh`, which keeps the readiness report and every counter honest.
 *
 * State carries the assignment id it belongs to, so a route change shows a
 * loading state instead of the previous assignment's data.
 */
export function useSpecification(assignmentId: string) {
  const [state, setState] = useState<SpecificationState | null>(null);

  const refresh = useCallback(async () => {
    try {
      const loaded = await loadSpecification(assignmentId);
      setState((previous) => toState(assignmentId, loaded, "", previous));
    } catch (caught) {
      setState((previous) =>
        toState(assignmentId, null, messageFor(caught, "Could not load the specification."), previous),
      );
    }
  }, [assignmentId]);

  useEffect(() => {
    let active = true;
    loadSpecification(assignmentId).then(
      (loaded) => {
        if (active) setState(toState(assignmentId, loaded, "", null));
      },
      (caught: unknown) => {
        if (active) {
          setState(
            toState(assignmentId, null, messageFor(caught, "Could not load the specification."), null),
          );
        }
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId]);

  const current = state?.id === assignmentId ? state : null;
  return {
    specification: current?.specification ?? null,
    graph: current?.graph ?? null,
    loading: current === null,
    error: current?.error ?? "",
    refresh,
  };
}
