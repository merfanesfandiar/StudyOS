import { Browser, BrowserContext, Page, expect, test } from "@playwright/test";
import { en, fa } from "../../lib/i18n/messages";
import {
  ANALYSIS,
  ASSIGNMENT_ID,
  DEPENDENCY_GRAPH,
  PLAN,
  SPECIFICATION,
} from "../fixtures/specification";

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

// A route answers with a 200 body, or with `error()` when the server would
// really return a non-2xx. The distinction matters: "this assignment has never
// been analyzed" is a 404 carrying a code the client branches on, not a 200
// carrying a detail object. Answering 200 with `{ detail: "not_found" }`
// type-checks as JSON and then throws deep inside a component, which surfaces
// as a generic load failure and takes the whole page's text with it.
//
// A named wrapper rather than a `[status, body]` tuple: half these bodies are
// themselves arrays, and a tuple test cannot tell `[]` meaning "no courses"
// from `[]` meaning "404 with no body". Reading that wrong gave every list
// endpoint an undefined status and took the app shell down with it.
interface Stub {
  status?: number;
  body: unknown;
}

const ok = (body: unknown): Stub => ({ body });
const error = (status: number, code: string): Stub => ({
  status,
  body: { error: { code, message: code } },
});

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

/**
 * Two or more Latin words. One word is a product name, a format, a code or a
 * unit, all of which stay in Latin script in a Persian build; two words is
 * almost always an English phrase that should have been a catalogue key. The
 * earlier three-word threshold let "Analysis" and "done" through -- a heading
 * and a status suffix, both untranslated, both invisible to it.
 */
const PROSE = /[A-Za-z][A-Za-z'’-]*(?:\s+[A-Za-z][A-Za-z'’-]*){1,}/;

/**
 * Latin words that exist in the English catalogue and not in the Persian one.
 *
 * `PROSE` above needs two words to fire, because a single Latin word on a
 * Persian page is usually a product name or a unit. That is a reasonable
 * default and it was still not enough: this page shipped an untranslated
 * "Analysis" heading, a "confidence" suffix and a "corrected" marker, none of
 * them two words, all of them catalogue strings that should have been Persian.
 *
 * So this is the other half. A word that the English catalogue uses and the
 * Persian catalogue does not is, by construction, copy that was left behind;
 * a word both catalogues use is a brand or a format and is allowed, and a word
 * neither uses -- a UUID, a model name, a date -- is content and stays out of
 * it. The set is derived rather than listed, so a new Persian string that keeps
 * a Latin brand name keeps passing with no edit here, and a new English string
 * that nobody translated starts failing with no edit here either.
 */
