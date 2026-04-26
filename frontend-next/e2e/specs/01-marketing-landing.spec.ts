import { test, expect } from "../fixtures";
import { LandingPage } from "../poms";

/**
 * Journey 1 — Public marketing landing.
 *
 * Visitor lands on `/` and sees:
 *   - the AI/data stack headline
 *   - the "Star on GitHub" CTA in the hero
 *   - a footer with the github.com/njain006/costly-oss link
 */
test.describe("Marketing landing", () => {
  test("renders headline, Star on GitHub CTA, and footer", async ({ page }) => {
    const landing = new LandingPage(page);
    await landing.goto();

    await expect(page).toHaveTitle(/costly/i);

    await landing.expectMarketingChrome();
    await expect(landing.starOnGithubCta).toHaveAttribute(
      "href",
      /github\.com\/njain006\/costly-oss/,
    );
    await expect(landing.starOnGithubCta).toHaveAttribute(
      "target",
      "_blank",
    );
    await expect(landing.githubFooterLink).toBeVisible();
  });

  test("nav exposes pricing, setup, and login routes", async ({ page }) => {
    const landing = new LandingPage(page);
    await landing.goto();

    await expect(landing.pricingLink).toBeVisible();
    await expect(landing.setupLink).toBeVisible();
    await expect(landing.logInLink).toBeVisible();
    await expect(landing.getStartedCta).toBeVisible();
  });
});
