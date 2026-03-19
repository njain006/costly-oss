# Costly — Snowflake Cost Intelligence Platform

## What This Is

Costly is a Snowflake cost analytics and optimization platform. It connects to a customer's Snowflake account via read-only key-pair auth, queries ACCOUNT_USAGE views, and surfaces cost anomalies, optimization recommendations, and performance insights. It can also execute optimization actions (warehouse resizing, auto-suspend tuning, clustering keys) directly.

**Self-hosted** — deploy anywhere with Docker Compose
**Repo:** https://github.com/njain006/costly-oss.git

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15 (App Router) + TypeScript + Tailwind CSS + shadcn/ui |
| Backend | FastAPI (Python) — modular routers/services/models |
| Database | MongoDB 7 (Motor async driver) |
| Cache | Redis 7 (with in-memory fallback) |
| Auth | JWT (15min access + 7d refresh tokens) + Google OAuth |
| Charts | Recharts |
| Deployment | Docker Compose (5 containers) behind nginx with Let's Encrypt SSL |

## Project Structure

```
costly/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, startup/shutdown, scheduler
│   │   ├── config.py            # Pydantic Settings from .env
│   │   ├── database.py          # MongoDB client + index creation
│   │   ├── deps.py              # get_current_user(), get_data_source()
│   │   ├── models/              # Pydantic request/response models
│   │   │   ├── auth.py          # UserRegister, UserLogin, GoogleAuth, etc.
│   │   │   ├── connection.py    # SnowflakeConnectionCreate
│   │   │   └── alert.py         # AlertCreate, AlertUpdate
│   │   ├── routers/             # API route handlers
│   │   │   ├── auth.py          # /api/auth/* (register, login, google, refresh, reset-password)
│   │   │   ├── connections.py   # /api/connections/* (CRUD + test + activate)
│   │   │   ├── dashboard.py     # /api/dashboard
│   │   │   ├── costs.py         # /api/costs
│   │   │   ├── queries.py       # /api/queries
│   │   │   ├── storage.py       # /api/storage
│   │   │   ├── warehouses.py    # /api/warehouses
│   │   │   ├── workloads.py     # /api/workloads, /api/workloads/{id}/runs
│   │   │   ├── recommendations.py # /api/recommendations
│   │   │   ├── alerts.py        # /api/alerts/* (CRUD + evaluation)
│   │   │   ├── history.py       # /api/history/*, /api/sync/*, /api/history/export
│   │   │   └── debug.py         # /api/debug/permissions
│   │   ├── services/
│   │   │   ├── snowflake.py     # Connection builder, all Snowflake SQL queries
│   │   │   ├── cache.py         # Redis-backed TTL cache (fallback to in-memory)
│   │   │   ├── encryption.py    # Fernet encrypt/decrypt for SF credentials
│   │   │   ├── email.py         # SMTP email sender (password reset, alerts)
│   │   │   ├── alerts_engine.py # Alert evaluation + Slack/email notifications
│   │   │   ├── query_sync.py    # Query history Snowflake → MongoDB sync
│   │   │   └── demo.py          # Demo data generators (no SF connection needed)
│   │   └── utils/
│   │       ├── constants.py     # CREDITS_MAP (warehouse sizes), CACHE_TTL
│   │       └── helpers.py       # days_ago(), run_in_thread()
│   ├── server.py                # Legacy monolith (kept for reference, not used)
│   ├── Dockerfile               # Production multi-stage build
│   ├── Dockerfile.dev           # Dev with hot-reload
│   └── requirements.txt
│
├── frontend-next/               # Next.js 15 frontend (the active one)
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx       # Root layout (Inter font, Google OAuth, Auth provider)
│   │   │   ├── page.tsx         # Landing page (SSR, expert Snowflake positioning)
│   │   │   ├── login/page.tsx   # Sign in/register tabs + Google OAuth
│   │   │   ├── pricing/page.tsx # 3-tier pricing (Free/Pro $49/Enterprise)
│   │   │   ├── setup/page.tsx   # Key-pair auth setup guide
│   │   │   ├── reset-password/page.tsx
│   │   │   └── (dashboard)/     # Auth-guarded route group
│   │   │       ├── layout.tsx   # Sidebar + DateRange provider
│   │   │       ├── dashboard/page.tsx
│   │   │       ├── costs/page.tsx
│   │   │       ├── queries/page.tsx
│   │   │       ├── history/page.tsx
│   │   │       ├── storage/page.tsx
│   │   │       ├── warehouses/page.tsx
│   │   │       ├── workloads/page.tsx
│   │   │       ├── recommendations/page.tsx
│   │   │       ├── alerts/page.tsx
│   │   │       └── settings/page.tsx
│   │   ├── components/
│   │   │   ├── ui/              # shadcn/ui components (button, card, dialog, table, etc.)
│   │   │   ├── sidebar.tsx      # Collapsible nav sidebar
│   │   │   ├── date-range-picker.tsx
│   │   │   ├── stat-card.tsx    # Reusable KPI card
│   │   │   ├── data-freshness.tsx
│   │   │   └── demo-banner.tsx
│   │   ├── lib/
│   │   │   ├── api.ts           # Axios instance with JWT interceptors + refresh
│   │   │   ├── utils.ts         # cn() for Tailwind class merging
│   │   │   ├── format.ts        # formatCurrency, formatBytes, formatDuration
│   │   │   └── constants.ts     # Colors, date presets
│   │   ├── hooks/
│   │   │   └── use-api.ts       # Generic data fetching hook with loading/error
│   │   └── providers/
│   │       ├── auth-provider.tsx # Auth context (login, logout, token management)
│   │       └── date-range-provider.tsx
│   ├── next.config.ts           # Standalone output + API rewrites
│   ├── Dockerfile               # Multi-stage production build
│   └── components.json          # shadcn/ui config
│
├── frontend/                    # Legacy React+Vite frontend (kept for reference)
├── nginx/nginx.conf             # Reverse proxy: /api/ → backend:8000, / → frontend:3000
├── docker-compose.yml           # mongodb + redis + backend + frontend + nginx
└── CLAUDE.md                    # This file
```

