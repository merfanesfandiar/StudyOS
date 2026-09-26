import { DEFAULT_LOCALE, type Locale } from "./locales";
import { catalogues, type MessageKey, type TranslateVars } from "./messages";

/**
 * Substitute `{name}` placeholders.
 *
 * A missing placeholder yields an empty string rather than throwing or leaving
 * the literal `{count}` on screen. A visible `{count}` is a bug report; a blank
 * is a cosmetic defect, and the cost of the wrong choice is lower.
 */
function interpolate(template: string, vars?: TranslateVars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.hasOwn(vars, key) ? String(vars[key]) : match,
  );
}

/**
 * Look up a message.
 *
 * Falls back to English rather than rendering the key. Showing `plan.approve` to
 * a user is worse than showing English text in a Persian page, and it is
 * trivially greppable; that is a better failure mode than a blank button.
 */
export type Translate = (key: MessageKey, vars?: TranslateVars) => string;

/**
 * Whether a key exists in the catalogue.
 *
 * For strings that arrive from the server rather than from the code: a readiness
 * field, an audit event type. Those come from a vocabulary the frontend does not
 * control, so a lookup has to be able to say "no" and fall back rather than
 * render a key. `Object.hasOwn` against the English catalogue is the honest test
 * -- `in` would also accept inherited properties and answer yes to nonsense.
 */
export function hasMessage(key: string): key is MessageKey {
  return Object.hasOwn(catalogues[DEFAULT_LOCALE], key);
}

export function translate(
  locale: Locale,
  key: MessageKey,
  vars?: TranslateVars,
): string {
  const template = catalogues[locale]?.[key] ?? catalogues[DEFAULT_LOCALE][key];
  return interpolate(template, vars);
}

/**
 * The prefix of a plural key, with the category suffix removed.
 *
 * Derived from `MessageKey` rather than declared by hand, so adding
 * `course.count.one`/`.other` to the catalogue widens this type automatically and
 * `count("course.count", n)` keeps typechecking without a second edit. Passing a
 * base with no matching pair — `count("plan.title", n)` — is a compile error
 * instead of a silently untranslated lookup.
 */
/**
 * Strip a plural category suffix from a key.
 *
 * The conditional is written over a bare type parameter on purpose. Distribution
 * across a union only happens when the checked type is a naked parameter, so
 * inlining this as `MessageKey extends \`${infer B}.one\`` would test the whole
 * union at once, fail, and collapse to `never`.
 */
type StripPluralCategory<K extends string> = K extends `${infer Base}.one`
  ? Base
  : K extends `${infer Base}.other`
    ? Base
    : never;

export type PluralBase = StripPluralCategory<MessageKey>;

/**
 * Count with locale-correct pluralisation.
 *
 * Plural rules are per-language data, and they genuinely disagree: CLDR puts
 * English 0 in the "other" category and Persian 0 in "one", so "0 مورد" is the
 * correct Persian and "0 items" the correct English. A hand-rolled
 * `count === 1` test appears to work right up until a locale disagrees, which
 * is why the catalogue encodes `.one`/`.other` keys and `Intl.PluralRules` does
 * the selecting.
 */
export function pluralKey(locale: Locale, base: PluralBase, count: number): MessageKey {
  const suffix = new Intl.PluralRules(locale).select(count);
  return `${base}.${suffix}` as MessageKey;
}

export function translateCount(locale: Locale, base: PluralBase, count: number): string {
  return translate(locale, pluralKey(locale, base, count), { count });
}
