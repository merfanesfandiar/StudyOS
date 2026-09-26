/**
 * Locale definitions.
 *
 * English and Persian are the two shipped locales. Persian is here because it
 * is a real test of the layout: it is written right to left, and it is the
 * reason the app uses logical CSS properties rather than left/right ones. A
 * locale list that only ever contains English locales proves nothing about
 * direction handling, so the RTL case is a first-class citizen from the start.
 */

export const LOCALES = ["en", "fa"] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

export interface LocaleMeta {
  /** BCP 47 tag for `Intl`, `<html lang>`, and `dir`. */
  tag: string;
  /** Endonym: the language's name in that language. */
  label: string;
  dir: "ltr" | "rtl";
}

export const LOCALE_META: Record<Locale, LocaleMeta> = {
  en: { tag: "en-US", label: "English", dir: "ltr" },
  fa: { tag: "fa-IR", label: "فارسی", dir: "rtl" },
};

export function isLocale(value: string | null | undefined): value is Locale {
  return value !== null && value !== undefined && (LOCALES as readonly string[]).includes(value);
}

/** Resolve anything a browser might hand us to a supported locale. */
export function resolveLocale(value: string | null | undefined): Locale {
  if (isLocale(value)) return value;
  // `fa-IR`, `fa`, or an uppercase variant should all land on Persian.
  const base = value?.split("-")[0]?.toLowerCase();
  return isLocale(base) ? base : DEFAULT_LOCALE;
}

export function dirFor(locale: Locale): "ltr" | "rtl" {
  return LOCALE_META[locale].dir;
}
