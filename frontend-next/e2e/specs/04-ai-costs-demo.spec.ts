import { test, expect } from "../fixtures";
import { AiCostsPage } from "../poms";

/**
 * Journey 4 — `/ai-costs` page in demo mode.
 *
 * Asserts that the AI Spend Intelligence page renders:
 *   - Cache Hit Rate KPI tile
 *   - Daily Tokens by Tier chart
 *   - At least one AI cost recommendation
 */
test.describe("AI costs (demo)", () => {
  test("renders cache hit rate KPI, tokens-by-tier chart, and recommendations", async ({
    withSeededAnthropicConn,
  }) => {
    const { page, conn } = withSeededAnthropicConn;
    expect(
      conn.hasDemoCostsRendered,
      "demo /api/demo/ai-costs should include an Anthropic provider row",
    ).toBe(true);

    const aiCosts = new AiCostsPage(page);
    await aiCosts.goto();

    await expect(aiCosts.cacheHitRateCard).toBeVisible();
    await expect(aiCosts.totalAiSpendCard).toBeVisible();
    await expect(aiCosts.totalTokensCard).toBeVisible();
    await expect(aiCosts.dailyTokensByTierChart).toBeVisible();
    await expect(aiCosts.providerComparisonTable).toBeVisible();
    await expect(aiCosts.recommendationsHeading).toBeVisible();

    const recCount = await aiCosts.getRecommendationCount();
    expect(recCount).toBeGreaterThan(0);
  });
});
