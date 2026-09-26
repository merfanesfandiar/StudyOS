import { Browser, BrowserContext, Page, expect, test } from "@playwright/test";

/**
 * Theme, direction, and translation, verified in a browser.
 *
 * These are the claims a unit test cannot make. A class string typechecks and
 * lints and says nothing about what colour reaches the screen, and a `dir="rtl"`
 * attribute says nothing about whether the layout mirrors. So this file reads
 * computed styles and measured geometry.
 *
 * The login page is the fixture because it needs no API: the auth check fails,
 * which is exactly the state this page renders for. Everything asserted here is
 * a claim about the app shell, not about the data layer.
 */

const THEME_KEY = "studyos.theme";
const LOCALE_KEY = "studyos.locale";

/**
 * Seed the stored preferences before any page script runs.
 *
 * Only fills in a key that is absent. A `page.addInitScript` runs on *every*
 * navigation, so an unconditional write would silently undo a value the test
 * set itself -- which is how "the toggle persists" ends up asserting nothing
 * at all.
 */
async function seed(page: Page, theme?: string, locale?: string) {
  await page.addInitScript(
    ([themeKey, localeKey, storedTheme, storedLocale]) => {
      if (storedTheme && !window.localStorage.getItem(themeKey)) {
        window.localStorage.setItem(themeKey, storedTheme);
      }
      if (storedLocale && !window.localStorage.getItem(localeKey)) {
        window.localStorage.setItem(localeKey, storedLocale);
      }
    },
    [THEME_KEY, LOCALE_KEY, theme ?? null, locale ?? null] as const,
  );
}

/** A context with seeded preferences and one page already loaded. */
async function openWith(
  browser: Browser,
  theme: string,
  locale: string,
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await seed(page, theme, locale);
  await page.goto("/login");
  return { context, page };
}

/**
 * A computed colour as sRGB bytes.
 *
 * The tokens are authored in `oklch()`, so Chromium reports computed colours in
 * `lab()` notation and a test that expects `rgb(...)` fails while looking like
 * the design is wrong. Converting through a canvas sidesteps the notation: it
 * asks the browser what colour is actually painted.
 */
async function toRgb(page: Page, colour: string): Promise<[number, number, number]> {
  return page.evaluate((value) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext("2d")!;
    context.fillStyle = value;
    // A canvas only accepts colours it can parse, so this doubles as a check
    // that the computed value is a real colour.
    context.fillRect(0, 0, 1, 1);
    const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
    return [r, g, b] as [number, number, number];
  }, colour);
}

async function canvasRgb(page: Page): Promise<[number, number, number]> {
  return toRgb(page, await page.evaluate(() => getComputedStyle(document.body).backgroundColor));
}

async function tokenRgb(page: Page, token: string): Promise<[number, number, number]> {
  return toRgb(
    page,
    await page.evaluate((name) => {
      const probe = document.createElement("div");
      probe.style.color = `var(${name})`;
      document.body.appendChild(probe);
      const resolved = getComputedStyle(probe).color;
      probe.remove();
      return resolved;
    }, token),
  );
}

