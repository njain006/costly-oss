import { Page, Locator, expect } from "@playwright/test";

/**
 * AI Spend Intelligence page (`/ai-costs`).
 *
 * The demo endpoint `/api/demo/ai-costs` does NOT set `demo: true` in its
 * response, so this page renders KPI tiles + charts even without a real
 * connection — the demo fixture is enough.
 */
export class AiCostsPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly cacheHitRateCard: Locator;
  readonly totalAiSpendCard: Locator;
  readonly totalTokensCard: Locator;
  readonly dailyTokensByTierChart: Locator;
  readonly providerComparisonTable: Locator;
  readonly recommendationsList: Locator;
  readonly recommendationsHeading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", {
      level: 1,
      name: /ai spend intelligence/i,
    });
    this.cacheHitRateCard = page.getByText(/^Cache Hit Rate$/i).first();
    this.totalAiSpendCard = page.getByText(/^Total AI Spend$/i).first();
    this.totalTokensCard = page.getByText(/^Total Tokens$/i).first();
    this.dailyTokensByTierChart = page
      .locator("div")
      .filter({ has: page.getByText(/daily tokens by tier/i) })
      .first();
    this.providerComparisonTable = page
      .locator("div")
      .filter({ has: page.getByText(/provider comparison/i) })
      .first();
    this.recommendationsHeading = page.getByText(
      /ai cost recommendations/i,
    );
    // Each recommendation row contains a "Save ~$..." badge.
    this.recommendationsList = page.getByText(/^Save ~\$/);
  }

  async goto() {
    await this.page.goto("/ai-costs", { waitUntil: "domcontentloaded" });
    await expect(this.heading).toBeVisible();
  }

  async getRecommendationCount(): Promise<number> {
    return await this.recommendationsList.count();
  }
}
