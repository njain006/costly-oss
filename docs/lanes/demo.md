# Lane: DEMO

Scope: make `/demo` feel like a real, impressive product tour. Live at costly.cdatainsights.com/demo.

Primary files:
- `backend/app/services/demo.py`
- `backend/app/services/demo_platforms.py`
- `backend/app/routers/public_demo.py`
- `backend/tests/test_demo_*`
- frontend empty-state branches in `frontend-next/src/app/(dashboard)/*/page.tsx`

## Endpoint audit (done)

| Frontend call | Demo equivalent | Status |
|---|---|---|
| `/dashboard` | `/api/demo/dashboard` | done (rich) |
| `/costs` | `/api/demo/costs` | done |
| `/costs/attribution` | `/api/demo/cost-attribution` | done |
| `/ai-costs` | `/api/demo/ai-costs` | done, enriched with tool_use breakdown |
| `/queries` | `/api/demo/queries` | done |
| `/storage` | `/api/demo/storage` | done |
| `/warehouses` | `/api/demo/warehouses` | done |
| `/warehouses/sizing` | `/api/demo/warehouses/sizing` | done |
| `/warehouses/autosuspend` | `/api/demo/warehouses/autosuspend` | done |
| `/spillage` | `/api/demo/spillage` | done |
| `/query-patterns` | `/api/demo/query-patterns` | done |
| `/stale-tables` | `/api/demo/stale-tables` | done |
| `/recommendations` | `/api/demo/recommendations` | upgraded (ddl, effort, priority, PR body) |
| `/workloads` | `/api/demo/workloads` | done |
| `/workloads/:id/runs` | `/api/demo/workloads/:id/runs` | done |
| `/platforms` | `/api/demo/platforms` | upgraded (6 platforms, matches real shape) |
| `/platforms/costs` | `/api/demo/platforms/costs` | done |
| `/connections/status` | `/api/demo/connections/status` | done |
| `/alerts` | `/api/demo/alerts` | done (empty list) |
| `/anomalies` | `/api/demo/anomalies` | **NEW** added |
| `/chat` | `/api/demo/chat` | done |
| `/chat/sample` | `/api/demo/chat/sample` | **NEW** seeded demo conversation |
| `/history/queries` | — | backlog (stretch) |
| `/overview/summary` | — | backlog — only called from onboarding |
| `/debug/permissions` | — | backlog — settings page for connected users |
| `/connections` | — | backlog — settings page for connected users |
| `/admin/*`, `/teams/*`, `/settings/*` | — | out of scope for demo |

## Checklist

### Done (this pass)
- [x] Audit `/api/*` endpoints consumed by dashboard pages
- [x] Add `generate_demo_anomalies(days)` tied to the prompt-caching regression + ETL overnight narratives
- [x] Wire `/api/demo/anomalies` router
- [x] Enrich `generate_demo_ai_costs()` with per-day `tool_use` breakdown (Bash / Edit / Read / Write / Grep / WebFetch cost + tokens)
- [x] Upgrade `generate_demo_recommendations()` — high/medium/low mix, ddl, GitHub PR dry-run body
- [x] Upgrade `generate_demo_platform_connections()` to 6 platforms matching the `/api/platforms` real shape (id, platform, name, created_at, last_synced, pricing_overrides)
- [x] Seed sample chat conversation via `generate_demo_chat_sample()` + `/api/demo/chat/sample`
- [x] New tests: `backend/tests/test_demo_ai_costs.py`, `test_demo_anomalies.py`, `test_demo_recommendations.py`, `test_demo_platforms.py`, `test_demo_chat.py` — snapshot + shape-match per generator
- [x] Baseline 613 tests still passing; added tests also green

### In progress
- (none)

### Backlog
- [ ] `/api/demo/history/queries` — the history page currently 404s in demo mode
- [ ] `/api/demo/debug/permissions` + `/api/demo/connections` — settings page still shows real empty-state for demo users
- [ ] Frontend: render tool-cost chart from new `ai_costs.tool_use` field in `/ai-costs` page
- [ ] Frontend: surface `/chat/sample` on first visit to the chat page when no history
- [ ] `/api/demo/overview/summary` for the onboarding route (demo mode probably never hits onboarding, so low priority)
- [ ] `/api/demo/alerts/rules` + sample notification history so the alerts page has content
