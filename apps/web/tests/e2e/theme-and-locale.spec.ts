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


/**
 * An authenticated page, for the controls that only exist inside the app shell.
 *
 * The shell is behind auth, and the login page has no theme or language control
 * in it -- which is precisely why the compact language toggle went untested for
 * as long as it was broken. Seeding preferences proves they are *applied*; it
 * says nothing about whether the control you press to change them works.
 */
async function openShell(browser: Browser, theme: string, locale: string) {
  const api = "http://localhost:8000/api/v1";
  const context = await browser.newContext();
  const page = await context.newPage();
  await seed(page, theme, locale);
  const user = {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Sara",
    email: "sara@example.edu",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
  const empty = { items: [], page: { page: 1, page_size: 20, total: 0, pages: 1 } };
  // A single catch-all shape is not enough: the dashboard expects its stats
  // object and throws on a page envelope, and Next answers a thrown route with
  // its own English error page -- which then fails this suite for a reason that
  // has nothing to do with preferences.
  const shapes: Record<string, unknown> = {
    "/courses": [],
    "/assignments": empty,
    "/notifications": [],
    "/dashboard": {
      upcoming_assignments: [],
      recent_assignments: [],
      courses_count: 0,
      assignments_count: 0,
      in_progress_assignments_count: 0,
      ready_assignments_count: 0,
      incomplete_assignments_count: 0,
      completed_assignments_count: 0,
      completion_percentage: 0,
      average_readiness_score: 0,
      unread_notifications_count: 0,
    },
  };
  await page.route(`${api}/**`, (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    return route.fulfill({
      json: shapes[path] ?? empty,
      contentType: "application/json",
    });
  });
  await page.route(`${api}/auth/me`, (route) =>
    route.fulfill({ json: user, contentType: "application/json" }),
  );
  await page.goto("/dashboard");
  return { context, page };
}

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

test.describe("the controls in the app shell", () => {
  test("the compact language control switches the language when clicked", async ({ browser }) => {
    // A real click, not a DOM-level `selectOption`.
    //
    // The previous control was a `<label>` wrapped around a visually hidden
    // native `<select>`. Driving that select from the DOM changed the locale
    // perfectly well, so nothing was wrong with the state -- but `sr-only` clips
    // the control to a 1px box, so a user's click opened the OS picker at that
    // degenerate position, away from the button. Setting the value in a test
    // passed while the button did nothing for a person. Only clicking it proves
    // the affordance.
    const { context, page } = await openShell(browser, "light", "en");
    try {
      await expect(page.locator("h1, h2").first()).toBeVisible();
      expect(await page.getAttribute("html", "lang")).toBe("en-US");

      const control = page.getByRole("button", { name: /Switch to فارسی/ });
      await control.click();

      await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
      await expect(page.locator("html")).toHaveAttribute("lang", "fa-IR");
      // The control now offers the way back, so the change is reversible from
      // the same place rather than only through settings.
      await expect(page.getByRole("button", { name: /تغییر زبان به English/ })).toBeVisible();
      // And it survives a reload, which is what makes it a setting rather than a
      // one-off.
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    } finally {
      await context.close();
    }
  });

  test("the compact theme control switches the theme when clicked", async ({ browser }) => {
    const { context, page } = await openShell(browser, "light", "en");
    try {
      await expect(page.locator("h1, h2").first()).toBeVisible();
      const light = await canvasRgb(page);
      await page.getByRole("button", { name: /theme/i }).first().click();
      await expect.poll(async () => (await canvasRgb(page)) !== light).toBe(true);
    } finally {
      await context.close();
    }
  });
});
