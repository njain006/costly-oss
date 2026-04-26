# Changelog

All notable changes to Costly are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/) once a first tagged release is cut. Until then, dates are the canonical ordering.

## [Unreleased]

### Added

- **Claude Code connector** — attributes local Claude Code Max/Pro session cost by reading `~/.claude/projects/**/*.jsonl` transcripts. Imputes list-price dollars from token counts (including cache tiers) so subscription users get per-project, per-model, per-day cost attribution that the Anthropic Admin API cannot surface. (`claude_code_connector.py`, docs/connectors/claude-code.md)
- **Overview page Cache Hit Rate KPI** — 6-tile KPI grid now includes cache hit rate alongside spend, requests, tokens, and model mix. (`frontend-next/src/app/(dashboard)/overview/page.tsx`)
- **AI Costs view** — surfaces Claude Code traffic and cache-tier splits (cached-read vs cache-write-5m vs cache-write-1h vs input vs output) with dedicated KPIs. (`backend/app/routers/ai_costs.py`, `frontend-next/src/app/(dashboard)/ai-costs/page.tsx`)
- **Demo AI costs endpoint** — `/api/demo/ai-costs` returns realistic multi-provider AI spend so logged-out visitors on `/demo` land on a representative unified view. (`backend/app/routers/public_demo.py`, `backend/app/services/demo.py`)
- **Multi-platform `/setup` guide** — public setup page rewritten from Snowflake-only key-pair docs into an AI-first multi-platform guide with deep-links into the in-app "Add Platform" flow; Snowflake key-pair walkthrough kept as a collapsible section. (`frontend-next/src/app/setup/page.tsx`)
- **Claude Code in platforms UI** — the in-app Platforms → Add flow now offers Claude Code as a selectable connector. (`frontend-next/src/app/(dashboard)/platforms/page.tsx`)
- **Databricks SQL connector dependency** — adds `databricks-sql-connector` to enable querying `system.billing.usage` and `system.billing.list_prices`. (`backend/requirements.txt`)
- **17-connector knowledge base** — per-platform KBs under `docs/connectors/` covering pricing model, data sources, SKU taxonomy, auth model, gotchas, and recommendations. Companion specs: `connector-ground-truth.md`, `connector-roadmap-2026.md`, `dashboard-visualization-spec.md`, `chart-patterns.md`, `agent-chat-ux.md`.

### Changed

- **Landing + navigation reposition** — nav label "Docs" renamed to "Setup"; marketing copy moves away from Snowflake-only language toward "one agent for your AI, data, BI, CI, and cloud bills." (`frontend-next/src/app/page.tsx`, `frontend-next/src/app/setup/page.tsx`)
- **Demo landing route** — `/demo` now lands on `/overview` (unified AI + data view) instead of the Snowflake-centric `/dashboard`. (`frontend-next/src/app/demo/page.tsx`)
- **Anthropic connector overhaul** — migrated to the Admin API `usage_report/messages` + `cost_report` endpoints; adds cache tiers (ephemeral 5m / 1h / read), `service_tier` (standard / priority / batch), and `context_window` (`0-200k` / `200k-1M`). 56 tests. (`backend/app/services/connectors/anthropic_connector.py`)
- **OpenAI connector overhaul** — now queries all eight Usage API buckets (completions, embeddings, moderations, images, audio_speeches, audio_transcriptions, vector_stores, code_interpreter_sessions) plus the Costs API. Fixes the legacy `/100` cents-vs-dollars bug on the 2025-11 Costs API rollout. Adds cache, batch, and reasoning tier attribution. 104 tests. (`backend/app/services/connectors/openai_connector.py`)
- **Gemini / Vertex AI connector overhaul** — rebuilt on the BigQuery billing export (`gcp_billing_export_resource_v1_*`) as the invoice-authoritative source; preserves Cloud Monitoring + AI Studio as fallbacks. Adds SKU catalog, context-cache tier, thinking-mode tier, and per-region attribution. 117 tests. (`backend/app/services/connectors/gemini_connector.py`)
- **Snowflake connector overhaul** — migrated to `ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` (already-billed USD) with fallback to `ACCOUNT_USAGE.METERING_DAILY_HISTORY`; adds serverless credit lines (nine SKUs), `QUERY_ATTRIBUTION_HISTORY` for per-query / per-user / per-role / per-query-tag attribution, customer pricing overrides for capacity / EDP contracts, and structured error types. 55 tests. (`backend/app/services/connectors/snowflake_connector.py`)
- **Databricks connector overhaul** — migrated from the legacy Billable Usage API to `system.billing.usage` + `system.billing.list_prices` system tables; adds per-job and per-workflow attribution. 92 tests. (`backend/app/services/connectors/databricks_connector.py`)
- **BigQuery connector overhaul** — fixes multi-region handling, adds BigQuery Editions support (Standard / Enterprise / Enterprise Plus / On-Demand), corrects storage calculation, and parameterises SQL to prevent injection. 56 tests. (`backend/app/services/connectors/bigquery_connector.py`)
- **Frontend Docker build** — `NEXT_PUBLIC_API_URL` is now baked at build time via a build-arg passed through `docker-compose.yml`, so relative/absolute API base URLs are deterministic across environments. (`frontend-next/Dockerfile`, `docker-compose.yml`)
- **Canonical frontend port** — reverted to `3000:3000` after a brief detour; production docs and compose file now agree. (`docker-compose.yml`)

### Fixed

- **Demo no longer opens on Snowflake-only dashboard** — `/demo` landing URL aligned with the AI-first repositioning; legacy `/dashboard` retained for direct links. (`frontend-next/src/app/demo/page.tsx`)
- **Anthropic connector 403s on admin-scoped keys** — old `/v1/organizations/usage` path upgraded to the documented Admin API report endpoints. (`backend/app/services/connectors/anthropic_connector.py`)

### Infrastructure

- `docker-compose.override.yml` is now gitignored — intended to be used per-host for volume mounts (e.g. mounting a developer's `~/.claude` into the backend container so the Claude Code connector can read local transcripts). (`.gitignore`)
- Coverage artifacts (`backend/.coverage`, `htmlcov/`) are now gitignored.

[Unreleased]: https://github.com/njain006/costly-oss/compare/HEAD...HEAD
