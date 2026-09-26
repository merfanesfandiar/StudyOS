"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  LOCALE_STORAGE_KEY,
  THEME_STORAGE_KEY,
  isTheme,
  prefersDark,
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
  // Both start from storage, not from a hardcoded default, because the blocking
  // script has already written the choice to the DOM and this must agree with it
  // or the first client render will flip the page back.
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);
  const [systemDark, setSystemDark] = useState<boolean>(prefersDark);

  // Track the OS preference so `system` stays live: switching the laptop to dark
  // mode should repaint an app that never touched its theme setting.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

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

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private browsing can refuse writes. The theme still applies for this
      // session, which is better than throwing during a click handler.
    }
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      // See setTheme: a failed write is not worth breaking the switch over.
    }
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
