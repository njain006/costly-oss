import { Page, Locator, expect } from "@playwright/test";

/**
 * Anomalies page (`/anomalies`).
 *
 * Mute / mark-expected / acknowledge state is local-only, persisted in
 * `localStorage` under the key `costly_anomaly_state_v1`. Tests assert
 * that key changes after a mute action.
 */
export const ANOMALY_STORAGE_KEY = "costly_anomaly_state_v1";

export class AnomaliesPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly anomalyRows: Locator;
  readonly mutedTab: Locator;
  readonly openTab: Locator;
  readonly allTab: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", {
      level: 1,
      name: /anomalies/i,
    });
    // Tabs are radix Tabs — match by accessible role.
    this.allTab = page.getByRole("tab", { name: /^all/i });
    this.openTab = page.getByRole("tab", { name: /^open/i });
    this.mutedTab = page.getByRole("tab", { name: /^muted/i });
    // Each anomaly row exposes a "Mute" menu trigger button.
    this.anomalyRows = page.getByRole("button", { name: /mute/i });
  }

  async goto() {
    await this.page.goto("/anomalies", { waitUntil: "domcontentloaded" });
    await expect(this.heading).toBeVisible();
  }

  async getAnomalyRowCount(): Promise<number> {
    return await this.anomalyRows.count();
  }

  /**
   * Read the persisted local anomaly state. Useful for asserting that a
   * mute action actually wrote to localStorage.
   */
  async getLocalState(): Promise<unknown> {
    return await this.page.evaluate(
      (key) => JSON.parse(window.localStorage.getItem(key) || "null"),
      ANOMALY_STORAGE_KEY,
    );
  }

  async clearLocalState() {
    await this.page.evaluate(
      (key) => window.localStorage.removeItem(key),
      ANOMALY_STORAGE_KEY,
    );
  }
}
