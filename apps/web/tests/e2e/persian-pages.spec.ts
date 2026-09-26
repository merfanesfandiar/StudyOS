import { Browser, BrowserContext, Page, expect, test } from "@playwright/test";

/**
 * Every translated page, checked for the failure mode a unit test cannot see.
 *
 * A missing catalogue key does not crash. `translate` falls back to English, so
 * a page with a dozen untranslated strings still renders, still passes its
 * component tests, and still looks fine in development. The regression that
 * actually bites is a Persian page with English scattered through it, and the
 * only way to notice is to read the rendered text in the browser.
 *
 * So this walks the pages and asserts no English sentences survive. It is
 * deliberately blunt: it does not know which strings should be there, only that
 * a sentence in Latin script on a `fa` page is a bug.
 *
 * The pages are behind auth, which normally needs Postgres and Docker. Both are
 * unavailable here, so `/auth/me` and the list endpoints are intercepted and
 * answered with the empty shapes the UI already handles. That keeps this a test
 * of the frontend's own strings, which is what it is for, and leaves the
 * end-to-end data path to the full-stack spec.
 */

const THEME_KEY = "studyos.theme";
const LOCALE_KEY = "studyos.locale";
const API = "http://localhost:8000/api/v1";
const API_PATH = "/api/v1";

const USER = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Sara",
  email: "sara@example.edu",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const EMPTY_PAGE = { items: [], page: { page: 1, page_size: 20, total: 0, pages: 1 } };

/**
 * Latin-script prose that is expected to remain in a Persian build.
 *
 * Only genuinely untranslatable content, and kept as short as possible: these
 * are proper nouns and format fragments, not sentences. A new entry needs a
 * reason, because the usual reason turns out to be a missing key.
 */
const ALLOWED = [
  "StudyOS",
  "PDF",
  "DOCX",
  "TXT",
  "ZIP",
  "MB",
  "OKLCH",
];

/** A run of Latin words long enough to be prose rather than a code or acronym. */
const PROSE = /[A-Za-z][A-Za-z'’-]*(?:\s+[A-Za-z][A-Za-z'’-]*){2,}/;

function untranslated(text: string): string[] {
  return (text ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => PROSE.test(line))
    .filter((line) => !ALLOWED.some((allowed) => line.includes(allowed)))
    .filter((line) => !/^[/#.\-–—\s]*$/.test(line));
}

async function openPersian(browser: Browser): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.addInitScript(
    ([themeKey, localeKey]) => {
      window.localStorage.setItem(themeKey, "light");
      window.localStorage.setItem(localeKey, "fa");
    },
    [THEME_KEY, LOCALE_KEY] as const,
  );

  // Anything else gets the shape its endpoint actually returns, so the page
  // renders its real empty or populated state instead of an error. The list of
  // routes is deliberately the whole API rather than the ones these five pages
  // happen to call: an unstubbed request produces the offline error state, which
  // is itself English, and the scan would then be reading the failure path
  // instead of the page.
  // Shapes copied from the `Dashboard` and `Notification` types rather than
  // invented: the first draft stubbed a plausible-looking stats object, the page
  // threw on it, and Next replaced the whole route with its own English
  // error page -- which read as a translation failure but was a bad fixture.
  const SHAPES: Record<string, unknown> = {
    "/courses": [],
    "/assignments": EMPTY_PAGE,
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

  await page.route(`${API}/**`, (route) => {
    const path = new URL(route.request().url()).pathname.slice(API_PATH.length);
    const shape = SHAPES[path] ?? EMPTY_PAGE;
    return route.fulfill({ json: shape, contentType: "application/json" });
  });

  // Registered last on purpose. Playwright matches routes newest-first, so if
  // this came before the catch-all above it would be shadowed by it, `/auth/me`
  // would come back as the empty list shape, and the shell would redirect to the
  // login page -- where this test would then find nothing to complain about.
  await page.route(`${API}/auth/me`, (route) =>
    route.fulfill({ json: USER, contentType: "application/json" }),
  );

  return { context, page };
}

const PAGES = [
  { path: "/dashboard", heading: "داشبورد" },
  { path: "/courses", heading: "دوره‌ها" },
  { path: "/assignments", heading: "تکالیف" },
  { path: "/settings", heading: "تنظیمات" },
  { path: "/assignments/new", heading: "تکلیف جدید" },
];

test.describe("no page keeps English text in a Persian build", () => {
  for (const { path, heading } of PAGES) {
    test(`${path} renders Persian`, async ({ browser }) => {
      const { context, page } = await openPersian(browser);
      try {
        await page.goto(path);
        await expect(page.locator("h1, h2").first()).toBeVisible();
        // Confirm the page really is Persian before scanning it, so a redirect
        // to login cannot make this pass by finding nothing to complain about.
        await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();

        const offenders = untranslated(await page.locator("body").innerText());
        expect(offenders, `English text left on ${path}:\n${offenders.join("\n")}`).toEqual([]);
      } finally {
        await context.close();
      }
    });
  }
});
