import { test, expect } from "../fixtures";
import { SetupPage } from "../poms";

/**
 * Journey 2 — `/setup` connector catalog.
 *
 * Asserts:
 *   - all 18 connector cards render
 *   - the "AI & LLM APIs" category appears first
 *   - Claude Code is present (the local-transcript connector — pitched
 *     alongside the Anthropic API connector)
 */
test.describe("Setup connector catalog", () => {
  test("lists 18 connector cards with AI category first", async ({ page }) => {
    const setup = new SetupPage(page);
    await setup.goto();

    const count = await setup.getConnectorCount();
    expect(count, "expected exactly 18 connector cards").toBe(18);

    const order = await setup.getCategoryOrder();
    expect(order.length).toBeGreaterThanOrEqual(6);
    expect(order[0]).toMatch(/ai .* llm apis/i);
  });

  test("Claude Code and Anthropic API cards are present in the AI section", async ({
    page,
  }) => {
    const setup = new SetupPage(page);
    await setup.goto();

    await expect(setup.aiCategoryHeading).toBeVisible();
    await expect(setup.claudeCodeCard).toBeVisible();
    await expect(setup.anthropicCard).toBeVisible();

    // Connect cards should deep-link to /platforms?add=<key>.
    const connectLinks = page.getByRole("link", {
      name: /^connect\s*$/i,
    });
    const hrefs = await connectLinks.evaluateAll((els) =>
      (els as HTMLAnchorElement[]).map((a) => a.getAttribute("href")),
    );
    expect(hrefs).toContain("/platforms?add=claude_code");
    expect(hrefs).toContain("/platforms?add=anthropic");
  });
});
