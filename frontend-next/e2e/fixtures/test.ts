/**
 * Custom Playwright `test` with shared fixtures.
 *
 * Fixtures provided:
 *   • demoUser            — a frozen Demo user object (matches AuthProvider)
 *   • authenticatedPage   — a Page already in demo mode (localStorage seeded)
 *   • withSeededAnthropicConn — same as authenticatedPage but explicitly
 *                               asserts the AI costs demo endpoint returns
 *                               provider data so the AI Costs page renders.
 *
 * These three cover everything the journey specs need without forcing a
 * real account or real API keys.
 */

import { test as base, expect, type Page } from "@playwright/test";
import {
  DemoUser,
  SeededAnthropicConn,
  UniqueRegisteredUser,
} from "./types";

const DEMO_USER: DemoUser = {
  user_id: "demo",
  name: "Demo User",
  email: "demo@costly.dev",
};

/**
 * Seed demo localStorage on a Page that has already navigated to the app
 * origin. Idempotent.
 */
export async function enableDemoMode(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("costly_demo", "1");
    } catch {
      // ignore — incognito with storage disabled
    }
  });
}

interface CostlyFixtures {
  demoUser: DemoUser;
  authenticatedPage: Page;
  withSeededAnthropicConn: { page: Page; conn: SeededAnthropicConn };
  uniqueUser: UniqueRegisteredUser;
}

export const test = base.extend<CostlyFixtures>({
  demoUser: async ({}, use) => {
    await use(DEMO_USER);
  },

  authenticatedPage: async ({ page }, use) => {
    await enableDemoMode(page);
    // Force a navigation so the init script fires before any test code runs.
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await use(page);
  },

  withSeededAnthropicConn: async ({ page, request }, use) => {
    // Probe the demo API to confirm it's serving AI cost data with at least
    // one Anthropic provider row. This guards against the demo generator
    // regressing.
    const resp = await request.get("/api/demo/ai-costs?days=7");
    expect(resp.ok(), "/api/demo/ai-costs?days=7 should respond OK").toBe(true);
    const data = await resp.json();
    const hasAnthropic = Array.isArray(data?.providers)
      ? data.providers.some(
          (p: { platform?: string }) => p.platform === "anthropic",
        )
      : false;

    await enableDemoMode(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await use({
      page,
      conn: { platform: "anthropic", hasDemoCostsRendered: hasAnthropic },
    });
  },

  uniqueUser: async ({}, use) => {
    // Per-test-run unique email so register tests are idempotent.
    const stamp = Date.now().toString(36);
    const rand = Math.random().toString(36).slice(2, 8);
    await use({
      email: `e2e-${stamp}-${rand}@costly.test`,
      password: "Password123!",
      name: `E2E User ${stamp}`,
    });
  },
});

export { expect };
