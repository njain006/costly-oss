# Lane: tests-e2e

End-to-end testing for the costly frontend. Source lives under
`frontend-next/e2e/`. See `frontend-next/e2e/README.md` for the
contributor guide.

## Done

- **Playwright config** (`frontend-next/playwright.config.ts`)
  - Project matrix: chromium + webkit + mobile-chrome (Pixel 7) for local
    + local-stack CI; chromium-only for deployed read-only smoke runs.
  - Reporters: `html` (always), `list` (local), `github` (CI), `json`
    (CI artifact).
  - `screenshot: "only-on-failure"`, `video: "retain-on-failure"`,
    `trace: "on-first-retry"`.
  - `baseURL` from `BASE_URL` env (default `http://localhost:3000`).
  - `forbidOnly` + 2 retries when `CI=1`.
- **Eight critical journey specs** under `e2e/specs/`:
  - `00-api-smoke` — public demo API smoke
  - `01-marketing-landing` — headline + Star on GitHub + footer
  - `02-setup-catalog` — 18 connector cards, AI-first, Claude Code present
  - `03-demo-overview` — `/demo` redirect → `/overview` KPIs render
  - `04-ai-costs-demo` — cache hit rate + tokens-by-tier + recommendations
  - `05-anomalies-mute` — list renders, mute persists in localStorage
  - `06-platforms-claude-code-deeplink` — `?add=claude_code` opens dialog
    with JSONL upload section + "Where to find files" hint
  - `07-register-then-login` — register → token persisted (skipped on
    deployed env)
  - `08-not-found-graceful` — `/docs` returns ≤ 404 with no JS errors
- **Page Object Model** (`e2e/poms/`):
  - `LandingPage`, `SetupPage`, `OverviewPage`, `AiCostsPage`,
    `AnomaliesPage`, `PlatformsPage`. All export typed locators and
    action helpers; selectors prefer `getByRole` / `getByText`.
- **Shared fixtures** (`e2e/fixtures/test.ts`) via `test.extend()`:
  - `demoUser` — frozen demo user object
  - `authenticatedPage` — Page with `costly_demo=1` seeded via
    `addInitScript`
  - `withSeededAnthropicConn` — same plus a probe of
    `/api/demo/ai-costs` to confirm the demo provider data shape
  - `uniqueUser` — per-test-run unique email/password/name
- **Accessibility checks** (`09-accessibility.spec.ts`) using
  `@axe-core/playwright`:
  - Marketing landing, `/overview` (demo), `/ai-costs` (demo).
  - Fails build on `critical` or `serious` violations only;
    `moderate`/`minor` issues are logged for triage.
  - Tags: `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`.
- **CI**:
  - Existing `ci.yml::e2e-tests` job continues to run against a local
    FastAPI + Next.js stack on every PR (chromium-only, full mutation
    suite).
  - New `.github/workflows/e2e-deployed.yml` runs the read-only subset
    against `https://costly.cdatainsights.com` on push to main, nightly
    cron (13:00 UTC), and manual dispatch. Uploads `playwright-report`
    + `test-results` artifacts (HTML report, traces, screenshots,
    videos).
- **Contributor docs** (`frontend-next/e2e/README.md`) — local + CI
  runbook, fixture catalogue, debugging recipes.

## In progress

- **Cross-browser coverage** of the deployed-smoke run: today only
  chromium runs against prod to keep wall-clock low. Once the suite is
  stable, expand to webkit on the nightly cron only.
- **Selector hardening** of Setup category cards. Today the count of
  connector cards leans on the `Connect` link role; if the marketing team
  ever adds a non-card "Connect" CTA, the count test will start lying.
  Plan: add `data-testid="connector-card"` to `PlatformCard` in
  `src/app/setup/page.tsx`.

## Backlog

- **Visual regression with Percy** — wire `@percy/playwright` into the
  deployed-smoke workflow for the marketing landing, `/overview`, and
  `/ai-costs`. Requires Percy project + `PERCY_TOKEN` repo secret.
- **Storybook + Chromatic for component tests** — the dashboard charts
  (recharts wrappers in `src/app/(dashboard)/overview/page.tsx`,
  `ai-costs/page.tsx`, `anomalies/page.tsx`) are the most common source
  of visual breakage. Component-level Chromatic runs would catch those
  before they hit the e2e suite.
- **Mobile Safari coverage** — currently we run mobile-chrome (Pixel 7)
  but not mobile-safari (iPhone 14). The webkit project covers desktop
  Safari, but iOS-specific layout quirks (notches, scroll bouncing,
  100svh handling) need their own matrix entry. Add
  `{ name: "mobile-safari", use: { ...devices["iPhone 14"] } }` to the
  config once we have the cycle budget.
- **Per-connector connect-flow tests** — today only Claude Code's
  deep-link dialog is exercised. Add equivalents for the 17 other
  connectors using the `?add=<key>` deep-link, asserting the dialog
  renders the expected credential fields. Probably one parameterized
  spec rather than 17 files.
- **Auth flow expansion** — register → logout → login with same
  credentials → token refresh. All require local-stack mode.
- **Anomaly seeding helper** — instead of writing the local state
  through `page.evaluate`, expose a tiny `e2e/helpers/anomalies.ts` that
  composes the same `muteSignature()` + `emptyLocalState()` functions
  used by `src/lib/anomalies.ts`. This would catch shape drift between
  the test seeder and production code.
- **Coverage reporting** — wire `playwright-test-coverage` (or the
  built-in Chromium coverage API) so we can track how much of the
  frontend bundle the e2e suite actually exercises. Useful to spot dead
  routes.
- **Lighthouse CI on the marketing landing** — separate from a11y;
  catches Core Web Vitals regressions on the public homepage.

## Operational notes

- Each commit on this branch must keep
  `cd frontend-next && npx playwright test --list` green (lane rule).
- `@axe-core/playwright` and the new `playwright` scripts in
  `package.json` are the only dependency changes — no runtime deps were
  added.
- The deployed-smoke workflow MUST stay read-only. If a journey ever
  needs to mutate, gate it on `IS_PUBLIC_ONLY` from
  `e2e/fixtures/types.ts`.