## Deployment

### Docker Services (5 containers)
```
nginx       → ports 80/443, reverse proxy
frontend    → port 3000, Next.js standalone
backend     → port 8000, FastAPI with 4 Uvicorn workers
redis       → port 6379, cache
mongodb     → port 27017, persistent volume
```

### Deploy Process
```bash
docker compose build --no-cache frontend backend
docker compose up -d
```

### Important: NEXT_PUBLIC_ env vars
Next.js inlines `NEXT_PUBLIC_*` variables at **build time**. The `.env.local` file must exist in `frontend-next/` BEFORE building the Docker image.

## Key Architecture Decisions

1. **MongoDB over Postgres** — The data model (users, connections, alerts, query_history with nested objects) fits document storage well. No compelling reason to migrate.

2. **Redis cache with in-memory fallback** — `services/cache.py` tries Redis first, falls back to a TTL dict if Redis is unavailable. Shared across Uvicorn workers.

3. **All Snowflake queries in `services/snowflake.py`** — Single source of truth for every SQL query against ACCOUNT_USAGE views. Queries are run in threads via `run_in_executor` to avoid blocking the async event loop.

4. **Demo mode** — When no Snowflake connection exists, `services/demo.py` generates realistic fake data so the app works out of the box. The `deps.py:get_data_source()` dependency switches between real and demo data.

5. **JWT refresh tokens** — Access tokens expire in 15 minutes. Refresh tokens last 7 days. The frontend Axios interceptor in `lib/api.ts` automatically refreshes on 401.

6. **Next.js App Router with route groups** — `(dashboard)/` is a route group that shares a sidebar layout and requires authentication. Public pages (landing, login, pricing, setup) are outside it.

7. **shadcn/ui** — Components are copied into `components/ui/`, not imported from a package. Full control, Tailwind-native, accessible.

## Platform Connectors (15)

