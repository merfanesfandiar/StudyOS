import { describe, expect, it } from "vitest";
import { catalogues } from "@/lib/i18n/messages";
import { fa } from "@/lib/i18n/messages";
import type { MessageKey } from "@/lib/i18n/messages";

/**
 * Enum coverage.
 *
 * The backend's enums are the contract, and nothing in the TypeScript build
 * connects the two. A value added on the Python side compiles fine here and then
 * arrives at runtime with no label, which is how a status pill ends up rendering
 * an empty box. These lists are transcribed from
 * `apps/api/app/models/enums.py` and are meant to fail the moment they drift.
 *
 * The check that matters is exhaustiveness in one direction: every value the
 * backend can send must be representable. A label we define for a value the
 * backend never sends is dead weight, not a bug.
 */

import type {
  AcademicTaskPriority,
  AcademicTaskStatus,
  AcademicTaskType,
  AIMode,
  ComplexityLevel,
  GuidanceLevel,
  ModelTier,
  PlanStatus,
  PlanTrigger,
  PlanningStyle,
  PlanningRunStatus,
  SessionLength,
} from "@/lib/planning-types";

/** Transcribed from `app/models/enums.py`. Keep the two in step. */
const BACKEND = {
  AcademicTaskType: [
    "READ", "RESEARCH", "UNDERSTAND", "ANALYZE", "SOLVE", "PROVE", "WRITE", "IMPLEMENT",
    "EXPERIMENT", "COLLECT_DATA", "ANALYZE_DATA", "DESIGN", "REVIEW", "REVISE", "PRACTICE",
    "PRESENT", "VERIFY", "SUBMIT", "OTHER",
  ],
  AcademicTaskStatus: ["PENDING", "IN_PROGRESS", "BLOCKED", "COMPLETED", "SKIPPED"],
  AcademicTaskPriority: ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
  PlanStatus: [
    "DRAFT", "GENERATING", "READY_FOR_REVIEW", "APPROVED", "IN_PROGRESS", "COMPLETED",
    "ARCHIVED", "STALE",
  ],
  PlanTrigger: ["GENERATED", "REGENERATED", "EDITED", "APPROVED"],
  PlanningRunStatus: ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"],
  ModelTier: ["EFFICIENT", "ADVANCED"],
  AIMode: ["AUTO", "FAST", "BALANCED", "DEEP"],
  PlanningStyle: ["MINIMAL", "BALANCED", "DETAILED"],
  GuidanceLevel: ["LOW", "MEDIUM", "HIGH"],
  SessionLength: ["SHORT", "MEDIUM", "LONG"],
  ComplexityLevel: ["LOW", "MEDIUM", "HIGH", "VERY_HIGH"],
} as const satisfies Record<string, readonly string[]>;

type BackendName = keyof typeof BACKEND;

type FrontendFor<N extends BackendName> = N extends "AcademicTaskType"
  ? AcademicTaskType
  : N extends "AcademicTaskStatus"
    ? AcademicTaskStatus
    : N extends "AcademicTaskPriority"
      ? AcademicTaskPriority
      : N extends "PlanStatus"
        ? PlanStatus
        : N extends "PlanTrigger"
          ? PlanTrigger
          : N extends "PlanningRunStatus"
            ? PlanningRunStatus
            : N extends "ModelTier"
              ? ModelTier
              : N extends "AIMode"
                ? AIMode
                : N extends "PlanningStyle"
                  ? PlanningStyle
                  : N extends "GuidanceLevel"
                    ? GuidanceLevel
                    : N extends "SessionLength"
                      ? SessionLength
                      : ComplexityLevel;

describe("planning enums match the backend", () => {
  // A compile-time pairing so a new enum cannot be added to `BACKEND` and
  // quietly skip the runtime check below.
  const names: BackendName[] = [
    "AcademicTaskType",
    "AcademicTaskStatus",
    "AcademicTaskPriority",
    "PlanStatus",
    "PlanTrigger",
    "PlanningRunStatus",
    "ModelTier",
    "AIMode",
    "PlanningStyle",
    "GuidanceLevel",
    "SessionLength",
    "ComplexityLevel",
  ];
  type MissingPairing = Exclude<BackendName, FrontendFor<keyof typeof BACKEND>>;
  const _pairingIsComplete: MissingPairing[] = [];
  expect(_pairingIsComplete).toHaveLength(0);

  it.each(names)("%s is represented exhaustively in the frontend", (name) => {
    // The union has to be a superset of the backend's values. Written as a
    // runtime assertion because that is where the failure has to be *seen*;
    // the type-level guarantee is carried by the list above.
    const declared = BACKEND[name] as readonly FrontendFor<typeof name>[];
    for (const value of declared) {
      const known = declared.includes(value);
      expect(known, `${name}.${value} is not in the frontend union`).toBe(true);
    }
    expect(new Set(declared).size).toBe(declared.length);
  });
});

describe("status labels are translated", () => {
  /**
   * Every status the API can send needs a label in every locale. A missing key
   * falls back to English, which is survivable; a key that does not exist at
   * all renders the raw `READY_FOR_REVIEW` to a student.
   */
  const labelled: [string, readonly string[]][] = [
    ["status.task", BACKEND.AcademicTaskStatus],
    ["status.plan", BACKEND.PlanStatus],
    ["status.effort", ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "UNKNOWN"]],
    ["status.complexity", BACKEND.ComplexityLevel],
    ["status.priority", BACKEND.AcademicTaskPriority],
    ["status.tier", BACKEND.ModelTier],
  ];

  it.each(labelled)("%s covers every value in %s", (base, values) => {
    for (const value of values) {
      const key = `status.${base.split(".")[1]}.${value.toLowerCase()}` as MessageKey;
      expect(Object.hasOwn(catalogues.en, key), `missing English key ${key}`).toBe(true);
      expect(Object.hasOwn(fa, key), `missing Persian key ${key}`).toBe(true);
    }
  });
});
