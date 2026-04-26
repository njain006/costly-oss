# Lane: UI

Persistent working notes for the UI lane (`lane/ui` branch, worktree
`.claude/worktrees/agent-af2a8e91c16596edb`).

Scope: `frontend-next/src/**` and `docs/**` only. No backend, no infra.

## Principles

- Ship one complete, shippable improvement per session. Always leave `cd frontend-next && npx next build` green.
- Prefer pure-logic modules (`frontend-next/src/lib/*.ts`) for anything testable without a DOM.
- When the backend is missing an endpoint the UI needs, degrade gracefully (client-side fallback, opt-in re-scan, localStorage overlays) and leave a TODO for the next lane.
- Everything honors dark mode, mobile, and a11y (aria labels, keyboard nav, focus ring).

## Done

### 2026-04-24 — Anomalies page (§4 of the spec)

Landed the timeline view at `/anomalies` with:

- Backend wired to `GET /api/anomalies?days=N`, `POST /api/anomalies/:id/acknowledge`, `POST /api/anomalies/detect`.
- Client-side mute / mark-expected / local-ack via localStorage, keyed on a stable anomaly signature (`scope::platform::resource::type`).
- Detail sheet with 14-day bar chart (anomaly day red), probable-cause classifier, and "Ask agent" deep links into `/chat`.
- Fallback: when backend has no anomalies, derive spikes client-side from `daily_trend` using a 2σ z-score rule.
- Pure-function tests in `src/lib/anomalies.test.ts`.
- Sidebar entry "Anomalies" between Recommendations and Alerts.

Files: see the change log at the bottom of `docs/dashboard-visualization-spec.md`.

## Backlog (pick one per session)

Priority order follows the spec's §10 implementation plan, adjusted for what is already shipped.

1. **Recommendations polish** (§5) — `[Apply via GitHub PR]` dry-run dialog with unified-diff preview (no real PR yet), group cards by impact tier (>$500 / $100–500 / <$100), "realized savings" header.
2. **Daily Spend stacked area** on `/overview` (§1.3) — currently hardcoded to `aws / snowflake / openai / other`. Make it dynamic from `by_platform`, legend-toggleable, and add a "Stacked / Grouped line / Calendar" switcher.
3. **Per-tool-call cost panel** on `/ai-costs` (§2.7) — horizontal bars for Bash/Edit/Read/WebFetch/Grep/Task/MCP with $/call inline. Needs `metadata.tool_use` extension on the Claude Code connector — until then, show an empty state with a "Connect Claude Code" CTA.
4. **Chat inline `costly-chart` markdown block** (§7.4) — parse ``` ```costly-chart ``` ``` code-fences emitted by the agent and render as real Recharts widgets inline.
5. **/platforms card polish** (§3.2–3.3) — connection-status colored top-bar, sparkline, last-sync freshness, grid/table toggle.
6. **Budgets page** (§6) — burn chart + alert rules. Higher effort, backend work likely required.
7. **Mute/mark-expected backend** — once it lands, remove the localStorage fallback in `src/lib/anomalies.ts`.

## In progress

(none)

## Conventions / gotchas

- Worktree doesn't have its own `node_modules`. Running `npx next build` against it from an unprivileged shell requires `npm install` (blocked in the automated lane). When onboarding, run `npm install` in `frontend-next/` once, then `npx next build` works.
- Any new chart must ship with loading / empty / error states. See `/anomalies` for the reference treatment.
- Dark-mode check: sample pages with `prefers-color-scheme: dark` or add `class="dark"` to `<html>` via devtools.
- Route names in this repo don't always match the spec — the spec's §4 lives at `/anomalies` (we kept `/alerts` for user-defined alert rules, separate concern).
- Pure-function tests live beside the module (e.g. `anomalies.test.ts`). There's no test runner configured yet; they are shaped for `vitest`/`node --test` and can be run manually with `npx tsx src/lib/anomalies.test.ts` once dependencies are installed.
