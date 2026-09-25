import { describe, expect, it } from "vitest";
import { formatDate, formatFileSize, statusLabel, toLocalDateTime, toUtcDateTime } from "@/lib/format";
import type { AssignmentStatus } from "@/lib/types";

const pad = (value: number) => String(value).padStart(2, "0");

function localWallClock(iso: string): string {
  const date = new Date(iso);
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("-") + `T${[pad(date.getHours()), pad(date.getMinutes())].join(":")}`;
}

describe("formatFileSize", () => {
  it.each([
    [0, "0 B"],
    [1, "1 B"],
    [1023, "1023 B"],
    [1024, "1.0 KB"],
    [1536, "1.5 KB"],
    [1024 * 1024 - 1, "1024.0 KB"],
    [1024 * 1024, "1.0 MB"],
    [2.5 * 1024 * 1024, "2.5 MB"],
  ])("formats %d bytes as %s", (bytes, expected) => {
    expect(formatFileSize(bytes)).toBe(expected);
  });
});

describe("statusLabel", () => {
  const cases: [AssignmentStatus, string][] = [
    ["DRAFT", "Draft"],
    ["ACTIVE", "Active"],
    ["COMPLETED", "Completed"],
    ["ARCHIVED", "Archived"],
  ];

  it.each(cases)("turns %s into %s", (status, expected) => {
    expect(statusLabel(status)).toBe(expected);
  });
});

describe("formatDate", () => {
  it.each([null, undefined, ""])("falls back for %s", (value) => {
    expect(formatDate(value)).toBe("No deadline");
  });

  it("formats a deadline as a medium date with a short time", () => {
    const value = "2026-03-04T15:30:00.000Z";
    const expected = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));

    expect(formatDate(value)).toBe(expected);
    expect(formatDate(value)).toContain("2026");
  });
});

describe("toLocalDateTime", () => {
  it("returns an empty string for a missing value", () => {
    expect(toLocalDateTime(null)).toBe("");
  });

  it("rewrites an instant into local wall clock time without a zone suffix", () => {
    const value = "2026-03-04T15:30:00.000Z";

    const result = toLocalDateTime(value);

    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(result).toBe(localWallClock(value));
  });
});

describe("toUtcDateTime", () => {
  it("returns null for a missing value", () => {
    expect(toUtcDateTime("")).toBeNull();
  });

  it("converts a local input value to an absolute utc instant", () => {
    const result = toUtcDateTime("2026-03-04T15:30");

    expect(result).toBe(new Date("2026-03-04T15:30").toISOString());
    expect(result).toMatch(/Z$/);
  });

  it("round-trips through toLocalDateTime without drift", () => {
    const value = "2026-03-04T15:30:00.000Z";

    expect(toUtcDateTime(toLocalDateTime(value))).toBe(value);
  });
});
