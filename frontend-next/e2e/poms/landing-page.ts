import { Page, Locator, expect } from "@playwright/test";

/**
 * Marketing landing page (`/`).
 *
 * Mirrors the public costly homepage at https://costly.cdatainsights.com.
 * Selectors prefer accessible roles + visible text — no test IDs exist on
 * the marketing page yet, and we don't want to add them just for tests.
 */
export class LandingPage {
  readonly page: Page;
  readonly headline: Locator;
  readonly heroSubheadline: Locator;
  readonly tryDemoCta: Locator;
  readonly starOnGithubCta: Locator;
  readonly getStartedCta: Locator;
  readonly logInLink: Locator;
  readonly pricingLink: Locator;
  readonly setupLink: Locator;
  readonly footer: Locator;
  readonly githubFooterLink: Locator;
  readonly platformPills: Locator;

  constructor(page: Page) {
    this.page = page;
    // Headline reads "See every dollar your AI and data stack costs" split
    // across two lines via <br/>. Match the "AI and data stack costs" gradient
    // span which is unique on the page.
    this.headline = page.getByRole("heading", {
      level: 1,
      name: /AI and data stack costs/i,
    });
    this.heroSubheadline = page.getByText(/open-source AI agent for your/i);
    this.tryDemoCta = page
      .getByRole("link", { name: /try live demo/i })
      .first();
    this.starOnGithubCta = page.getByRole("link", { name: /star on github/i });
    this.getStartedCta = page
      .getByRole("link", { name: /get started/i })
      .first();
    this.logInLink = page.getByRole("link", { name: /log in/i }).first();
    this.pricingLink = page.getByRole("link", { name: /pricing/i }).first();
    this.setupLink = page.getByRole("link", { name: /^setup$/i }).first();
    this.footer = page.locator("footer");
    this.githubFooterLink = this.footer.getByRole("link", {
      name: /github\.com\/njain006\/costly-oss/i,
    });
    this.platformPills = page.locator("section").filter({
      hasText: /15\+ connectors across your entire data stack/i,
    });
  }

  async goto() {
    await this.page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(this.headline).toBeVisible();
  }

  async expectMarketingChrome() {
    await expect(this.headline).toBeVisible();
    await expect(this.tryDemoCta).toBeVisible();
    await expect(this.starOnGithubCta).toBeVisible();
    await expect(this.footer).toBeVisible();
  }
}
