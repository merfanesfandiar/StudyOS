import { expect, test } from "@playwright/test";

test("student plans and finalizes an assignment", async ({ page }) => {
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

  await page.getByLabel("Requirement title").fill("Implement authentication");
  const requirementForm = page.locator("form").filter({ has: page.getByLabel("Requirement title") });
  await requirementForm.getByLabel("Description").fill("Users can register and sign in.");
  await requirementForm.getByRole("button", { name: "Add requirement" }).click();
  await expect(page.getByText("Requirement added.")).toBeVisible();

  await page.getByLabel("Criterion title").fill("Functionality");
  await page.getByLabel("Weight percentage").fill("60");
  await page.getByRole("button", { name: "Add criterion" }).click();
  await expect(page.getByText("60%").first()).toBeVisible();

  await page.getByLabel("Criterion title").fill("Code quality");
  await page.getByLabel("Weight percentage").fill("40");
  await page.getByRole("button", { name: "Add criterion" }).click();
  await expect(page.getByText("100%").first()).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Finalize assignment" }).click();
  await expect(page.getByText("Assignment finalized and now active.")).toBeVisible();
  await expect(page.getByText("Active", { exact: true })).toBeVisible();
});
