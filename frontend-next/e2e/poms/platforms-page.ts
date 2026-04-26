import { Page, Locator, expect } from "@playwright/test";

/**
 * Platforms / connectors page (`/platforms`).
 *
 * Supports a `?add=<key>` query param to deep-link the connect dialog open.
 * The Setup page links here via that pattern, e.g. `?add=claude_code`.
 */
export class PlatformsPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly connectDialog: Locator;
  readonly dialogTitle: Locator;
  readonly cancelButton: Locator;
  readonly jsonlUploadHint: Locator;
  readonly jsonlUploadInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", {
      level: 1,
      name: /platforms|connectors/i,
    });
    this.connectDialog = page.getByRole("dialog");
    this.dialogTitle = this.connectDialog.locator("h2, [role=heading]").first();
    this.cancelButton = page.getByRole("button", { name: /^cancel$/i });
    // For Claude Code the dialog renders a JSONL upload hint block — it lists
    // ~/.claude/projects/ paths and shows the "Where to find the files:" copy.
    this.jsonlUploadHint = page.getByText(/where to find the files:/i);
    this.jsonlUploadInput = page.locator('input[type="file"]');
  }

  async goto(query = "") {
    const url = query ? `/platforms?${query}` : "/platforms";
    await this.page.goto(url, { waitUntil: "domcontentloaded" });
    await expect(this.heading).toBeVisible();
  }

  async closeDialog() {
    await this.cancelButton.click();
    await expect(this.connectDialog).toBeHidden();
  }
}
