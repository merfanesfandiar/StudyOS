import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary from "@/app/(app)/error";
import { renderWithPreferences } from "./render";

/**
 * The workspace error boundary is a regular client component, so it can be
 * tested for what matters: it is translated, and "Try again" really retries.
 * The route-level wiring (Next swapping it in place of a crashed page) is the
 * framework's job and is exercised by the framework, not this test.
 */

afterEach(() => {
  cleanup();
  window.localStorage.removeItem("studyos.locale");
});

describe("(app) error boundary", () => {
  it("shows a recoverable, translated message instead of the crash", async () => {
    renderWithPreferences(<ErrorBoundary error={new Error("boom")} retry={() => {}} />);

    expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    // The failed page's internals stay hidden: no stack trails leak to a student.
    expect(screen.queryByText(/boom/)).not.toBeInTheDocument();
  });

  it("retries when asked", () => {
    const retry = vi.fn();
    renderWithPreferences(<ErrorBoundary error={new Error("boom")} retry={retry} />);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("speaks Persian to a Persian reader", () => {
    window.localStorage.setItem("studyos.locale", "fa");
    renderWithPreferences(<ErrorBoundary error={new Error("boom")} retry={() => {}} />);

    expect(screen.getByRole("heading", { name: "خطایی رخ داد" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تلاش دوباره" })).toBeInTheDocument();
  });
});