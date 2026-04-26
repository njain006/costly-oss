# Lane: TESTS-FRONTEND-UNIT

> Branch: `lane/tests-frontend-unit`
> Owner: tests-frontend-unit lane agent
> Scope: `frontend-next/` (test runner, configs, tests), this doc, and a single
> additive `frontend-unit` job in `.github/workflows/ci.yml`.

## Purpose

Stand up component-level testing for the Next.js frontend. The repo had only
Playwright E2E plus one TypeScript-only inline test harness in
`src/lib/anomalies.test.ts`. This lane introduces a real unit test runner,
mocks, fixtures, and the first batch of component + page tests.

## Done

### Framework choice

- **Vitest 2.x** + React Testing Library + happy-dom + MSW 2.
  - Vitest over Jest because the repo is ESM-first (Next.js 16 + Tailwind 4),
    Vitest has zero babel config, and shares Vite's ESBuild transformer.
    See https://vitest.dev/guide/comparisons.html — Vitest's first-class ESM
    + TS, in-source snapshots, and `expect.extend` parity with Jest are all
    a net win in this stack.
  - happy-dom over jsdom because: ~3x faster boot, Recharts + Radix work
    with the polyfills we add in `vitest.setup.ts`, and we don't need
    jsdom-specific APIs like `JSDOM.fromFile`.
  - MSW 2 for API mocking because the same handlers can be reused by E2E
    later (msw + Playwright).

### Files added

- `frontend-next/vitest.config.ts` — Vitest config with v8 coverage,
  happy-dom env, `@/*` path alias via `vite-tsconfig-paths`, coverage
  thresholds (lines/funcs/stmts ≥ 30%, branches ≥ 50%).
- `frontend-next/vitest.setup.ts` — global setup. Wires jest-dom matchers,
  MSW lifecycle hooks, polyfills (`matchMedia`, `ResizeObserver`,
  `IntersectionObserver`), mocks for `next/navigation` and `next/link`.
- `frontend-next/test/mocks/handlers.ts` — default MSW handlers for every
  `/api/*` endpoint the components exercise. Mirrors
  `backend/app/routers/{anomalies,connections,platforms,dashboard,costs,auth}.py`.
- `frontend-next/test/mocks/server.ts` — MSW Node server.
- `frontend-next/test/charts.snapshot.test.tsx` — Recharts SVG snapshot
  guard so a Recharts upgrade can't silently break chart shapes.
- `frontend-next/test/README.md` — how to run, add, debug, and what NOT to
  test.

### Tests added

| File | Type | Cases |
|------|------|-------|
| `src/lib/anomalies.test.ts` | unit (port from inline harness) | 17 |
| `src/lib/format.test.ts` | unit (table-driven) | 28 (4 fns × 7 rows) |
| `src/components/stat-card.test.tsx` | component | 5 |
| `src/components/date-range-picker.test.tsx` | component (uses real provider) | 3 |
| `src/components/demo-banner.test.tsx` | component (3 render paths via MSW) | 3 |
| `src/components/anomalies/anomaly-row.test.tsx` | component | 7 |
| `src/app/(dashboard)/anomalies/page.test.tsx` | page (MSW + localStorage round-trip) | 3 |
| `test/charts.snapshot.test.tsx` | snapshot | 1 |

**Total: 67 test cases across 8 files.**

### CI

- New `frontend-unit` job in `.github/workflows/ci.yml`. Runs on every
  push/PR, caches `npm` deps via the existing
  `frontend-next/package-lock.json`, runs `npm run test:coverage`, uploads
  the `coverage/` directory as a build artifact.
- Coverage stays out of git via the existing `coverage/` entry in
  `.gitignore`.

### npm scripts

```
"test":           "vitest run",
"test:watch":     "vitest",
"test:coverage":  "vitest run --coverage",
"test:ui":        "vitest --ui"
```

## Backlog

In priority order:

1. **Storybook 8 + Chromatic** — visual regression for `<StatCard />`,
   `<AnomalyRow />`, `<DemoBanner />` and Recharts panels. Storybook will
   double as on-boarding docs for new contributors. Chromatic handles
   diffing on every PR.
2. **axe-core component-level a11y** — wrap the existing render helpers
   with `@axe-core/react` assertions; gate at zero new violations per
   touched component.
3. **`useApi` hook tests** — currently the hook is exercised indirectly
   via the page test. Add a dedicated `src/hooks/use-api.test.tsx` that
   covers loading, success, error, refetch, and cancel-on-unmount paths
   using `renderHook`.
4. **Auth provider tests** — login/logout/demo lifecycle, localStorage
   round-trip, token refresh interaction with the axios interceptor.
5. **Coverage ratchet** — start at 30%/50% floor; raise by 5 points each
   merge until lines ≥ 70%, branches ≥ 75%.
6. **Coverage diff comment on PRs** — wire `vitest --coverage` JSON
   summary into a github-script step to comment % delta vs `main`.
7. **Mutation testing (StrykerJS)** — once unit coverage is mature,
   introduce mutation testing on `src/lib/` to catch assertion-skin tests.
8. **Component testing in Playwright (`@playwright/experimental-ct-react`)**
   — useful for components that need real browser layout (Recharts
   responsive sizing, virtualized lists). Keep Vitest as the default;
   reserve Playwright CT for the small subset that needs it.

## Notes for other lanes

- Tests are located alongside source. Lanes adding new components should
  add a sibling `*.test.tsx` (see `frontend-next/test/README.md`).
- If you add a new `/api/*` endpoint, also add a default handler in
  `frontend-next/test/mocks/handlers.ts` so other components don't fail
  with surprise 500s in tests.
- DO NOT remove the `next/navigation` and `next/link` mocks in
  `vitest.setup.ts` — they keep the test runtime decoupled from the Next
  App Router runtime.