All connectors implement `BaseConnector` and normalize to `UnifiedCost` records.
Registered in `CONNECTOR_MAP` in `services/unified_costs.py`.

| Connector | File | API | Category |
|-----------|------|-----|----------|
| AWS (21 services) | `aws_connector.py` | Cost Explorer | compute, storage, orchestration, ingestion, AI, ML |
| Anthropic | `anthropic_connector.py` | Admin Usage API | ai_inference |
| dbt Cloud | `dbt_cloud_connector.py` | Admin API | transformation |
| OpenAI | `openai_connector.py` | Usage + Costs API | ai_inference |
| Gemini/Vertex AI | `gemini_connector.py` | AI Studio + Cloud Monitoring | ai_inference |
| Fivetran | `fivetran_connector.py` | REST API v2 | ingestion |
| Airbyte | `airbyte_connector.py` | Cloud/Self-hosted API | ingestion |
| Monte Carlo | `monte_carlo_connector.py` | GraphQL API | data_quality |
| BigQuery | `bigquery_connector.py` | INFORMATION_SCHEMA.JOBS | compute, storage |
| Databricks | `databricks_connector.py` | Billable Usage API | compute, transformation, ml_serving |
| Looker | `looker_connector.py` | Admin API | serving, transformation |
| Tableau | `tableau_connector.py` | REST API | licensing, serving |
| GitHub Actions | `github_connector.py` | Actions/Billing API | ci_cd |
| GitLab CI | `gitlab_connector.py` | Pipelines API | ci_cd |
| Omni | `omni_connector.py` | REST API | serving |

## Snowflake ACCOUNT_USAGE Views Used

The backend queries these views for analytics:

- `WAREHOUSE_METERING_HISTORY` — credit consumption per warehouse
- `WAREHOUSE_LOAD_HISTORY` — utilization (avg_running / avg_available)
- `WAREHOUSE_EVENTS_HISTORY` — suspend/resume patterns for auto-suspend analysis
- `QUERY_HISTORY` — execution times, spillage, compilation, queue time
- `QUERY_ATTRIBUTION_HISTORY` — per-query cost attribution
- `TABLE_STORAGE_METRICS` — per-table storage (active, time-travel, failsafe)
- `DATABASE_STORAGE_USAGE_HISTORY` — storage trends over time
- `ACCESS_HISTORY` — last-queried timestamps for stale table detection
- `AUTOMATIC_CLUSTERING_HISTORY` — clustering credit usage
- `LOGIN_HISTORY` — user activity tracking

## Backend .env Variables

See `backend/.env.example` for all configuration options. Key variables:

```
JWT_SECRET=<openssl rand -hex 32>
ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
LLM_API_KEY=<anthropic-or-openai-api-key>
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
GOOGLE_CLIENT_ID=<google-oauth-client-id>
```

## Common Tasks

### Add a new shadcn/ui component
```bash
cd frontend-next
npx shadcn@latest add <component-name>
```

### Add a new API endpoint
1. Create or edit a router in `backend/app/routers/`
2. Add Pydantic models in `backend/app/models/` if needed
3. Add Snowflake queries in `backend/app/services/snowflake.py`
4. Include the router in `backend/app/main.py` if it's new

### Add a new dashboard page
1. Create `frontend-next/src/app/(dashboard)/<name>/page.tsx`
2. Add the nav link in `frontend-next/src/components/sidebar.tsx`
3. The page automatically gets the sidebar layout and auth guard

## Things to Know

- The old `frontend/` (React+Vite) and `backend/server.py` (monolith) are kept for reference but are NOT used in production. The active code is `frontend-next/` and `backend/app/`.
- Recharts Tooltip `formatter` props need `(v) => formatCurrency(Number(v))` pattern (not typed param) to avoid TypeScript errors.
- `useSearchParams()` in Next.js requires wrapping the component in `<Suspense>`.
- The EC2 instance has limited RAM (~1.9GB + 2GB swap). Docker builds can be slow. Use `--no-cache` only when needed.
