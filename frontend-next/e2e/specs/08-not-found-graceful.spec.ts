import { test, expect } from "../fixtures";

/**
 * Journey 8 — Unknown path renders gracefully.
 *
 * `/docs` is currently not implemented. We expect either:
 *   - Next.js' built-in 404 page (status 404 + "could not be found"), OR
 *   - the marketing nav still renders (i.e. the layout chrome doesn't crash).
 *
 * Either way, the response must be ≤ 404 (no 5xx) and the page body must
 * load without uncaught exceptions.
 */
test.describe("404 / unknown route", () => {
  test("hitting /docs does not crash the app", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));

    const resp = await page.goto("/docs", { waitUntil: "domcontentloaded" });
    expect(resp, "navigation response should exist").not.toBeNull();
    const status = resp?.status() ?? 0;
    expect(status, "should be 200 or 404, never 5xx").toBeLessThan(500);

    // Either the body shows the 404 copy or the page chrome rendered ok.
    const bodyText = (await page.textContent("body")) ?? "";
    const hasNotFoundCopy =
      /could not be found|404|page not found/i.test(bodyText);
    const hasMarketingNav = /costly/i.test(bodyText);
    expect(
      hasNotFoundCopy || hasMarketingNav,
      "expected either a 404 page or app chrome",
    ).toBe(true);

    expect(
      consoleErrors,
      "no uncaught page errors are allowed on the 404 path",
    ).toEqual([]);
  });
});
