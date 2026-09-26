"use client";

import { usePreferences } from "./preferences-provider";

/**
 * The skip link is the first thing a keyboard or screen-reader user reaches, and
 * it is in a layout, so it has to be a client component to read the catalogue.
 * It lives inside `PreferencesProvider` for exactly that reason: a skip link that
 * says "پرش به محتوا" on a Persian page and "Skip to content" on an English one
 * is a language bug in the first place.
 */
export function SkipLink() {
  const { t } = usePreferences();
  return (
    <a
      className="sr-only z-50 rounded-[var(--radius-control)] bg-[var(--color-accent)] px-4 py-2 font-semibold text-[var(--color-accent-ink)] focus:not-sr-only focus:fixed focus:start-4 focus:top-4"
      href="#main-content"
    >
      {t("app.skipToContent")}
    </a>
  );
}
