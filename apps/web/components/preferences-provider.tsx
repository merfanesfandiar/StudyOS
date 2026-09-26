"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  LOCALE_STORAGE_KEY,
  THEME_STORAGE_KEY,
  isTheme,
  notifyStoredPreferencesChanged,
  prefersDark,
  subscribeToStoredPreferences,
  subscribeToSystemDark,
  type Theme,
} from "@/lib/theme";
import { DEFAULT_LOCALE, dirFor, resolveLocale, type Locale } from "@/lib/i18n/locales";
import { translate, translateCount, type PluralBase } from "@/lib/i18n/translate";
import type { MessageKey, TranslateVars } from "@/lib/i18n/messages";

interface PreferencesValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  /** The theme currently painted, with `system` already resolved. */
  effectiveTheme: "light" | "dark";
  locale: Locale;
  setLocale: (locale: Locale) => void;
  dir: "ltr" | "rtl";
  t: (key: MessageKey, vars?: TranslateVars) => string;
  count: (base: PluralBase, value: number) => string;
  /**
   * A value for `<html lang>`. This must never be empty: a screen reader uses it
   * to pick a pronunciation engine, and an empty `lang` means English rules
   * applied to Persian text, which is worse than no language support at all.
   */
  htmlLang: string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatDate: (value: string | Date | null | undefined, style?: "date" | "datetime") => string;
}

const PreferencesContext = createContext<PreferencesValue | null>(null);

const serverTheme = (): Theme => "system";
const serverLocale = (): Locale => DEFAULT_LOCALE;
const serverPrefersDark = (): boolean => false;

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return isTheme(stored) ? stored : "system";
}

function readStoredLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  return resolveLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY));
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  // The stored preferences are read through `useSyncExternalStore` rather than a
  // `useState` initialiser, which is the obvious thing to reach for and is wrong
  // here.
  //
  // A `useState` initialiser runs during render, on the server and in the
  // browser, and the two disagree: there is no localStorage on the server, so it
  // yields the default, while the browser yields the stored value. Every visitor
  // whose locale is not the default then gets React error #418, "text content
  // did not match" -- React discards the server markup and logs on every page
  // load. The third argument is the fix: it is the value used for the server
  // render *and* for hydration, so both agree by construction, and the client
  // store takes over immediately afterwards.
  //
  // Nothing flashes as a result. The blocking script in the document head has
  // already set `lang`, `dir` and the theme attribute before first paint, so the
  // page comes up in the right language and direction regardless.
  const theme = useSyncExternalStore(subscribeToStoredPreferences, readStoredTheme, serverTheme);
  const locale = useSyncExternalStore(subscribeToStoredPreferences, readStoredLocale, serverLocale);
  const systemDark = useSyncExternalStore(subscribeToSystemDark, prefersDark, serverPrefersDark);

  const effectiveTheme: "light" | "dark" = theme === "system" ? (systemDark ? "dark" : "light") : theme;

  useEffect(() => {
    document.documentElement.dataset.theme = effectiveTheme;
  }, [effectiveTheme]);

  const dir = dirFor(locale);

  useEffect(() => {
    const root = document.documentElement;
    root.lang = locale === "fa" ? "fa-IR" : "en-US";
    root.dir = dir;
  }, [dir, locale]);

  // Writing the key is the update. The store notifies through the same
  // subscription the reads use, so there is no second copy of this state to keep
  // in step -- which is what `setThemeState` used to be.
  const setTheme = useCallback((next: Theme) => {
    try {
      if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private browsing can refuse writes. Private browsing is exactly when a
      // throw here would be worst, and there is nothing to fall back to: the
      // blocking script reads the same key, so a write that failed there is not
      // a bug this code can paper over.
    }
    notifyStoredPreferencesChanged();
  }, []);

  const setLocale = useCallback((next: Locale) => {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      // See setTheme.
    }
    notifyStoredPreferencesChanged();
  }, []);

  const value = useMemo<PreferencesValue>(() => {
    const numberFormat = new Intl.NumberFormat(locale);
    return {
      theme,
      setTheme,
      effectiveTheme,
      locale,
      setLocale,
      dir,
      t: (key, vars) => translate(locale, key, vars),
      count: (base, amount) => translateCount(locale, base, amount),
      htmlLang: locale === "fa" ? "fa-IR" : "en-US",
      // `NumberFormat.format` takes no options, so a caller-supplied set needs
      // its own formatter. Reusing the cached one would silently ignore them.
      formatNumber: (input, options) =>
        options ? new Intl.NumberFormat(locale, options).format(input) : numberFormat.format(input),
      formatDate: (input, style = "date") => {
        if (!input) return translate(locale, "common.notSet");
        const date = input instanceof Date ? input : new Date(input);
        if (Number.isNaN(date.getTime())) return translate(locale, "common.notSet");
        return new Intl.DateTimeFormat(locale, {
          dateStyle: style === "date" ? "medium" : "medium",
          ...(style === "datetime" ? { timeStyle: "short" as const } : {}),
        }).format(date);
      },
    };
  }, [dir, effectiveTheme, locale, setLocale, setTheme, theme]);

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesValue {
  const value = useContext(PreferencesContext);
  if (!value) {
    throw new Error("usePreferences must be used inside a PreferencesProvider");
  }
  return value;
}

/** Shorthand for the common case of only needing the translator. */
export function useTranslate(): PreferencesValue["t"] {
  return usePreferences().t;
}