function latinWords(values: string[]): Set<string> {
  return new Set(values.flatMap((value) => value.toLowerCase().match(/[a-z][a-z'’-]{2,}/g) ?? []));
}

function catalogueValues(catalogue: object): string[] {
  return Object.values(catalogue).flatMap((value) =>
    typeof value === "string" ? [value] : value && typeof value === "object" ? catalogueValues(value) : [],
  );
}

const ENGLISH_ONLY = [...latinWords(catalogueValues(en))].filter(
  (word) => !latinWords(catalogueValues(fa)).has(word),
);

function leakedCatalogueWords(line: string): string[] {
  return (line.toLowerCase().match(/[a-z][a-z'’-]{2,}/g) ?? []).filter((word) => ENGLISH_ONLY.includes(word));
}

function untranslated(text: string): string[] {
  return (text ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => !ALLOWED.some((allowed) => line.includes(allowed)))
    .filter((line) => !/^[/#.\-–—\s]*$/.test(line))
    .filter((line) => PROSE.test(line) || leakedCatalogueWords(line).length > 0);
}

async function openPersian(
  browser: Browser,
  extraRoutes: Array<[string, Stub]> = [],
): Promise<{ context: BrowserContext; page: Page }> {
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
  //

  const SHAPES: Record<string, Stub> = {
    // The detail route is the densest surface in the app: every specification
    // section, the readiness gate, the dependency graph and the analysis panel
    // render at once. Populated rather than empty, because the chrome that
    // fails to translate is the chrome that only appears once there is something
    // to show -- an empty specification renders almost no text, so an empty
    // fixture would pass a page that is mostly untranslated.
    [`/assignments/${ASSIGNMENT_ID}/specification`]: ok(SPECIFICATION),
    [`/assignments/${ASSIGNMENT_ID}/requirements/dependency-graph`]: ok(DEPENDENCY_GRAPH),
    // Not analyzed yet, which is the state a real student sees first. A 404 with
    // the code the client checks for, so the panel renders its "analyze this"
    // empty state -- the string-dense one -- rather than an error.
    [`/assignments/${ASSIGNMENT_ID}/analysis`]: error(404, "ANALYSIS_NOT_FOUND"),
    // `null` is a real plan response meaning "no plan yet", not an empty page.
    // A page envelope here would be read as a plan and crash the panel.
    [`/assignments/${ASSIGNMENT_ID}/plans`]: ok(null),
    "/courses": ok([]),
    "/assignments": ok(EMPTY_PAGE),
    "/notifications": ok([]),
    "/dashboard": ok({
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
    }),
  };

  function answer(route: import("@playwright/test").Route, stub: Stub) {
    return route.fulfill({
      status: stub.status ?? 200,
      json: stub.body,
      contentType: "application/json",
    });
  }

  await page.route(`${API}/**`, (route) => {
    const path = new URL(route.request().url()).pathname.slice(API_PATH.length);
    return answer(route, SHAPES[path] ?? ok(EMPTY_PAGE));
  });

  // Most specific first, for the same reason as the `/auth/me` route below.
  for (const [path, stub] of extraRoutes) {
    await page.route(`${API}${path}`, (route) => answer(route, stub));
  }

  // Registered last on purpose. Playwright matches routes newest-first, so if
  // this came before the catch-all above it would be shadowed by it, `/auth/me`
  // would come back as the empty list shape, and the shell would redirect to the
  // login page -- where this test would then find nothing to complain about.
  await page.route(`${API}/auth/me`, (route) =>
    route.fulfill({ json: USER, contentType: "application/json" }),
  );

  return { context, page };
}

interface Case {
  path: string;
  /** The heading to confirm the page really is Persian, when it has one. */
  heading: string | null;
  /**
   * Text that only appears once this page has actually loaded its data. Used
   * instead of a heading on the detail route, so a failed load cannot leave the
   * scan reading an error page and finding nothing to complain about.
   */
  waitsFor?: string | string[];
  /** Overrides for this case only; the shared table covers the rest. */
  routes?: Array<[string, Stub]>;
  name?: string;
}

const PAGES: Case[] = [
  { path: "/dashboard", heading: "داشبورد" },
  { path: "/courses", heading: "دوره‌ها" },
  { path: "/assignments", heading: "تکالیف" },
  { path: "/settings", heading: "تنظیمات" },
  { path: "/assignments/new", heading: "تکلیف جدید" },
  // No heading to wait on: the detail page is a titled panel with no single
  // h1, and asserting on one would mean inventing a heading. Instead this waits
  // for content that only a successfully loaded specification can produce, so a
  // failed load cannot make the scan pass over an error page.
  { path: `/assignments/${ASSIGNMENT_ID}`, heading: null, waitsFor: "حالت‌های صریح تعریف شوند" },
  {
    path: `/assignments/${ASSIGNMENT_ID}`,
    heading: null,
    // The model name is rendered by the analysis panel and nowhere else, so
    // seeing it means the panel mounted rather than that the page loaded.
    waitsFor: ANALYSIS.model,
    // The analysed state of the same page. This is where the string density
    // peaks -- around forty labelled sections of the analysis panel -- and none
    // of it is reachable while the assignment is unanalyzed. The 404 above is
    // the one a student actually meets first, so both are worth scanning.
    routes: [[`/assignments/${ASSIGNMENT_ID}/analysis`, ok(ANALYSIS)]],
    name: "with an analysis",
  },
  {
    path: `/assignments/${ASSIGNMENT_ID}`,
    heading: null,
    // The third state, and the one that was still unchecked. The planning panel
    // is not a separate route -- it renders inside the detail page -- but it
    // only appears once a plan exists, so every earlier case rendered it as an
    // empty state. An empty state is the state with the least text in it, so
    // the densest part of the planning UI was never scanned at all.
    // Two anchors, not one: the plan title alone would still pass if the body
    // below it failed to render, which is the case that needs checking.
    waitsFor: [PLAN.title, PLAN.tasks[0].title, PLAN.milestones[0].title],
    routes: [
      [`/assignments/${ASSIGNMENT_ID}/analysis`, ok(ANALYSIS)],
      [`/assignments/${ASSIGNMENT_ID}/plans`, ok(PLAN)],
    ],
    name: "with an analysis and a plan",
  },
];

test.describe("no page keeps English text in a Persian build", () => {
  for (const { path, heading, waitsFor, routes, name } of PAGES) {
    test(`${path}${name ? ` ${name}` : ""} renders Persian`, async ({ browser }) => {
      const { context, page } = await openPersian(browser, routes ?? []);
      try {
        await page.goto(path);
        if (waitsFor) {
          for (const anchor of [waitsFor].flat()) {
            await expect(page.getByText(anchor).first()).toBeVisible({ timeout: 15_000 });
          }
        } else {
          await expect(page.locator("h1, h2").first()).toBeVisible();
          // Confirm the page really is Persian before scanning it, so a redirect
          // to login cannot make this pass by finding nothing to complain about.
          await expect(page.getByRole("heading", { name: heading! }).first()).toBeVisible();
        }

        const offenders = untranslated(await page.locator("body").innerText());
        expect(offenders, `English text left on ${path}:\n${offenders.join("\n")}`).toEqual([]);
      } finally {
        await context.close();
      }
    });
  }
});
