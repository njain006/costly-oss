import { Page, Locator, expect } from "@playwright/test";

/**
 * Setup / connectors catalog page (`/setup`).
 *
 * The page lists 18 connectors grouped into six categories. AI category
 * appears first per the current pitch. Each card has a "Connect" link
 * deep-linking to `/platforms?add=<key>`.
 */
export class SetupPage {
  readonly page: Page;
  readonly headline: Locator;
  readonly categories: Locator;
  readonly connectorCards: Locator;
  readonly aiCategoryHeading: Locator;
  readonly claudeCodeCard: Locator;
  readonly anthropicCard: Locator;

  constructor(page: Page) {
    this.page = page;
    this.headline = page.getByRole("heading", {
      level: 1,
      name: /connect your ai .* data stack/i,
    });
    // Each category renders an `<h2>` (AI & LLM APIs, Pipelines, Warehouses, …)
    this.categories = page.locator("h2");
    // Each connector card has a "Connect" CTA — count those to count cards.
    this.connectorCards = page.getByRole("link", { name: /^connect\s*$/i });
    this.aiCategoryHeading = page.getByRole("heading", {
      level: 2,
      name: /ai .* llm apis/i,
    });
    this.claudeCodeCard = page
      .locator("div", { has: page.getByText(/^Claude Code$/) })
      .filter({ hasText: /subscription \(max\/pro\) usage/i })
      .first();
    this.anthropicCard = page
      .locator("div", { has: page.getByText(/^Anthropic API$/) })
      .first();
  }

  async goto() {
    await this.page.goto("/setup", { waitUntil: "domcontentloaded" });
    await expect(this.headline).toBeVisible();
  }

  async getConnectorCount(): Promise<number> {
    return await this.connectorCards.count();
  }

  /**
   * Returns the category headings in the order they appear on the page.
   * Used to assert AI is first.
   */
  async getCategoryOrder(): Promise<string[]> {
    return await this.categories.allTextContents();
  }
}
