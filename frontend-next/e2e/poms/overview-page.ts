import { Page, Locator, expect } from "@playwright/test";

/**
 * Overview / unified-cost dashboard page (`/overview`).
 *
 * Behind the dashboard route group — requires either a real session or
 * `costly_demo=1` in localStorage. The `withDemoSession` fixture handles
 * that; tests just call `goto()`.
 */
export class OverviewPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly dateRangeButtons: Locator;
  readonly statCards: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", {
      level: 1,
      name: /platform overview/i,
    });
    // Date range pill row at the top right of the header.
    this.dateRangeButtons = page.getByRole("button", {
      name: /^(7|14|30|90) days$/i,
    });
    // The page renders a row of StatCard tiles. Use the StatCard root class
    // which is consistent across pages — see `src/components/stat-card.tsx`.
    this.statCards = page.locator("[data-stat-card], .stat-card").or(
      page.locator("div", { hasText: /total spend|daily avg|ai inference/i })
    );
  }

  async goto() {
    await this.page.goto("/overview", { waitUntil: "domcontentloaded" });
    // Wait for either the empty state or the loaded heading.
    await expect(this.heading).toBeVisible();
  }

  /** True when the demo dashboard data has rendered KPI tiles. */
  async hasKpiTiles(): Promise<boolean> {
    // Demo data always contains the "Total Spend" tile.
    const totalSpend = this.page.getByText(/total spend/i).first();
    await totalSpend.waitFor({ state: "visible", timeout: 15_000 });
    return await totalSpend.isVisible();
  }
}
