import { test, expect } from "../fixtures";
import { OverviewPage } from "../poms";

/**
 * Journey 3 — `/demo` redirect → `/overview` with seeded data.
 *
 * The `/demo` page seeds `costly_demo=1` in localStorage and redirects to
 * `/overview`. With demo enabled, the dashboard renders KPI tiles based on
 * `/api/demo/platforms/costs`.
 */
test.describe("Demo overview", () => {
  test("/demo redirects to /overview and renders KPI tiles", async ({
    page,
  }) => {
    await page.goto("/demo");

    // The demo page does a useEffect-driven router.replace — wait for the
    // pathname to settle on /overview.
    await page.waitForURL(/\/overview$/, { timeout: 15_000 });

    const overview = new OverviewPage(page);
    await expect(overview.heading).toBeVisible();

    // KPI tiles render once /api/demo/platforms/costs has resolved.
    await expect(page.getByText(/^Total Spend$/i).first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/^Daily Average$/i).first()).toBeVisible();
    await expect(page.getByText(/^AI Spend$/i).first()).toBeVisible();
  });
});
