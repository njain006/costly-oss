# Frontend Unit Tests

Vitest + React Testing Library + MSW. Tests live next to source code as
`*.test.ts` / `*.test.tsx`, plus a small handful of cross-cutting tests in
this `test/` directory (snapshots, MSW handlers).

## Run

```bash
cd frontend-next
npm test                  # one-shot run
npm run test:watch        # watch mode (re-run on save)
npm run test:coverage     # v8 coverage report → ./coverage
npm run test:ui           # interactive web UI (optional)
```

The first run downloads `happy-dom`, `msw`, `@testing-library/*` and
`@vitejs/plugin-react`. After that, a full unit run is < 5 seconds on a
modern laptop.

## Layout

```
frontend-next/
├── vitest.config.ts          # entry point — Vitest config
├── vitest.setup.ts           # global setup (jest-dom, MSW, polyfills)
├── src/
│   ├── lib/
│   │   ├── anomalies.ts
│   │   ├── anomalies.test.ts
│   │   ├── format.ts
│   │   └── format.test.ts
│   ├── components/
│   │   ├── stat-card.tsx
│   │   ├── stat-card.test.tsx
│   │   ├── date-range-picker.tsx
│   │   ├── date-range-picker.test.tsx
│   │   ├── demo-banner.tsx
│   │   ├── demo-banner.test.tsx
│   │   └── anomalies/
│   │       ├── anomaly-row.tsx
│   │       └── anomaly-row.test.tsx
│   └── app/(dashboard)/anomalies/
│       ├── page.tsx
│       └── page.test.tsx
└── test/
    ├── README.md             # this file
    ├── charts.snapshot.test.tsx
    └── mocks/
        ├── handlers.ts       # default MSW handlers (mirrors backend routers)
        └── server.ts         # MSW Node server
```

## Adding a test

### Pure functions (lib/)

```ts
import { describe, expect, it } from "vitest";
import { formatCurrency } from "./format";

describe("formatCurrency", () => {
  it("formats whole dollars", () => {
    expect(formatCurrency(42)).toBe("$42");
  });
});
```

### Components

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MyButton from "./my-button";

describe("<MyButton />", () => {
  it("calls onClick when pressed", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<MyButton onClick={onClick} label="Save" />);
    await user.click(screen.getByRole("button", { name: /save/i }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});
```

### Pages that hit the API

Use `screen.findBy*` (async) for anything rendered after a fetch resolves.
Override MSW handlers per test with `server.use(...)`:

```tsx
import { http, HttpResponse } from "msw";
import { server } from "../../../test/mocks/server";

it("renders the row from API data", async () => {
  server.use(
    http.get("*/api/anomalies", () =>
      HttpResponse.json({ anomalies: [{ /* … */ }] }),
    ),
  );
  render(<AnomaliesPage />);
  expect(await screen.findAllByRole("article")).toHaveLength(1);
});
```

## Updating snapshots

Snapshot tests live in `test/charts.snapshot.test.tsx`. To regenerate after
an intentional Recharts upgrade or chart-shape change:

```bash
npm test -- -u
```

Review the diff carefully — a snapshot change is a contract change for any
downstream consumer that screenshots these charts.

## Coverage

Coverage uses the v8 provider (no babel instrumentation) and writes to
`./coverage/`. Floor thresholds are set in `vitest.config.ts`:

| Metric    | Floor |
|-----------|-------|
| Lines     | 30%   |
| Functions | 30%   |
| Statements| 30%   |
| Branches  | 50%   |

These are intentionally low for the first batch — ratchet them up as
coverage grows. The CI job uploads `coverage/` as an artifact.

## What NOT to test

- **`src/components/ui/*`** — these are vendored shadcn/ui primitives.
  They have their own upstream tests; we don't fork them.
- **Tailwind class strings** — assert on behaviour, not on `className`
  contents. Class names are an implementation detail and change often.
- **Exact icon SVG paths** — we test "an svg renders", not the path data.
  Lucide icon updates would otherwise break unrelated tests.
- **Next.js framework code** — `next/router`, `next/image`, `next/link`
  are mocked. Trust Next, not your mock.
- **Network behaviour beyond the contract** — happy-path + one error path
  per endpoint is enough at the unit level. Use Playwright for full
  request orchestration (retry, refresh, race conditions).

## Troubleshooting

### "ReferenceError: ResizeObserver is not defined"

Already polyfilled in `vitest.setup.ts`. If a new dependency needs another
DOM API, add the polyfill there.

### "MSW: warning — captured a request without a matching handler"

Either add a handler in `test/mocks/handlers.ts` (if it's a default for
all tests) or override per-test with `server.use(...)`.

### "Cannot find module '@/lib/foo'"

The `@/*` alias is resolved by `vite-tsconfig-paths`. Confirm the import
matches a path under `src/`.
