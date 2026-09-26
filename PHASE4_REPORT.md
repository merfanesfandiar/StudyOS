# Phase 4: Planning Engine, Design System, and Localization — Final Report

## Summary

Implemented the planning engine end to end, then rebuilt the web client's visual
and linguistic foundations on top of it.

The planning engine turns a reviewed `AssignmentAnalysis` into a durable,
inspectable `AcademicWorkPlan` with a task graph that a student can correct
before anything is executed. The design work replaced hardcoded colors with
semantic tokens, added light and dark themes, and added full Persian with
right-to-left layout. The localization work made those two features
reachable in both languages, including the error paths, which is where the
work turned out to be.

Every gate passes against the numbers recorded below: 265 API tests, 119 web
unit tests, 14 real-browser tests, ruff, mypy across 108 files, tsc, eslint, and
a clean production build. Six end-to-end tests skip themselves when the API is
not running, and the four checks that genuinely cannot run here are named
rather than left implied — *What was not verified* is the most important section
in this report.

---

## What was built

### Planning engine

The pipeline a request now travels:

```
AssignmentSpecification → AssignmentAnalysis → PlanningContractResponse
  → PlannerOutput → AcademicWorkPlan → Task Graph → Human Review → Approved Plan
```

Durability decisions that shaped the code:

- **Nothing is discarded on failure.** A provider or graph failure commits the
  run and its `PLAN_GENERATION_FAILED` audit row through savepoint handling
  rather than rolling back, so the history a student sees explains the failure
  instead of omitting it.
- **Failures are typed at the boundary.** `LLMError` becomes
  `503 PLANNER_UNAVAILABLE` (the model provider is down; retry later) and
  `PlanGraphError` becomes `502 PLAN_REJECTED` (the model answered with an
  unusable graph; the request needs changing). Collapsing both into a 500 would
  have told a student to fix something they did not break.
- **Fallback is data, not a special case.** `used_fallback` and
  `rejection_reasons` are persisted structured fields, so a plan produced by the
  rule-based fallback is visibly labelled and can be compared against a real
  planner run later.
- **Regeneration is scoped, not wholesale.** `scope=MILESTONES` copies tasks,
  edges, and traceability from the approved plan and regenerates only the
  schedule, with no model call. `TASKS` and `NONE` replan.
- **Route order is load-bearing.** `/plans/runs` and `/plans/model-selection`
  must be declared before `/plans/{plan_id}`, or FastAPI binds the UUID
  converter to the literal paths and planning requests 404 on a plan that
  exists.

### Design system

- Roughly 350 hardcoded palette utilities across 21 TSX files replaced with
  semantic tokens; no TSX palette references remain.
- Light and dark themes, applied to the document root, persisted, and defaulted
  to the system preference.
- Tokens carry the contrast work rather than the components: a theme is legible
  because the token pairs were checked, not because each component was
  restyled.
- Layout converted to logical CSS properties, so right-to-left is a rendering
  concern instead of a per-component mirror.

### Localization

- English and Persian across a typed catalogue of 622 keys. `fa` is declared as
  `Record<MessageKey, string>` against a `MessageKey` union derived from `en`,
  so a missing or misspelled Persian key is a type error rather than a blank
  label in production. This is enforced, not convention.
- Locale-aware number, date, and relative-time formatting.
- A no-flash inline script applies the stored theme and direction before
  first paint, so there is no flash of the wrong theme or of English text on a
  Persian session.
- The server keeps English metadata. That is deliberate: it is what a crawler
  and a no-JavaScript client see, and it keeps the rendered HTML stable across
  the hydration boundary.

---

## Files changed

### Backend

- `apps/api/app/modules/planning/` — orchestrator, router, graph validation,
  model tiers, fallback construction.
- `apps/api/app/models/enums.py` — `ModelTier` (`EFFICIENT`, `ADVANCED`),
  `AIMode` (`AUTO`, `FAST`, `BALANCED`, `DEEP`), scope and run-status values.
- `apps/api/app/models/entities.py` — `AcademicWorkPlan`, task graph, runs,
  traceability.
- `apps/api/app/schemas/planning.py` — planner contract and `PageResponse<T>`
  (`items` plus `page: { page, page_size, total, pages }`).
- `apps/api/alembic/versions/0005_phase4_planning.py` — current head.
- `apps/api/tests/test_planning_api.py` — provider failure, graph rejection,
  dangling-dependency coverage.

### Web

- `apps/web/lib/i18n/messages.ts` — the 622-key catalogue.
- `apps/web/lib/error-message.ts` — the single resolver every error path uses.
- `apps/web/lib/format.ts` — translator-aware status and enum labels.
- `apps/web/lib/use-plan.ts`, `use-analysis.ts`, `use-specification.ts` — hooks
  that resolve failures at render time.
- `apps/web/components/preferences-provider.tsx`, `apps/web/lib/theme.ts` —
  hydration-safe preference state.
- `apps/web/components/planning/plan-panel.tsx` — the planning UI.
- `apps/web/components/assignment/` — detail sections, all localized.
- `apps/web/app/globals.css` — semantic light and dark tokens.
- `apps/web/tests/e2e/theme-and-locale.spec.ts`, `persian-pages.spec.ts`,
  `critical-flow.spec.ts`.
- `apps/web/scripts/prepare-standalone.mjs`, `apps/web/playwright.config.ts`.
- `.github/workflows/ci.yml`.

