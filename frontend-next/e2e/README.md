# Costly E2E Tests

Playwright end-to-end suite for the costly frontend.

## Layout

```
e2e/
├── fixtures/        Shared Playwright test.extend() fixtures + types
│   ├── test.ts        custom `test`/`expect` exports + demoUser, authenticatedPage,
│   │                  withSeededAnthropicConn, uniqueUser
│   ├── types.ts       narrow types + IS_PUBLIC_ONLY guard
│   └── index.ts       re-exports
├── poms/            Page Object Models — typed selectors + actions
│   ├── landing-page.ts
│   ├── setup-page.ts
│   ├── overview-page.ts
│   ├── ai-costs-page.ts
│   ├── anomalies-page.ts
│   ├── platforms-page.ts
│   └── index.ts
├── specs/           The actual journey tests (numbered for readable order)
│   ├── 00-api-smoke.spec.ts
│   ├── 01-marketing-landing.spec.ts
│   ├── 02-setup-catalog.spec.ts
│   ├── 03-demo-overview.spec.ts
│   ├── 04-ai-costs-demo.spec.ts
│   ├── 05-anomalies-mute.spec.ts
│   ├── 06-platforms-claude-code-deeplink.spec.ts
│   ├── 07-register-then-login.spec.ts
│   ├── 08-not-found-graceful.spec.ts
│   └── 09-accessibility.spec.ts
├── landing.spec.ts        (empty stub — moved to specs/)
├── demo-dashboard.spec.ts (empty stub — moved to specs/)
└── README.md        this file
```

`testDir` in `playwright.config.ts` is scoped to `./e2e/specs`, so the
POM/fixture files (also `.ts`) are never scanned as test sources.

## Running locally

In one shell, start the app:

```bash
cd frontend-next
npm run dev          # http://localhost:3000
# (the backend on :8000 is reverse-proxied via next.config rewrites)
```

In another shell, run the tests:

```bash
cd frontend-next
npm run e2e          # all projects (chromium + webkit + mobile-chrome)
npm run e2e:headed   # watch the browser
npm run e2e:ui       # Playwright UI mode
npm run e2e:list     # enumerate without running
npm run e2e:report   # open the last HTML report
```

Pin a single browser:

```bash
npx playwright test --project=chromium
```

## Running against the deployed site (read-only)

```bash
npm run e2e:deployed
# == BASE_URL=https://costly.cdatainsights.com PUBLIC_ONLY=1 playwright test
```

`PUBLIC_ONLY=1` instructs the suite to skip any test that mutates server
state (currently just the register/login journey). The deployed CI job in
`.github/workflows/e2e-deployed.yml` runs with this env on a schedule and
on push to `main`.

## How the demo fixture works

`/demo` writes `costly_demo=1` to localStorage and redirects to `/overview`.
The `enableDemoMode(page)` helper in `fixtures/test.ts` does the same thing
via an `addInitScript` so dashboard pages can be hit directly. The
authenticated dashboard layout treats `isDemo` and `user` interchangeably
when deciding whether to render — see
`src/app/(dashboard)/layout.tsx`.

`api.ts` rewrites every `/api/*` call to `/api/demo/*` while demo mode is
active, so the tests exercise the real Next.js + FastAPI plumbing without
needing any credentials.

## Accessibility checks

`09-accessibility.spec.ts` runs `@axe-core/playwright` against the
marketing landing, `/overview` (demo), and `/ai-costs` (demo). It fails
the build only on `critical` or `serious` violations — `moderate` and
`minor` issues are logged for triage.

## Adding a new journey

1. **Map the page** — add or extend a POM under `e2e/poms/`. Selectors
   prefer accessible roles (`getByRole`, `getByLabel`, `getByText`) over
   CSS classes. If you must add a `data-testid`, do so in the component
   source, not in a wrapping div.
2. **Add a spec** under `e2e/specs/NN-short-name.spec.ts`. Use the shared
   `test`/`expect` from `../fixtures` (not `@playwright/test` directly)
   so all journeys share the same fixtures.
3. **Pick a fixture**:
   - Public marketing pages → bare `page`.
   - Anything under `(dashboard)/` → `authenticatedPage` (demo session).
   - Anything that needs AI cost data → `withSeededAnthropicConn`.
   - Anything that needs a fresh per-run user → `uniqueUser`.
4. **Mark deployed-unsafe** tests with `test.skip(IS_PUBLIC_ONLY, …)` if
   they would mutate prod state.

## Updating screenshots

Failure screenshots are written to `frontend-next/test-results/`. To
intentionally update visual regression baselines (none yet — see
`docs/lanes/tests-e2e.md` for the Percy roadmap), use:

```bash
npx playwright test --update-snapshots
```

## Debugging a flake

```bash
# Re-run the same spec 10 times to expose flakiness.
npx playwright test specs/05-anomalies-mute.spec.ts --repeat-each=10

# Run with traces, then open the trace viewer.
npx playwright test specs/05-anomalies-mute.spec.ts --trace on
npx playwright show-trace test-results/.../trace.zip
```

## CI

Two workflows exercise this suite:

- `.github/workflows/ci.yml` job `e2e-tests` — boots a local FastAPI +
  Next.js stack, runs the full chromium project on PRs.
- `.github/workflows/e2e-deployed.yml` — runs the read-only subset
  against `https://costly.cdatainsights.com` on a schedule + on push to
  `main`.
