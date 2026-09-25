import { expect, Locator, Page, test } from "@playwright/test";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

function section(page: Page, testId: string): Locator {
  return page.getByTestId(testId);
}

async function addRequirement(page: Page, title: string, description: string): Promise<void> {
  const requirements = section(page, "requirements-section");
  await requirements.getByLabel("Title").fill(title);
  await requirements.getByLabel("Description").fill(description);
  await requirements.getByRole("button", { name: "Add requirement" }).click();
  await expect(requirements.getByText(title, { exact: true })).toBeVisible();
}

async function addCriterion(page: Page, title: string, weight: string): Promise<void> {
  const criteria = section(page, "criteria-section");
  await criteria.getByLabel("Criterion title").fill(title);
  await criteria.getByLabel("Weight %").fill(weight);
  await criteria.getByRole("button", { name: "Add criterion" }).click();
  await expect(criteria.getByText(title, { exact: true })).toBeVisible();
}

/** Register, create a course, and land on a draft assignment. */
async function seedDraft(page: Page): Promise<string> {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 10_000)}@example.com`;

  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Student");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("StrongPass123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.goto("/courses");
  await page.getByLabel("Course name").fill("Advanced Programming");
  await page.getByLabel("Course code").fill("AP140");
  await page.getByLabel("Description").fill("Object-oriented design and data structures.");
  await page.getByRole("button", { name: "Add course" }).click();
  await expect(page.getByText("AP140 was added.")).toBeVisible();
  await page.getByRole("link", { name: /AP140/ }).click();
  await expect(page.getByRole("heading", { name: /AP140/ })).toBeVisible();

  await page.getByRole("link", { name: "New assignment" }).click();
  await page.getByLabel("Assignment title").fill("Build a Java Strategy Game");
  await page.getByLabel("Brief or description").fill(BRIEF);
  await page.getByLabel("Deadline").fill("2026-12-01T17:00");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(/\/assignments\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Build a Java Strategy Game" })).toBeVisible();
  return page.url();
}

/** Fill in everything the advisory and blocking checks look at. */
async function completeSpecification(page: Page): Promise<void> {
  await addRequirement(page, "Implement authentication", "Users can register and sign in.");
  await addRequirement(page, "Build the combat loop", "Units take turns and deal damage.");

  const requirements = section(page, "requirements-section");
  const second = requirements.getByText("Build the combat loop").locator("xpath=ancestor::li[1]");
  await second.getByRole("button", { name: "Depends on" }).click();
  await requirements.getByLabel("Depends on").selectOption({ index: 1 });
  await requirements.getByRole("button", { name: "Add dependency" }).click();
  await expect(requirements.getByText("Needs REQ-001")).toBeVisible();
  await expect(requirements.getByText("REQ-001 → REQ-002")).toBeVisible();

  const constraints = section(page, "constraints-section");
  await constraints.getByLabel("Title").fill("Java version");
  await constraints.getByLabel("Description").fill("The project must build with Java 17 only.");
  await constraints.getByLabel("Value (optional)").fill("Java 17");
  await constraints.getByRole("button", { name: "Add constraint" }).click();
  await expect(constraints.getByRole("button", { name: "Delete Java version" })).toBeVisible();

  await addCriterion(page, "Functionality", "60");
  await addCriterion(page, "Code quality", "40");

  const deliverables = section(page, "deliverables-section");
  await deliverables.getByLabel("Title").fill("Source archive");
  await deliverables.getByRole("button", { name: "Add deliverable" }).click();
  await expect(
    deliverables.getByRole("button", { name: "Delete Source archive" }),
  ).toBeVisible();

  const taxonomy = section(page, "taxonomy-section");
  await taxonomy.getByLabel("Name").fill("Java");
  await taxonomy.getByLabel("Version").fill("17");
  await taxonomy.getByRole("button", { name: "Add technology" }).click();
  await expect(taxonomy.getByRole("button", { name: "Remove Java" })).toBeVisible();
  await taxonomy.getByLabel("Tag").fill("game-dev");
  await taxonomy.getByRole("button", { name: "Add tag" }).click();
  await expect(taxonomy.getByRole("button", { name: "Remove game-dev" })).toBeVisible();

  await page.getByTestId("document-upload").setInputFiles(briefPath);
  await expect(page.getByTestId("document-item")).toHaveCount(1);
}

test("the readiness gate blocks an incomplete specification and releases it once complete", async ({
  page,
}) => {
  await seedDraft(page);

  const readiness = section(page, "readiness-panel");
  await expect(readiness).toContainText("Evaluation criteria");
  await expect(readiness).toContainText("Requirements");
  await expect(readiness.getByRole("button", { name: "Mark ready for analysis" })).toBeDisabled();

  await completeSpecification(page);

  await expect(readiness).toContainText("100%");
  await expect(readiness.getByRole("button", { name: "Mark ready for analysis" })).toBeEnabled();
  await readiness.getByRole("button", { name: "Mark ready for analysis" }).click();
  await expect(readiness).toContainText("Marked ready for analysis");
  await expect(page.getByText("Ready for analysis").first()).toBeVisible();

  // Breaking a blocking check demotes the assignment without any extra click.
  const criteria = section(page, "criteria-section");
  await criteria.getByRole("button", { name: "Delete Code quality" }).click();
  await expect(readiness).toContainText("Evaluation criteria total 60.00%");
  await expect(page.getByText("Incomplete").first()).toBeVisible();
  await expect(readiness.getByRole("button", { name: "Mark ready for analysis" })).toBeDisabled();

  // Repairing it is not automatic either: the student reopens the gate.
  await addCriterion(page, "Code quality", "40");
  await readiness.getByRole("button", { name: "Mark ready for analysis" }).click();
  await expect(readiness).toContainText("Marked ready for analysis");
});

test("requirements, resources, summary, and history stay in step with the specification", async ({
  page,
}) => {
  const assignmentUrl = await seedDraft(page);
  await completeSpecification(page);

  const requirements = section(page, "requirements-section");
  await requirements.getByLabel("Status for REQ-001").selectOption("COMPLETED");
  await expect(requirements.getByText("1/2 done")).toBeVisible();

  const summary = section(page, "summary-section");
  await expect(summary).toContainText("1 completed");

  const document = page.getByTestId("document-item");
  await expect(document).toContainText("assignment-brief.pdf");

  const download = page.waitForEvent("download");
  await document.getByRole("button", { name: "Download" }).click();
  const downloaded = await download;
  expect(downloaded.suggestedFilename()).toBe("assignment-brief.pdf");
  const downloadedPath = await downloaded.path();
  expect((await stat(downloadedPath as string)).size).toBeGreaterThan(0);

  page.once("dialog", (dialog) => void dialog.accept());
  await document.getByRole("button", { name: "Delete assignment-brief.pdf" }).click();
  await expect(page.getByTestId("document-item")).toHaveCount(0);
  await expect(page.getByText("No documents attached yet.")).toBeVisible();

  const history = section(page, "history-section");
  // The feed is keyed on the specification version, so it reflects the edits
  // made above instead of the state the page was opened in.
  await expect(history.getByText(/^Added requirement REQ-001$/)).toBeVisible();
  await expect(history.getByText(/^Uploaded assignment-brief\.pdf$/)).toBeVisible();
  await expect(history.getByText(/^Deleted assignment-brief\.pdf$/)).toBeVisible();
  await history.getByRole("button", { name: "Versions" }).click();
  await expect(history.getByText(/Version \d+/).first()).toBeVisible();
  await history.getByRole("button", { name: "View" }).first().click();
  await expect(page.getByTestId("version-snapshot")).toContainText("requirements");

  // A reopened gate is still reachable after leaving and coming back.
  await page.goto(assignmentUrl);
  await expect(section(page, "requirements-section")).toContainText("REQ-002");
});

test("the dashboard reports readiness instead of a single active count", async ({ page }) => {
  await seedDraft(page);
  await completeSpecification(page);
  await section(page, "readiness-panel")
    .getByRole("button", { name: "Mark ready for analysis" })
    .click();
  await expect(section(page, "readiness-panel")).toContainText("Marked ready for analysis");

  await page.goto("/dashboard");
  const summary = page.getByRole("region", { name: "Workspace summary" });
  await expect(summary.getByText("Ready for analysis")).toBeVisible();
  await expect(summary.getByText("Incomplete")).toBeVisible();
  await expect(summary.getByText("100%", { exact: true }).first()).toBeVisible();
  await expect(summary).toContainText("Average readiness");

  const upcoming = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Upcoming deadlines" }) })
    .last();
  await expect(upcoming.getByRole("link", { name: /Build a Java Strategy Game/ }).first()).toBeVisible();

  await page.goto("/assignments");
  await page.getByRole("button", { name: "Ready" }).click();
  await expect(page.getByRole("link", { name: /Build a Java Strategy Game/ })).toBeVisible();
  await page.getByRole("button", { name: "Incomplete" }).click();
  await expect(page.getByText("No matching assignments")).toBeVisible();
});

test("a second student cannot reach the first student's assignment", async ({ browser }) => {
  const firstContext = await browser.newContext();
  const firstPage = await firstContext.newPage();

  const assignmentUrl = await seedDraft(firstPage);
  await firstPage.getByTestId("document-upload").setInputFiles(briefPath);
  await expect(firstPage.getByTestId("document-item")).toHaveCount(1);

  const secondContext = await browser.newContext();
  const secondPage = await secondContext.newPage();

  await secondPage.goto("/register");
  await secondPage.getByLabel("Full name").fill("Other Student");
  await secondPage.getByLabel("Email address").fill(`other-${Date.now()}@example.com`);
  await secondPage.getByLabel("Password").fill("StrongPass123");
  await secondPage.getByRole("button", { name: "Create account" }).click();
  await expect(secondPage).toHaveURL(/\/dashboard$/);

  await secondPage.goto(assignmentUrl);
  await expect(secondPage.getByText("Assignment not found.")).toBeVisible();

  await secondPage.goto("/courses");
  await expect(secondPage.getByText("No courses yet")).toBeVisible();
  await secondPage.goto("/assignments");
  await expect(secondPage.getByText("No assignments yet")).toBeVisible();

  await firstContext.close();
  await secondContext.close();
});
