/**
 * Theme resolution, kept out of React so it can run in a blocking inline script
 * before first paint.
 *
 * The ordering is the whole point: `localStorage` first, then the OS preference.
 * A user who explicitly chose dark gets dark even when their OS says light,
 * and a user who chose nothing gets the OS behaviour, which is what they expect
 * without ever opening settings.
 */

export const THEMES = ["light", "dark", "system"] as const;
export type Theme = (typeof THEMES)[number];

export const THEME_STORAGE_KEY = "studyos.theme";
export const LOCALE_STORAGE_KEY = "studyos.locale";

export const isTheme = (value: unknown): value is Theme =>
  typeof value === "string" && (THEMES as readonly string[]).includes(value);

export function prefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

/** The theme that should actually be painted, collapsing `system`. */
export function resolveTheme(theme: Theme): "light" | "dark" {
  return theme === "system" ? (prefersDark() ? "dark" : "light") : theme;
}

/**
 * The script inlined into `<head>`.
 *
 * It must be tiny and synchronous. It sets `data-theme` on the root element so
 * the first paint is already correct; doing this in a `useEffect` instead shows
 * a white flash on every load for dark-mode users, which reads as a broken page
 * before the app has had a chance to render anything.
 */
export function themeBootstrapScript(): string {
  return `(function(){try{
var k=${JSON.stringify(THEME_STORAGE_KEY)};
var s=localStorage.getItem(k);
var t=(s==="light"||s==="dark")?s:(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");
document.documentElement.dataset.theme=t;
}catch(e){}})();`;
}

export function localeBootstrapScript(): string {
  return `(function(){try{
var k=${JSON.stringify(LOCALE_STORAGE_KEY)};
var l=localStorage.getItem(k);
document.documentElement.lang=(l==="fa")?"fa-IR":(l==="en"?"en-US":"en-US");
document.documentElement.dir=(l==="fa")?"rtl":"ltr";
}catch(e){}})();`;
}
