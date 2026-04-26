import { test, expect } from "../fixtures";
import { PlatformsPage } from "../poms";

/**
 * Journey 6 — `/platforms?add=claude_code`.
 *
 * The deep-link from the Setup page should:
 *   - open the connect dialog
 *   - render the Claude Code JSONL upload section with the
 *     "Where to find the files" hint block
 */
test.describe("Platforms — Claude Code connect deep-link", () => {
  test("opens dialog with JSONL upload section visible", async ({
    authenticatedPage: page,
  }) => {
    const platforms = new PlatformsPage(page);
    await platforms.goto("add=claude_code");

    await expect(platforms.connectDialog).toBeVisible();
    await expect(platforms.connectDialog).toContainText(/claude code/i);
    await expect(platforms.jsonlUploadHint).toBeVisible();

    // The dialog should explain where to find the JSONL files.
    await expect(
      page.getByText(/~\/\.claude\/projects\//).first(),
    ).toBeVisible();
    await expect(
      page.getByText(/each project has its own folder/i),
    ).toBeVisible();

    // File input is present and accepts JSONL.
    await expect(platforms.jsonlUploadInput).toBeVisible();
    await expect(platforms.jsonlUploadInput).toHaveAttribute(
      "accept",
      /\.jsonl/,
    );
  });
});
