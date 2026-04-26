import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the costly frontend.
 *
 * Modes:
 *   • Local dev          — `npm run e2e` (run `npm run dev` in another shell)
 *   • Local CI-like      — `CI=1 npm run e2e`
 *   • Deployed read-only — `npm run e2e:deployed`
 *                          (BASE_URL=https://costly.cdatainsights.com PUBLIC_ONLY=1)
 *
 * Notes:
 *   • PUBLIC_ONLY=1 skips any test that mutates server state (register/login).
 *     The deployed CI job sets this so we never create real users in prod.
 *   • Browser matrix: chromium + webkit + mobile-chrome by default. Locally
 *     you can pin a single project with `npx playwright test --project=chromium`.
 *   • baseURL falls back to localhost:3000 — start `npm run dev` first when
 *     running locally.
 */

const isCI = !!process.env.CI;
const baseURL = process.env.BASE_URL || "http://localhost:3000";

// Only spin webkit + mobile-chrome on full local runs / CI; deployed read-only
// runs default to chromium-only to keep wall-clock low against prod.
const isDeployedSmoke =
  process.env.PUBLIC_ONLY === "1" || /costly\.cdatainsights\.com/.test(baseURL);

export default defineConfig({
  testDir: "./e2e/specs",
  // Specs live under e2e/specs/ — POMs and fixtures are siblings and must
  // not be picked up as test files.
  testMatch: /.*\.spec\.ts$/,
  outputDir: "test-results",

  // Each test gets its own browser context — no shared cookies or storage.
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 2 : undefined,

  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },

  reporter: isCI
    ? [
        ["github"],
        ["html", { outputFolder: "playwright-report", open: "never" }],
        ["json", { outputFile: "test-results/results.json" }],
      ]
    : [
        ["list"],
        ["html", { outputFolder: "playwright-report", open: "never" }],
      ],

  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    // Keep external requests light — most assertions hit our own /api/demo/*
    // endpoints which are unauthenticated read-only paths.
    extraHTTPHeaders: {
      "x-test-runner": "playwright",
    },
  },

  projects: isDeployedSmoke
    ? [
        {
          name: "chromium",
          use: { ...devices["Desktop Chrome"] },
        },
      ]
    : [
        {
          name: "chromium",
          use: { ...devices["Desktop Chrome"] },
        },
        {
          name: "webkit",
          use: { ...devices["Desktop Safari"] },
        },
        {
          name: "mobile-chrome",
          use: { ...devices["Pixel 7"] },
        },
      ],

  // Locally we expect the user to run `npm run dev` themselves so HMR stays
  // useful; CI starts the server explicitly in the workflow file. So no
  // webServer block here.
});
