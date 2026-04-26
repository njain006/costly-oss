import { test, expect } from "../fixtures";

/**
 * Smoke tests against the public demo API.
 *
 * These run very fast (<2s total) and catch the most common regression:
 * the demo backend going dark or changing its response shape. They run
 * first (the `00-` prefix) so a deployment-wide outage shows up as the
 * first red dot, not the 14th.
 *
 * Read-only — safe to run against production.
 */
test.describe("Public demo API smoke", () => {
  test("dashboard endpoint serves demo data", async ({ request }) => {
    const resp = await request.get("/api/demo/dashboard?days=7");
    expect(resp.ok()).toBe(true);
    const data = await resp.json();
    expect(data.demo).toBe(true);
    expect(data.daily_costs).toBeDefined();
  });

  test("unified platform costs endpoint serves multi-platform data", async ({
    request,
  }) => {
    const resp = await request.get("/api/demo/platforms/costs?days=7");
    expect(resp.ok()).toBe(true);
    const data = await resp.json();
    expect(data.total_cost).toBeGreaterThan(0);
    expect(data.by_platform.length).toBeGreaterThan(0);
    expect(data.by_category.length).toBeGreaterThan(0);
    expect(data.daily_trend.length).toBe(7);
  });

  test("supported-platforms list includes the canonical 5 connectors", async ({
    request,
  }) => {
    const resp = await request.get("/api/demo/platforms/supported");
    expect(resp.ok()).toBe(true);
    const data = await resp.json();
    expect(data.platforms.length).toBeGreaterThanOrEqual(15);
    for (const slug of [
      "aws",
      "openai",
      "fivetran",
      "databricks",
      "github",
    ]) {
      expect(data.platforms, `missing connector slug: ${slug}`).toContain(slug);
    }
  });

  test("ai-costs demo endpoint returns provider rows", async ({ request }) => {
    const resp = await request.get("/api/demo/ai-costs?days=7");
    expect(resp.ok()).toBe(true);
    const data = await resp.json();
    expect(data.kpis).toBeDefined();
    expect(typeof data.kpis.cache_hit_rate).toBe("number");
    expect(Array.isArray(data.providers)).toBe(true);
    expect(data.providers.length).toBeGreaterThan(0);
    expect(Array.isArray(data.recommendations)).toBe(true);
  });
});
