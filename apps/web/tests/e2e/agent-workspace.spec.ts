import { expect, Page, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fa } from "../../lib/i18n/messages";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/$/,
  "",
);

/**
 * End-to-end coverage for the Agent Workspace.
 *
 * Like the critical flow, these tests need the real API and a real database:
 * the workspace is a thin client over persisted conversations, runs, events
 * and artifacts, and stubbing any of those away would test the fixture rather
 * than the product. When the API is not running they skip, loudly, rather
 * than fail.
 *
 * The compose API runs the deterministic mock provider. Its runs execute each
 * task, then deterministically raise a REVIEW checkpoint at the revision limit
 * ("keep revising / move on / stop"), and its draft artifacts carry validated
 * dynamic UI envelopes — both are real runtime behaviour this suite exercises
 * end to end.
 */
async function apiIsUp(): Promise<boolean> {
  try {
    const response = await fetch(new URL("/health", API_URL), {
      signal: AbortSignal.timeout(2_000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

let apiAvailable = false;
let apiChecked = false;

const briefPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "fixtures",
  "assignment-brief.pdf",
);

/** Long enough to clear the description check at 80 characters. */
const BRIEF =
  "Create a small turn-based strategy game in Java with unit tests, a documented build, and a " +
  "written design note explaining the module boundaries you chose.";

/** Every terminal or in-flight status the runtime can legitimately show. */
const RUN_STATUS = /COMPLETED|BLOCKED|WAITING_FOR_USER|FAILED|CANCELLED|PAUSED|RUNNING|STARTING/;

const workspace = (page: Page) => page.getByTestId("agent-workspace");
const sidebarNav = (page: Page) => page.getByRole("navigation", { name: "Conversations" });
const contextPanel = (page: Page) => page.getByRole("complementary", { name: "Context" });
const threadRegion = (page: Page) => page.getByRole("region", { name: "Conversation thread" });

/** A conversation's select button, scoped to the list so the create button
 * (which carries the same "New conversation" text) cannot be hit by accident. */
const conversationItem = (page: Page, title: string) =>
  sidebarNav(page).locator("li").getByText(title, { exact: true });

/** Register and land on the dashboard. */
async function register(page: Page): Promise<void> {
  const email = `ws-${Date.now()}-${Math.floor(Math.random() * 10_000)}@example.com`;
  await page.goto("/register");
  // Wait for the hydrated form before touching it: filling during hydration
  // races the element being replaced and the fill silently retries forever.
  await page.getByRole("button", { name: "Create account" }).waitFor({ state: "visible" });
  await page.getByLabel("Full name").fill("E2E Student");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("StrongPass123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

/** Register, create a course, and land on a draft assignment. Returns its URL. */
async function seedDraft(page: Page, title = "Build a Java Strategy Game"): Promise<string> {
  await register(page);

  await page.goto("/courses");
  await page.getByLabel("Course name").fill("Advanced Programming");
  await page.getByLabel("Course code").fill(`AP${Math.floor(Math.random() * 9000 + 1000)}`);
  await page.getByLabel("Description").fill("Object-oriented design and data structures.");
  await page.getByRole("button", { name: "Add course" }).click();
  await page.getByRole("link", { name: /AP\d{4}/ }).first().click();
  await expect(page.getByRole("heading", { name: /AP\d{4}/ })).toBeVisible();

  await page.getByRole("link", { name: "New assignment" }).click();
  await page.getByLabel("Assignment title").fill(title);
  await page.getByLabel("Brief or description").fill(BRIEF);
  await page.getByLabel("Deadline").fill("2026-12-01T17:00");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(/\/assignments\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  return page.url();
}

/** Fill in everything the advisory and blocking checks look at. */
async function completeSpecification(page: Page): Promise<void> {
  const requirements = page.getByTestId("requirements-section");
  await requirements.getByLabel("Title").fill("Implement authentication");
  await requirements.getByLabel("Description").fill("Users can register and sign in.");
  await requirements.getByRole("button", { name: "Add requirement" }).click();
  await expect(requirements.getByText("Implement authentication", { exact: true })).toBeVisible();
  await requirements.getByLabel("Title").fill("Build the combat loop");
  await requirements.getByLabel("Description").fill("Units take turns and deal damage.");
  await requirements.getByRole("button", { name: "Add requirement" }).click();
  await expect(requirements.getByText("Build the combat loop", { exact: true })).toBeVisible();

  const criteria = page.getByTestId("criteria-section");
  await criteria.getByLabel("Criterion title").fill("Functionality");
  await criteria.getByLabel("Weight %").fill("60");
  await criteria.getByRole("button", { name: "Add criterion" }).click();
  // Wait for the first row to land before reusing the form: the form resets
  // on success, and a fill/click that races the reset is silently lost.
  await expect(criteria.getByText("Functionality")).toBeVisible();
  await criteria.getByLabel("Criterion title").fill("Code quality");
  await criteria.getByLabel("Weight %").fill("40");
  await criteria.getByRole("button", { name: "Add criterion" }).click();
  await expect(criteria.getByText("Code quality")).toBeVisible();

  const deliverables = page.getByTestId("deliverables-section");
  await deliverables.getByLabel("Title").fill("Source archive");
  await deliverables.getByRole("button", { name: "Add deliverable" }).click();
  await expect(deliverables.getByRole("button", { name: "Delete Source archive" })).toBeVisible();

  await page.getByTestId("document-upload").setInputFiles(briefPath);
  await expect(page.getByTestId("document-item")).toHaveCount(1);
}

/**
 * Resolve every REVIEW checkpoint through the workspace. The mock run waits
 * for a decision on every task; choosing "Move on and leave the draft"
 * completes the task and the runtime proceeds to the next one, until the plan
 * is done and no card remains. React reuses the card element between tasks, so
 * advancement is detected by the question text changing (or the card
 * disappearing once the run has settled).
 */
async function driveToTerminal(page: Page): Promise<void> {
  const card = page.locator('[data-testid="checkpoint-card"]');
  for (let round = 0; round < 40; round += 1) {
    if ((await card.count()) === 0) break;
    const question = card.getByText(/I have drafted/).first();
    const before = (await question.textContent()) ?? "";
    await card.getByRole("button", { name: "Move on and leave the draft" }).click();
    await expect
      .poll(
        async () => {
          const current = page.locator('[data-testid="checkpoint-card"]');
          if ((await current.count()) === 0) return "settled";
          const next = current.getByText(/I have drafted/).first();
          return (await next.count()) ? ((await next.textContent()) ?? "") : "settled";
        },
        { timeout: 90_000 },
      )
      .not.toBe(before);
  }
  // No open question left: the run must have settled somewhere terminal.
  const execution = contextPanel(page).locator("section").filter({ hasText: "Execution" });
  await expect(
    execution.getByText(/COMPLETED|CANCELLED|FAILED|BLOCKED/).first(),
  ).toBeVisible({ timeout: 90_000 });
}

/**
 * Drive a real run to a real outcome: start it on the assignment page, then
 * answer its checkpoints in the workspace. The compose API executes
 * synchronously, so when this returns the run has reached a terminal state and
 * its artifacts, events and verification (for a completed run) are persisted.
 */
async function runToOutcome(page: Page): Promise<string> {
  test.setTimeout(300_000);
  const url = await startRun(page);
  await newConversation(page, { register: false });
  await bindAssignment(page, "Build a Java Strategy Game");
  // The run waits at its first revision-limit checkpoint; the workspace card
  // must be live before the loop can start.
  await expect(page.locator('[data-testid="checkpoint-card"]').first()).toBeVisible({
    timeout: 60_000,
  });
  await driveToTerminal(page);
  return url;
}

async function startRun(page: Page): Promise<string> {
  await seedDraft(page);
  await completeSpecification(page);

  await page.getByTestId("analyze").click();
  await expect(page.getByTestId("analysis-summary")).toBeVisible();
  await page.getByTestId("accept-analysis").click();

  await page.getByRole("button", { name: "Generate plan" }).click();
  await page.getByRole("button", { name: "Approve plan" }).click({ timeout: 60_000 });

  const agent = page.getByTestId("agent-panel");
  await agent.getByRole("button", { name: "Create run" }).click({ timeout: 60_000 });
  await expect(agent.getByRole("button", { name: "Start", exact: true })).toBeVisible();
  await agent.getByRole("button", { name: "Start", exact: true }).click();
  await expect(
    agent.getByText(/Finished|Waiting for you|Blocked|Paused/).first(),
  ).toBeVisible({ timeout: 90_000 });
  return page.url();
}

/** Open the workspace and start a conversation from the empty state.
 * `register: false` reuses the session a previous helper created. */
async function newConversation(page: Page, { register: signUp = true } = {}): Promise<void> {
  if (signUp) await register(page);
  await page.goto("/agent");
  await expect(workspace(page)).toBeVisible();
  await page.getByRole("button", { name: "New conversation" }).first().click();
  // The thread is live once the composer is there.
  await expect(threadRegion(page).getByRole("textbox")).toBeVisible();
}

/** Bind a conversation to an assignment through the context panel. */
async function bindAssignment(page: Page, title: string): Promise<void> {
  await expect(
    contextPanel(page).getByText("This conversation is not linked to an assignment yet."),
  ).toBeVisible();
  await contextPanel(page).getByRole("button", { name: "Link an assignment" }).click();
  await contextPanel(page).getByRole("button", { name: title }).click();
  // The sidebar item carries the bound-assignment chip once the conversation
  // update has round-tripped.
  await expect(sidebarNav(page).getByText("Assignment", { exact: true })).toBeVisible();
}

test.beforeEach(async () => {
  if (apiChecked) return;
  apiChecked = true;
  apiAvailable = await apiIsUp();
  if (!apiAvailable) {
    console.warn(
      `[e2e] skipping the agent-workspace flow: no API at ${API_URL}. ` +
        "Start it with `docker compose up -d` to run these.",
    );
  }
});

test.beforeEach(async ({}, testInfo) => {
  test.skip(!apiAvailable, "API not running");
  void testInfo;
});

test.describe("agent workspace", () => {
  // Registration + course + assignment + workspace flows exceed the default.
  test.setTimeout(120_000);

  // Tailwind lg/xl breakpoints sit at 1024/1280px; a 1280x720 window can end
  // up narrower than 1280 once a scrollbar is accounted for, which would hide
  // the context panel and turn every layout assumption into a coin flip.
  test.use({ viewport: { width: 1440, height: 900 } });

  test("a conversation carries messages and survives a reload", async ({ page }) => {
    await newConversation(page);

    const thread = threadRegion(page);
    await thread.getByRole("textbox").fill("Help me plan the strategy game");
    await thread.getByRole("textbox").press("Enter");
    await expect(thread.getByText("Help me plan the strategy game")).toBeVisible();

    // The message is the user's own; no agent reply exists until the runtime
    // produces a real outcome, so none may appear.
    await expect(thread.getByText("You")).toBeVisible();

    // Reload: the workspace comes back empty-state (selection is not stored),
    // and the persisted messages are still there behind the conversation.
    await page.reload();
    await expect(workspace(page)).toBeVisible();
    await conversationItem(page, "New conversation").click();
    await expect(thread.getByText("Help me plan the strategy game")).toBeVisible();
  });

  test("conversations can be renamed, archived, restored, and deleted", async ({ page }) => {
    await newConversation(page);

    // Rename.
    await conversationItem(page, "New conversation").click();
    await sidebarNav(page).locator("li").first().hover();
    await sidebarNav(page).getByRole("button", { name: "Rename" }).click();
    const renameInput = page.getByRole("textbox", { name: "New name" });
    await renameInput.fill("Planning chat");
    await renameInput.press("Enter");
    await expect(conversationItem(page, "Planning chat")).toBeVisible();

    // Archive removes it from the default list.
    await sidebarNav(page).locator("li").first().hover();
    await sidebarNav(page).getByRole("button", { name: "Archive" }).click();
    await expect(conversationItem(page, "Planning chat")).toHaveCount(0);

    // Explicitly asking for archived ones reveals it, and restore returns it.
    await workspace(page).getByRole("checkbox").check();
    await expect(conversationItem(page, "Planning chat")).toBeVisible();
    await sidebarNav(page).locator("li").first().hover();
    await sidebarNav(page).getByRole("button", { name: "Restore" }).click();
    await expect(conversationItem(page, "Planning chat")).toHaveCount(0);

    // Delete asks first, and the confirmation is the only path in.
    await workspace(page).getByRole("checkbox").uncheck();
    await conversationItem(page, "Planning chat").click();
    await sidebarNav(page).locator("li").first().hover();
    await sidebarNav(page).getByRole("button", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete conversation?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Keep" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(conversationItem(page, "Planning chat")).toBeVisible();

    await sidebarNav(page).locator("li").first().hover();
    await sidebarNav(page).getByRole("button", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete conversation?" })
      .getByRole("button", { name: "Delete" })
      .click();
    await expect(conversationItem(page, "Planning chat")).toHaveCount(0);

    // Deletion is soft but final in the list: a reload brings nothing back.
    await page.reload();
    await expect(workspace(page)).toBeVisible();
    await expect(conversationItem(page, "Planning chat")).toHaveCount(0);
  });

  test("a conversation binds to a real assignment and can be unbound", async ({ page }) => {
    await seedDraft(page, "Bind Me Assignment");
    await newConversation(page, { register: false });
    await bindAssignment(page, "Bind Me Assignment");

    const context = contextPanel(page);
    await expect(context.getByText("Bind Me Assignment")).toBeVisible();
    await expect(context.getByText("Draft")).toBeVisible();

    // Unbinding returns the panel to its honest empty state.
    await context.getByRole("button", { name: "Unlink" }).click();
    await expect(
      context.getByText("This conversation is not linked to an assignment yet."),
    ).toBeVisible();
  });

  test("files upload through the composer only when an assignment is bound", async ({ page }) => {
    await seedDraft(page, "Upload Target");
    await newConversation(page, { register: false });

    const thread = threadRegion(page);
    const attach = thread.getByRole("button", { name: "Attach" });
    await expect(attach).toBeDisabled();
    await expect(attach).toHaveAttribute(
      "title",
      "Attach an assignment to this conversation to upload files.",
    );

    await bindAssignment(page, "Upload Target");
    await expect(attach).toBeEnabled();

    await thread.locator('input[type="file"]').setInputFiles(briefPath);
    await expect(thread.getByText("Uploaded")).toBeVisible();
    await expect(thread.getByText("assignment-brief.pdf")).toBeVisible();

    // A rejected file type is refused by the real documents API, and the
    // composer reports it rather than pretending anything was stored.
    await thread
      .locator('input[type="file"]')
      .setInputFiles({
        name: "payload.exe",
        mimeType: "application/octet-stream",
        buffer: Buffer.from("MZ"),
      });
    await expect(thread.getByText("This file type is not supported.")).toBeVisible();
  });

  test("a run reconnects: its status and activity are re-derived from persisted state", async ({
    page,
  }) => {
    // `runToOutcome` leaves the workspace on the conversation it drove the run
    // from — the one bound to the assignment and carrying the run summary.
    await runToOutcome(page);

    const context = contextPanel(page);
    const execution = context.locator("section").filter({ hasText: "Execution" });
    // The run's real status comes from the run detail; which terminal state it
    // reached is the provider's business, not the layout's. `.first()` is the
    // run-status span: the same section lists each task's own status too.
    await expect(execution.getByText(RUN_STATUS).first()).toBeVisible();

    // The activity rail renders the persisted event log, in the thread. The
    // rail is a window of the latest events (a ten-task run emits far more
    // than it shows), so the assertion uses an event near the tail that only
    // the real run produced: each task was completed by the student's own
    // "move on" decision.
    const decisionEvent = threadRegion(page).getByText(
      /Completed T\d+ with the student's draft left as-is\./,
    );
    await expect(threadRegion(page).getByText("Agent activity")).toBeVisible();
    await expect(decisionEvent.first()).toBeVisible({ timeout: 20_000 });

    // A reload re-derives everything from the persisted log — nothing is lost
    // and nothing new is invented.
    await page.reload();
    await expect(workspace(page)).toBeVisible();
    await conversationItem(page, "New conversation").click();
    await expect(
      contextPanel(page).locator("section").filter({ hasText: "Execution" }).getByText(RUN_STATUS).first(),
    ).toBeVisible();
    await expect(
      threadRegion(page).getByText(/Completed T\d+ with the student's draft left as-is\./).first(),
    ).toBeVisible({ timeout: 20_000 });
  });

  test("a real decision is answered in the workspace, once, through the backend", async ({
    page,
  }) => {
    await startRun(page);

    await newConversation(page, { register: false });
    await bindAssignment(page, "Build a Java Strategy Game");

    // The runtime raised a REVIEW checkpoint on its own; the workspace renders
    // it with exactly the options the backend offered.
    const card = page.getByTestId("checkpoint-card");
    await expect(card).toBeVisible({ timeout: 30_000 });

    // The decision round-trips through the resolve endpoint: the answered
    // question's card is gone (a new question for a later task may legitimately
    // take its place, but never the same one). The same sentence also appears
    // in the event log and the run summary, so the assertion is scoped to the
    // decision cards themselves.
    await card.getByRole("button", { name: "Move on and leave the draft" }).click();
    await expect(
      page.locator('[data-testid="checkpoint-card"]').filter({ hasText: "I have drafted T1" }),
    ).toHaveCount(0, { timeout: 30_000 });

    // Nothing else was asked for: the card count can only grow through real
    // runtime requests, and each is one decision.
    const interactionCard = page.getByTestId("interaction-card");
    if (await interactionCard.count()) {
      // An interaction is a backend-raised risk gate: it renders with its own
      // approve/reject pair and is never invented client-side.
      await expect(interactionCard.first()).toBeVisible();
    }
  });

  test("artifacts are real, previewable, and downloadable", async ({ page }) => {
    await runToOutcome(page);

    await newConversation(page, { register: false });
    await bindAssignment(page, "Build a Java Strategy Game");

    const context = contextPanel(page);
    const artifactsSection = context.locator("section").filter({ hasText: "Artifacts" });
    const first = artifactsSection.locator("details").first();
    await expect(first).toBeVisible();

    // The body is text rendered as text, or a validated dynamic UI block when
    // the artifact carries one — the mock runtime attaches UI envelopes, so
    // both paths are real. `<details>` starts collapsed, so the assertion is
    // that expanding it reveals the artifact, not that hidden content exists.
    await first.locator("summary").click();
    await expect(first).toHaveAttribute("open", "");
    const bodyText = first.locator("pre");
    if (await bodyText.count()) {
      await expect(bodyText.first()).toBeVisible();
      await expect(bodyText.first()).not.toBeEmpty();
    } else {
      // Dynamic UI path: the registered renderer drew structured blocks, and
      // the runtime's own envelope describes the artifact's type.
      await expect(first.getByText(/Artifact type:/)).toBeVisible();
    }

    // Download hands the exact content the API returned to the browser.
    const downloadPromise = page.waitForEvent("download");
    await artifactsSection.getByRole("button", { name: "Download" }).first().click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.(md|txt)$/);
  });

  test("a completed run is verified, and the verdict is the real one", async ({ page }) => {
    await runToOutcome(page);

    await newConversation(page, { register: false });
    await bindAssignment(page, "Build a Java Strategy Game");

    // Every completed run triggers the real verification pipeline; a completed
    // run must therefore produce a verdict, not just an empty state.
    const panel = page.getByTestId("verification-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByTestId("verification-verdict")).toBeVisible({ timeout: 60_000 });
  });
});

test("the workspace is right-to-left in Persian", async ({ page }) => {
  // Register while the app is in English (the auth helpers are English), then
  // switch locale before opening the workspace: every part of the surface the
  // frontend renders must be Persian, and the page must lay out right to left.
  await register(page);
  await page.addInitScript(() => {
    window.localStorage.setItem("studyos.locale", "fa");
  });
  await page.goto("/agent");
  await expect(workspace(page)).toBeVisible();

  await expect(page.locator("html")).toHaveAttribute("lang", "fa-IR");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  // `dir` is only a hint; the computed direction is what actually lays out.
  expect(
    await page.evaluate(() => getComputedStyle(document.documentElement).direction),
  ).toBe("rtl");

  // The three regions are labelled in Persian.
  await expect(
    page.getByRole("navigation", { name: fa["workspace.sidebar.conversations"] }),
  ).toBeVisible();
  const thread = page.getByRole("region", { name: fa["workspace.thread.title"] });
  await expect(thread.getByText(fa["workspace.thread.emptyBody"])).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: fa["workspace.context.title"] }),
  ).toBeVisible();

  // A Persian message goes through the same real path as any other: typed,
  // persisted, and rendered again after a reload.
  await page.getByRole("button", { name: fa["workspace.sidebar.new"] }).first().click();
  const textbox = thread.getByRole("textbox");
  await expect(textbox).toHaveAttribute("aria-label", fa["workspace.composer.placeholder"]);
  const message = "سلام، این یک پیام آزمایشی است.";
  await textbox.fill(message);
  await textbox.press("Enter");
  await expect(thread.getByText(message)).toBeVisible();

  await page.reload();
  await expect(workspace(page)).toBeVisible();
  await page
    .getByRole("navigation", { name: fa["workspace.sidebar.conversations"] })
    .locator("li")
    .getByText(fa["workspace.newConversationTitle"], { exact: true })
    .click();
  await expect(
    page
      .getByRole("region", { name: fa["workspace.thread.title"] })
      .getByText(message),
  ).toBeVisible();
});

test.describe("agent workspace on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the workspace is usable on a phone", async ({ page }) => {
    await newConversation(page);

    const thread = threadRegion(page);
    await thread.getByRole("textbox").fill("hello from a phone");
    await thread.getByRole("textbox").press("Enter");
    await expect(thread.getByText("hello from a phone")).toBeVisible();

    // The sidebar is a drawer at this width.
    await page
      .getByRole("button", { name: "Conversations", exact: true })
      .filter({ visible: true })
      .click();
    const sidebarDrawer = page.getByRole("dialog");
    await expect(sidebarDrawer.getByRole("navigation", { name: "Conversations" })).toBeVisible();
    await sidebarDrawer.getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // So is the context panel. The desktop toggle carries the same label but
    // is hidden at this width, hence the visibility filter.
    await page
      .getByRole("button", { name: "Context", exact: true })
      .filter({ visible: true })
      .click();
    await expect(page.getByRole("dialog").getByText("Context")).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});