const luminance = ([r, g, b]: [number, number, number]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;

test.describe("theme", () => {
  test("the stored theme is applied before first paint", async ({ browser }) => {
    const { context, page } = await openWith(browser, "dark", "en");
    try {
      // The attribute has to come from the inline bootstrap, not from React
      // after hydration: a React-applied theme is a white flash for every
      // dark-mode user, which is the defect this system exists to avoid.
      expect(await page.getAttribute("html", "data-theme")).toBe("dark");
    } finally {
      await context.close();
    }
  });

  test("dark and light paint different canvases", async ({ browser }) => {
    const lightRun = await openWith(browser, "light", "en");
    const darkRun = await openWith(browser, "dark", "en");
    try {
      const light = await canvasRgb(lightRun.page);
      const dark = await canvasRgb(darkRun.page);

      // One class string satisfies this without either theme being applied, and
      // the page still renders unreadable. The two values are the claim.
      expect(light).not.toEqual(dark);
      expect(luminance(light)).toBeGreaterThan(200);
      expect(luminance(dark)).toBeLessThan(60);
    } finally {
      await lightRun.context.close();
      await darkRun.context.close();
    }
  });

  test("ink inverts against the canvas in both themes", async ({ browser }) => {
    const lightRun = await openWith(browser, "light", "en");
    const darkRun = await openWith(browser, "dark", "en");
    try {
      // Light theme: dark ink on a light canvas. Dark theme: light ink on a dark
      // canvas. A theme that failed to invert one of these is unreadable rather
      // than merely ugly, so the assertion is on the sign of the difference.
      const lightContrast =
        luminance(await canvasRgb(lightRun.page)) - luminance(await tokenRgb(lightRun.page, "--color-ink"));
      const darkContrast =
        luminance(await tokenRgb(darkRun.page, "--color-ink")) - luminance(await canvasRgb(darkRun.page));

      expect(lightContrast).toBeGreaterThan(100);
      expect(darkContrast).toBeGreaterThan(100);
    } finally {
      await lightRun.context.close();
      await darkRun.context.close();
    }
  });

  test("a stored theme is honoured on a later load", async ({ browser }) => {
    const { context, page } = await openWith(browser, "light", "en");
    try {
      await page.evaluate((key) => window.localStorage.setItem(key, "dark"), THEME_KEY);
      // Reload re-runs the bootstrap, which is the point: a theme that only
      // applied within one session is a theme that does not persist.
      await page.reload();

      expect(await page.getAttribute("html", "data-theme")).toBe("dark");
      expect(await page.evaluate((key) => window.localStorage.getItem(key), THEME_KEY)).toBe("dark");
      expect(luminance(await canvasRgb(page))).toBeLessThan(60);
    } finally {
      await context.close();
    }
  });

  test("the stored theme survives navigation to another page", async ({ browser }) => {
    const { context, page } = await openWith(browser, "dark", "en");
    try {
      expect(await page.getAttribute("html", "data-theme")).toBe("dark");
      await page.goto("/register");
      expect(await page.getAttribute("html", "data-theme")).toBe("dark");
    } finally {
      await context.close();
    }
  });
});

test.describe("locale and direction", () => {
  test("Persian sets dir and lang before first paint", async ({ browser }) => {
    const { context, page } = await openWith(browser, "light", "fa");
    try {
      expect(await page.getAttribute("html", "dir")).toBe("rtl");
      // `lang` must be a real value, not empty: a screen reader picks a
      // pronunciation engine from it, and an empty `lang` means English rules
      // applied to Persian text, which is worse than no language support.
      expect(await page.getAttribute("html", "lang")).toBe("fa-IR");
    } finally {
      await context.close();
    }
  });

  test("English stays left-to-right", async ({ browser }) => {
    const { context, page } = await openWith(browser, "light", "en");
    try {
      expect(await page.getAttribute("html", "dir")).toBe("ltr");
      expect(await page.getAttribute("html", "lang")).toBe("en-US");
    } finally {
      await context.close();
    }
  });

  test("the login form is translated, not just re-laid-out", async ({ browser }) => {
    const { context, page } = await openWith(browser, "light", "fa");
    try {
      await expect(page.getByLabel("نشانی ایمیل")).toBeVisible();
      await expect(page.getByLabel("گذرواژه")).toBeVisible();
      await expect(page.getByRole("button", { name: "ورود" })).toBeVisible();
      // A missing catalogue key falls back to English, so assert the English is
      // gone rather than only that the Persian appeared.
      await expect(page.getByLabel("Email address")).toHaveCount(0);
    } finally {
      await context.close();
    }
  });

  test("the layout mirrors rather than only flipping the direction attribute", async ({
    browser,
  }) => {
    const ltrRun = await openWith(browser, "light", "en");
    const rtlRun = await openWith(browser, "light", "fa");
    try {
      // The skip link is positioned with a logical `start` offset, so it has to
      // move. A `dir` attribute that reorders text but leaves boxes in place
      // means the layout is still left-to-right underneath.
      const ltrSkip = await ltrRun.page.locator('a[href="#main-content"]').boundingBox();
      const rtlSkip = await rtlRun.page.locator('a[href="#main-content"]').boundingBox();

      expect(ltrSkip).not.toBeNull();
      expect(rtlSkip).not.toBeNull();
      expect(ltrSkip!.x).toBeLessThan(rtlSkip!.x);
    } finally {
      await ltrRun.context.close();
      await rtlRun.context.close();
    }
  });
});
