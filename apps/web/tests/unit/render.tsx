/**
 * Test render helpers.
 *
 * The shared primitives in `components/ui.tsx` read their default labels from the
 * message catalogue, so they require a `PreferencesProvider` -- which the root
 * layout always supplies. A test that renders app UI without one is not
 * reproducing the app, and letting the provider fall back to English instead
 * would reintroduce exactly the silent untranslated string the catalogue is
 * typed to prevent.
 *
 * So the provider goes in the helper rather than in each test. A test that needs
 * a specific locale can render the node itself and wrap it.
 */

import { render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { PreferencesProvider } from "@/components/preferences-provider";

export function renderWithPreferences(ui: ReactElement) {
  const result = render(<PreferencesProvider>{ui}</PreferencesProvider>);
  // `rerender` is re-wrapped too. Returning the raw one would drop the provider
  // on the second render and fail with a "must be used inside" error that has
  // nothing to do with what the test was asserting.
  const { rerender } = result;
  return {
    ...result,
    rerender: (next: ReactElement) => rerender(<PreferencesProvider>{next}</PreferencesProvider>),
  };
}

/** For tests that need to inspect or wrap the tree themselves. */
export function withPreferences(children: ReactNode) {
  return <PreferencesProvider>{children}</PreferencesProvider>;
}
