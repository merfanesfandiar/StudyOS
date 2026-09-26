import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], channel: "chromium" },
    },
  ],
  webServer: {
    command: "npm run build && npm run start",
    url: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    // Never reuse. This suite exists to check what the browser actually paints,
    // and a leftover server from an earlier build satisfies the URL check while
    // serving stale HTML, JS and CSS -- which showed up as a dark-mode failure
    // reading the canvas as [0, 0, 0], the stylesheet simply not being there.
    // A false result in either direction is worse than the few seconds a build
    // costs, so the build below is the one under test. Set E2E_BASE_URL to test
    // a server you are running yourself, and then it is on you to rebuild it.
    reuseExistingServer: false,
    timeout: 300_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
