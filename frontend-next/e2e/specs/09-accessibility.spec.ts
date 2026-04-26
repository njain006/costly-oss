import { test, expect } from "../fixtures";
import AxeBuilder from "@axe-core/playwright";

/**
 * Accessibility checks via axe-core.
 *
 * We treat `critical` and `serious` violations as blocking. `moderate` /
 * `minor` issues are surfaced as console output but don't fail the build —
 * those land on the team's product-a11y backlog (see docs/lanes/tests-e2e.md).
 *
 * Coverage:
 *   - public marketing landing
 *   - /overview in demo mode
 *   - /ai-costs in demo mode
 */

const BLOCKING_IMPACTS = new Set(["critical", "serious"]);

interface AxeViolationLite {
  id: string;
  impact: "minor" | "moderate" | "serious" | "critical" | null | undefined;
  help: string;
  helpUrl: string;
  nodes: { target: unknown[] }[];
}

function summariseViolations(violations: AxeViolationLite[]): string {
  return violations
    .map(
      (v) =>
        `  • [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} nodes)\n    ${v.helpUrl}`,
    )
    .join("\n");
}

async function runAxe(page: import("@playwright/test").Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const violations = results.violations as unknown as AxeViolationLite[];
  const blocking = violations.filter((v) =>
    BLOCKING_IMPACTS.has(String(v.impact)),
  );

  if (violations.length > 0) {
    // Always log the full set so triage is easier without re-running.
    // eslint-disable-next-line no-console
    console.log(
      `\n[axe] ${label} — ${violations.length} violation(s) (${blocking.length} blocking):\n${summariseViolations(violations)}\n`,
    );
  }

  expect(
    blocking,
    `${label} has ${blocking.length} critical/serious a11y violation(s)`,
  ).toEqual([]);
}

test.describe("Accessibility — axe-core", () => {
  test("marketing landing has no critical or serious violations", async ({
    page,
  }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await runAxe(page, "/");
  });

  test("/overview (demo) has no critical or serious violations", async ({
    authenticatedPage: page,
  }) => {
    await page.goto("/overview", { waitUntil: "domcontentloaded" });
    // Wait for the heading so we don't axe-scan a still-loading skeleton.
    await page
      .getByRole("heading", { name: /platform overview/i })
      .waitFor({ state: "visible", timeout: 15_000 });
    await runAxe(page, "/overview");
  });

  test("/ai-costs (demo) has no critical or serious violations", async ({
    withSeededAnthropicConn,
  }) => {
    const { page } = withSeededAnthropicConn;
    await page.goto("/ai-costs", { waitUntil: "domcontentloaded" });
    await page
      .getByRole("heading", { name: /ai spend intelligence/i })
      .waitFor({ state: "visible", timeout: 15_000 });
    await runAxe(page, "/ai-costs");
  });
});
