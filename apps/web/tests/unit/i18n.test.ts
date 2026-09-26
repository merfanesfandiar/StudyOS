import { describe, expect, it } from "vitest";
import { LOCALES, dirFor, resolveLocale } from "@/lib/i18n/locales";
import { catalogues, en, fa, type MessageKey } from "@/lib/i18n/messages";
import { pluralKey, translate, translateCount } from "@/lib/i18n/translate";

describe("message catalogue", () => {
  it("has an entry for every key in every locale", () => {
    const keys = Object.keys(en) as MessageKey[];
    expect(keys.length).toBeGreaterThan(0);
    for (const locale of LOCALES) {
      const missing = keys.filter((key) => !(key in catalogues[locale]));
      expect({ locale, missing }).toEqual({ locale, missing: [] });
    }
  });

  it("has no keys the source locale does not define", () => {
    // A stale key in a translation is invisible to the missing-key check above
    // but still dead weight, and usually means a key was renamed on one side.
    const known = new Set<string>(Object.keys(en));
    for (const locale of LOCALES) {
      const extra = Object.keys(catalogues[locale]).filter((key) => !known.has(key));
      expect({ locale, extra }).toEqual({ locale, extra: [] });
    }
  });

  it("gives every locale the same placeholders for a message", () => {
    const placeholders = (value: string) =>
      (value.match(/\{\w+\}/g) ?? []).sort().join(",");
    for (const [key, english] of Object.entries(en)) {
      for (const locale of LOCALES) {
        if (locale === "en") continue;
        const translated = catalogues[locale][key as MessageKey];
        // Persian may reorder the sentence, so compare the placeholder *set*.
        expect({ key, locale, vars: placeholders(translated) }).toEqual({
          key,
          locale,
          vars: placeholders(english),
        });
      }
    }
  });

  it("translates every English string", () => {
    // Catches a Persian entry left as a copy of the English one, which compiles
    // fine and reads as an untranslated page to the only person who can see it.
    const untranslated = (Object.keys(en) as MessageKey[]).filter(
      (key) => fa[key] === en[key],
    );
    expect(untranslated).toEqual([]);
  });
});

describe("translate", () => {
  it("returns the message for the requested locale", () => {
    expect(translate("en", "plan.approve")).toBe("Approve plan");
    expect(translate("fa", "plan.approve")).toBe("تأیید برنامه");
  });

  it("substitutes named placeholders", () => {
    expect(translate("en", "plan.version", { version: 3 })).toBe("Version 3");
    expect(translate("en", "dashboard.welcome", { name: "Ada" })).toBe(
      "Welcome back, Ada",
    );
  });

  it("leaves an unsupplied placeholder visible rather than blanking the sentence", () => {
    expect(translate("en", "plan.version")).toBe("Version {version}");
  });

  it("falls back to English for a locale that lacks the key", () => {
    const broken = { ...catalogues.fa } as Partial<typeof fa>;
    delete broken["plan.approve"];
    const original = catalogues.fa;
    catalogues.fa = broken as typeof fa;
    try {
      expect(translate("fa", "plan.approve")).toBe("Approve plan");
    } finally {
      catalogues.fa = original;
    }
  });
});

describe("pluralisation", () => {
  it("uses the English rule", () => {
    expect(translateCount("en", "common.count", 1)).toBe("1 item");
    expect(translateCount("en", "common.count", 5)).toBe("5 items");
    expect(translateCount("en", "common.count", 0)).toBe("0 items");
  });

  it("applies Persian's own rule, which differs from English at zero", () => {
    // CLDR classifies Persian 0 as the "one" category and English 0 as "other",
    // so "0 مورد" is correct and "0 items" is not. A hand-rolled
    // `count === 1 ? singular : plural` gets this wrong in both languages: it
    // treats English 0 as plural (right by luck) and Persian 1 as singular
    // (right) but only because English and Persian happen to agree at 1. Ask
    // `Intl` and the agreement stops mattering.
    expect(pluralKey("en", "common.count", 0)).toBe("common.count.other");
    expect(pluralKey("fa", "common.count", 0)).toBe("common.count.one");
  });

  it("agrees with English at one, which is where they happen to match", () => {
    expect(pluralKey("en", "common.count", 1)).toBe("common.count.one");
    expect(pluralKey("fa", "common.count", 1)).toBe("common.count.one");
  });
});

describe("locale resolution", () => {
  it("accepts a supported tag", () => {
    expect(resolveLocale("en")).toBe("en");
    expect(resolveLocale("fa")).toBe("fa");
  });

  it("narrows a regional tag to its base language", () => {
    expect(resolveLocale("fa-IR")).toBe("fa");
    expect(resolveLocale("en-GB")).toBe("en");
  });

  it("falls back to the default for anything unsupported", () => {
    expect(resolveLocale("de")).toBe("en");
    expect(resolveLocale(null)).toBe("en");
    expect(resolveLocale(undefined)).toBe("en");
  });

  it("marks Persian as right to left and English as left to right", () => {
    expect(dirFor("fa")).toBe("rtl");
    expect(dirFor("en")).toBe("ltr");
  });
});
