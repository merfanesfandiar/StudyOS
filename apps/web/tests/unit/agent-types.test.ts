import { describe, expect, it } from "vitest";
import { isAgentRunSettled } from "@/lib/agent-types";

/**
 * "Settled" describes the event log, not the run's usefulness.
 *
 * The SSE endpoint ends the stream on this same set, so the workspace can read
 * a settled log once. A run parked on a student decision is explicitly not
 * settled: answering it writes more events to the same log, and treating it as
 * finished froze the activity rail at the first checkpoint.
 */
describe("isAgentRunSettled", () => {
  it("treats terminal statuses as settled", () => {
    for (const status of ["COMPLETED", "FAILED", "CANCELLED", "BLOCKED", "PAUSED"] as const) {
      expect(isAgentRunSettled(status)).toBe(true);
    }
  });

  it("does not treat a run waiting for the student as settled", () => {
    expect(isAgentRunSettled("WAITING_FOR_USER")).toBe(false);
  });

  it("does not treat a run that has not started (or is running) as settled", () => {
    for (const status of ["CREATED", "STARTING", "RUNNING"] as const) {
      expect(isAgentRunSettled(status)).toBe(false);
    }
  });
});
