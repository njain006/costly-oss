import { test, expect } from "../fixtures";
import { IS_PUBLIC_ONLY } from "../fixtures";

/**
 * Journey 7 — Register → automatic login.
 *
 * Skipped against the deployed environment to avoid creating real users
 * in the prod MongoDB. Runs against local CI / dev only.
 */
test.describe("Auth — register and login", () => {
  test.skip(
    IS_PUBLIC_ONLY,
    "Skipped against deployed env — would mutate prod state",
  );

  test("user can register a new account and is sent to onboarding/overview", async ({
    page,
    uniqueUser,
  }) => {
    await page.goto("/login");

    // Activate the Register tab.
    await page.getByRole("tab", { name: /^register$/i }).click();

    await page.getByLabel(/full name/i).fill(uniqueUser.name);
    await page.getByLabel(/^email$/i).fill(uniqueUser.email);
    await page.getByLabel(/^password$/i).fill(uniqueUser.password);

    await page.getByRole("button", { name: /create account/i }).click();

    // After register, /login redirects via /platforms probe → onboarding or
    // /overview. Either is acceptable.
    await page.waitForURL(/\/(onboarding|overview)$/, { timeout: 20_000 });

    // The auth provider should have written a token + user to localStorage.
    const token = await page.evaluate(() =>
      window.localStorage.getItem("costly_token"),
    );
    expect(token, "JWT access token should be persisted").toBeTruthy();

    const userJson = await page.evaluate(() =>
      window.localStorage.getItem("costly_user"),
    );
    expect(userJson, "user record should be persisted").toBeTruthy();
    const user = JSON.parse(userJson || "{}");
    expect(user.email).toBe(uniqueUser.email);
  });
});