### Docs

- `docs/planning/engine.md` — architecture and API reference.

---

## Defects the verification found

Unit tests passed over all of these. They are listed because what caught them
is the argument for the test types, not just the tests.

**A stale server produced a false dark-mode failure.** `reuseExistingServer`
defaults to true outside CI, so a locally running server from an earlier commit
answered the test. The first committed browser run was red because of a
container image, not the design. Fixed with `reuseExistingServer: false`; the
suite now always exercises the build in front of it.

**A dark canvas read as `[0, 0, 0]`.** The stylesheet 404'd, so the computed
background was transparent over the browser's black default. The contrast
assertion was correct; the environment was not. This is what motivated both the
local standalone parity work and the new `image` CI job.

**React hydration error #418.** `useState(readStoredTheme)` in the preferences
provider read `localStorage` during the first client render, which disagreed
with the server's HTML and forced a re-render. Replaced with
`useSyncExternalStore` over a subscribed store in `lib/theme.ts`, so the server
snapshot and the client snapshot are the same value by construction.

**The English network error reached Persian pages.** `ApiError.code ===
"NETWORK_ERROR"` was rendered through `error.message` throughout the failure
paths, and that message is the English string `NETWORK_ERROR_MESSAGE`. Browser
tests that scanned for untranslated text caught this on a page that had been
fully translated otherwise. Fixing it properly produced
`lib/error-message.ts`, now used at 26 call sites across 18 files, which
translates local failures and passes server messages through — the server stays
the authority on its own wording.

The scan that found this only ever covered the five authenticated pages listed
under *What was not verified*. So this class of bug was invisible on the routes
it did not visit, and "the scan is clean" should be read as a statement about
those five routes only.

**`use-plan` had four English strings inlined as literals.** Found by making
its fallback parameter a typed `MessageKey` instead of a `string`, which
rejected the literals at compile time. The planning panel is the one surface
where a failure is expected to be seen.

**An untranslated option survived the section translations.** `Choose a
requirement` in `requirements-section.tsx`, found by a final scan for capitalised
prose in JSX rather than by any test.

---

## Quality gate verification

| Gate | Command | Result |
| --- | --- | --- |
| API lint | `ruff check app tests alembic` | all checks passed |
| API types | `mypy app` | clean, 108 source files |
| API tests | `pytest -q` | 265 passed, 786 warnings |
| API schema | `alembic heads` | `0005_phase4_planning` (single head) |
| Golden analysis evaluation | `python -m app.ai.evaluation.report` | every fixture passed, every planted defect detected |
| Web types | `tsc --noEmit` | clean |
| Web lint | `eslint .` | clean |
| Web unit | `vitest run` | 119 passed, 8 files |
| Web build | `npm run build` | compiled successfully |
| Browser | `playwright test` | 14 passed, 6 skipped (API absent) |
| Local production parity | `npm run start` | HTML and `/_next/static` assets both 200 |

The 14 browser tests are 9 theme-and-RTL checks (`theme-and-locale.spec.ts`)
and 5 authenticated-page translation scans (`persian-pages.spec.ts`). The
translation scan intercepts API traffic, renders each page in Persian, and fails
on untranslated Latin prose with an allowlist for product names and units. It
found the network-error defect above.

---

## What was not verified

Stated plainly, because the gap between "the tests passed" and "this works" is
where this project is currently least certain.

- **The full-stack flow did not run here.** The six `critical-flow.spec.ts`
  tests need the API and a real database, and neither was available. They now
  skip with a stated reason instead of failing, so a red suite means a real
  regression. It has not been observed passing locally; in CI it runs against
  `docker compose up -d --build db api`, which is untested in this environment.
- **Docker was not available.** The new `image` CI job is written to build the
  web image and assert that it serves its own stylesheet, but it has never been
  executed. The compose and Dockerfile changes are static-review only.
- **Live OpenAI and OCR are unverified.** All model behaviour was exercised
  through the deterministic mock provider and the golden evaluation. Real
  provider latency, rate limits, and output drift are unmeasured, and the
  `LLMError → 503` path has been tested against a simulated failure only.
- **The Persian page scan does not cover `/assignments/[id]`.** The five scanned
  routes are `/dashboard`, `/courses`, `/assignments`, `/settings`, and
  `/assignments/new`. The detail route is the most string-dense surface in the
  app and is covered by unit tests and review, not by an automated scan. This is
  the largest remaining i18n risk.
- **Phase 3's `coverage_of` can over-report.** The union-based check can mark a
  requirement covered by a criterion that satisfies it only partially. Carried
  forward unresolved; it is a correctness question about the traceability view,
  not a rendering bug.

---

## Known limitations and next steps

1. Add an API-mocked `persian-pages` case for `/assignments/[id]`, which closes
   the largest i18n coverage gap and does not require a database.
2. Fix `coverage_of` to require a non-empty intersection for the covering
   criteria, or relabel the view as indicative.
3. Restore `alembic/script.py.mako`, which is absent. It does not block
   existing migrations, but it is needed to author a new one.
4. Measure real provider behaviour — latency, cost, and rate limits — before
   enabling OpenAI in a deployed environment, and confirm the timeout in
   `llm_timeout_seconds` is realistic against observed p95.
5. Phase 5 and autonomous task execution remain out of scope by design. Nothing
   in this phase executes a plan; a plan is inert until a human approves it.
