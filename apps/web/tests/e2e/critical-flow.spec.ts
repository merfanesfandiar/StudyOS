import { expect, test } from "@playwright/test";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const briefPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "fixtures",
  "assignment-brief.pdf",
);

test("student plans, documents, and finalizes an assignment", async ({ page }) => {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 10_000)}@example.com`;

  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Student");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("StrongPass123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

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
  await page.getByLabel("Brief or description").fill("Create a small strategy game with tests.");
  await page.getByLabel("Deadline").fill("2026-12-01T17:00");
  await page.getByRole("button", { name: "Create draft" }).click();
  await expect(page).toHaveURL(/\/assignments\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Build a Java Strategy Game" })).toBeVisible();
  const assignmentUrl = page.url();

  await page.getByLabel("Requirement title").fill("Implement authentication");
  const requirementForm = page.locator("form").filter({ has: page.getByLabel("Requirement title") });
  await requirementForm.getByLabel("Description").fill("Users can register and sign in.");
  await requirementForm.getByRole("button", { name: "Add requirement" }).click();
  await expect(page.getByText("Requirement added.")).toBeVisible();

  await page.getByLabel("Constraint title").fill("Java version");
  const constraintForm = page.locator("form").filter({ has: page.getByLabel("Constraint title") });
  await constraintForm.getByLabel("Constraint", { exact: true }).fill("The project must build with Java 17 only.");
  await constraintForm.getByLabel("Value or version").fill("Java 17");
  await constraintForm.getByRole("button", { name: "Add constraint" }).click();
  await expect(page.getByText("Constraint added.")).toBeVisible();

  await page.getByLabel("Criterion title").fill("Functionality");
  await page.getByLabel("Weight percentage").fill("60");
  await page.getByRole("button", { name: "Add criterion" }).click();
  await expect(page.getByText("60%").first()).toBeVisible();

  await page.getByLabel("Criterion title").fill("Code quality");
  await page.getByLabel("Weight percentage").fill("40");
  await page.getByRole("button", { name: "Add criterion" }).click();
  await expect(page.getByText("100%").first()).toBeVisible();

  await page.getByTestId("document-upload").setInputFiles(briefPath);
  await expect(page.getByText("assignment-brief.pdf uploaded.")).toBeVisible();
  const documentItem = page.getByTestId("document-item");
  await expect(documentItem).toHaveCount(1);
  await expect(documentItem).toContainText("assignment-brief.pdf");

  const download = page.waitForEvent("download");
  await documentItem.getByRole("button", { name: "Download" }).click();
  const downloaded = await download;
  expect(downloaded.suggestedFilename()).toBe("assignment-brief.pdf");
  const downloadedPath = await downloaded.path();
  expect(downloadedPath).toBeTruthy();
  expect((await stat(downloadedPath as string)).size).toBeGreaterThan(0);

  const review = page.getByTestId("review-panel");
  await expect(review.getByText("100% of 100%")).toBeVisible();
  await expect(review.getByText("1 requirements · 1 constraints · 2 criteria · 1 documents")).toBeVisible();
  await expect(page.getByTestId("phase-two-sections")).toContainText("AI plan");
  await expect(page.getByTestId("phase-two-sections")).toContainText("Verification");

  page.once("dialog", (dialog) => void dialog.accept());
  await documentItem.getByRole("button", { name: "Delete assignment-brief.pdf" }).click();
  await expect(page.getByText("Document deleted.")).toBeVisible();
  await expect(page.getByTestId("document-item")).toHaveCount(0);
  await expect(page.getByText("No documents attached yet.")).toBeVisible();

  await page.getByTestId("document-upload").setInputFiles(briefPath);
  await expect(page.getByTestId("document-item")).toHaveCount(1);

  await page.getByRole("button", { name: "Edit details" }).click();
  const editForm = page.locator("form").filter({ has: page.getByLabel("Status") });
  await editForm.getByLabel("Brief").fill("Create a small strategy game with tests and a documented build.");
  await editForm.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Assignment details updated.")).toBeVisible();
  await expect(
    page.getByText("Create a small strategy game with tests and a documented build."),
  ).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Finalize assignment" }).click();
  await expect(page.getByText("Assignment finalized and now active.")).toBeVisible();
  await expect(page.getByText("Active", { exact: true })).toBeVisible();

  await page.goto("/dashboard");
  const upcoming = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Upcoming deadlines" }) })
    .last();
  await expect(upcoming.getByRole("link", { name: /Build a Java Strategy Game/ }).first()).toBeVisible();

  await page.goto(assignmentUrl);
  await page.getByRole("button", { name: "Edit details" }).click();
  const completeForm = page.locator("form").filter({ has: page.getByLabel("Status") });
  await completeForm.getByLabel("Status").selectOption("COMPLETED");
  await completeForm.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Assignment details updated.")).toBeVisible();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible();

  await page.goto("/dashboard");
  const summary = page.getByRole("region", { name: "Workspace summary" });
  await expect(summary.getByText("Completion")).toBeVisible();
  await expect(summary.getByText("100%")).toBeVisible();

  await page.goto("/assignments");
  await expect(page.getByText("AP140")).toBeVisible();
});

test("a second student cannot reach the first student's resources", async ({ browser }) => {
  const firstContext = await browser.newContext();
  const firstPage = await firstContext.newPage();
  const ownerEmail = `owner-${Date.now()}@example.com`;

  await firstPage.goto("/register");
  await firstPage.getByLabel("Full name").fill("Owner Student");
  await firstPage.getByLabel("Email address").fill(ownerEmail);
  await firstPage.getByLabel("Password").fill("StrongPass123");
  await firstPage.getByRole("button", { name: "Create account" }).click();
  await expect(firstPage).toHaveURL(/\/dashboard$/);

  await firstPage.goto("/courses");
  await firstPage.getByLabel("Course name").fill("Advanced Programming");
  await firstPage.getByLabel("Course code").fill("AP140");
  await firstPage.getByRole("button", { name: "Add course" }).click();
  await expect(firstPage.getByText("AP140 was added.")).toBeVisible();
  await firstPage.getByRole("link", { name: /AP140/ }).click();
  await firstPage.getByRole("link", { name: "New assignment" }).click();
  await firstPage.getByLabel("Assignment title").fill("Build a Java Strategy Game");
  await firstPage.getByRole("button", { name: "Create draft" }).click();
  await expect(firstPage).toHaveURL(/\/assignments\/[0-9a-f-]{36}$/);
  const assignmentUrl = firstPage.url();
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
