"use client";

import { usePreferences } from "./preferences-provider";
import { LOCALES, LOCALE_META } from "@/lib/i18n/locales";
import { THEMES, type Theme } from "@/lib/theme";

/**
 * Theme and language controls.
 *
 * Two details here are load-bearing:
 *
 * The theme control is a segmented radio group, not a button that cycles. A
 * cycling button has no way to communicate the available options, and a user on
 * a dark-mode laptop who wants to check what "system" currently resolves to has
 * no way to find out short of pressing the button three times.
 *
 * The icon-only button variant carries `aria-label` and `sr-only` text. An
 * unlabelled icon button is an unlabeled control to a screen reader, and
 * "three unlabeled buttons in a toolbar" is a genuinely unusable toolbar.
 */

const THEME_ICON: Record<Theme, string> = {
  light: "M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66l1.42-1.42M4.92 19.08l1.42-1.42m0-11.32L4.92 4.92m14.16 14.16l-1.42-1.42M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  dark: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z",
  system: "M4 5h16M4 12h16M4 19h16",
};

function Icon({ path }: { path: string }) {
  return (
    <svg
      aria-hidden="true"
      className="size-4 shrink-0"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={1.75}
      stroke="currentColor"
    >
      <path d={path} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme, t, effectiveTheme } = usePreferences();

  if (compact) {
    // A single control for tight spaces: flips between light and dark from
    // wherever you are, which is the common case. "system" is still reachable
    // from settings, so nothing is lost by not offering it in the toolbar.
    const next: Theme = effectiveTheme === "dark" ? "light" : "dark";
    return (
      <button
        aria-label={t("theme.toggle")}
        className="btn-ghost !min-h-9 !px-2"
        onClick={() => setTheme(next)}
        title={`${t("theme.label")}: ${t(`theme.${effectiveTheme}`)}`}
        type="button"
      >
        <Icon path={THEME_ICON[effectiveTheme]} />
      </button>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm font-semibold text-[var(--color-ink)]">
        {t("theme.label")}
      </legend>
      <div
        className="inline-flex rounded-[var(--radius-control)] border border-[var(--color-line)] bg-[var(--color-surface-sunken)] p-1"
        role="radiogroup"
      >
        {THEMES.map((option) => {
          const selected = theme === option;
          return (
            <label
              className={`flex cursor-pointer items-center gap-2 rounded-[calc(var(--radius-control)-2px)] px-3 py-1.5 text-sm font-medium transition ${
                selected
                  ? "bg-[var(--color-surface)] text-[var(--color-ink)] shadow-[var(--shadow-card)]"
                  : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
              }`}
              key={option}
            >
              <input
                checked={selected}
                className="sr-only"
                name="theme"
                onChange={() => setTheme(option)}
                type="radio"
                value={option}
              />
              <Icon path={THEME_ICON[option]} />
              {t(`theme.${option}`)}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = usePreferences();

  if (compact) {
    // The current language is always written in that language. A globe icon
    // with no label tells the user nothing about which language they are in,
    // and "EN" tells them nothing if they cannot read Latin.
    const meta = LOCALE_META[locale];
    return (
      <label className="btn-ghost !min-h-9 cursor-pointer !px-2" title={t("language.toggle")}>
        <span aria-hidden="true" className="text-sm font-semibold">
          {meta.label}
        </span>
        <select
          aria-label={t("language.toggle")}
          className="sr-only"
          onChange={(event) => setLocale(event.target.value as (typeof LOCALES)[number])}
          value={locale}
        >
          {LOCALES.map((option) => (
            <option key={option} value={option}>
              {LOCALE_META[option].label}
            </option>
          ))}
        </select>
      </label>
    );
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm font-semibold text-[var(--color-ink)]">
        {t("language.label")}
      </legend>
      <div
        className="inline-flex rounded-[var(--radius-control)] border border-[var(--color-line)] bg-[var(--color-surface-sunken)] p-1"
        role="radiogroup"
      >
        {LOCALES.map((option) => {
          const selected = locale === option;
          const meta = LOCALE_META[option];
          return (
            <label
              className={`flex cursor-pointer items-center gap-2 rounded-[calc(var(--radius-control)-2px)] px-3 py-1.5 text-sm font-medium transition ${
                selected
                  ? "bg-[var(--color-surface)] text-[var(--color-ink)] shadow-[var(--shadow-card)]"
                  : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
              }`}
              key={option}
            >
              <input
                checked={selected}
                className="sr-only"
                name="locale"
                onChange={() => setLocale(option)}
                type="radio"
                value={option}
              />
              <span>{meta.label}</span>
              {meta.dir === "rtl" && (
                // Advertise the direction rather than letting a left-to-right
                // reader assume the label is a mistake.
                <span className="text-xs text-[var(--color-ink-subtle)]">RTL</span>
              )}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
