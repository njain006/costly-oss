# Costly — Open-source AI &amp; Data Cost Intelligence

[![CI](https://github.com/njain006/costly-oss/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/njain006/costly-oss/actions/workflows/ci.yml)
[![Security](https://github.com/njain006/costly-oss/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/njain006/costly-oss/actions/workflows/security.yml)
[![codecov](https://codecov.io/gh/njain006/costly-oss/branch/main/graph/badge.svg)](https://codecov.io/gh/njain006/costly-oss)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/njain006/costly-oss?display_name=tag&sort=semver)](https://github.com/njain006/costly-oss/releases)
[![GitHub stars](https://img.shields.io/github/stars/njain006/costly-oss?style=social)](https://github.com/njain006/costly-oss/stargazers)
[![Live Demo](https://img.shields.io/badge/demo-live-indigo)](https://costly.cdatainsights.com/demo)

**One AI agent for your Claude, GPT, Gemini, dbt, warehouse, BI, CI, and cloud bills.** Connect 17 platforms in minutes, ask questions in plain English, catch spikes before they become surprise bills. AI-first — not Snowflake-only. MIT licensed. Self-host in 10 minutes — or use the hosted cloud.

```bash
git clone https://github.com/njain006/costly-oss && cd costly-oss
cp backend/.env.example backend/.env   # add your LLM API key
docker compose up -d                    # open http://localhost:3000
```

## What it does

- **AI-first cost agent** — ask "why did our Claude spend spike last week?" or "which dbt models cost the most?" and get cited answers across every connected platform.
- **AI API cost attribution** — per-model, per-workspace, per-service-tier breakdowns across Anthropic, OpenAI, Gemini / Vertex AI; full cache-tier split (cached-read vs cache-write-5m vs cache-write-1h vs input vs output); batch / priority / flex / reasoning tier awareness.
- **Claude Code connector (new)** — attributes your local Claude Code Max / Pro subscription traffic by reading `~/.claude/projects/**/*.jsonl` transcripts. The only way to get per-project, per-model cost visibility for Claude Code users, because Admin API does not surface subscription traffic.
- **Unified cost dashboard** — single pane of glass for AI APIs, pipelines, warehouses, BI, CI / CD, and cloud.
- **Anomaly detection** — Z-score + day-over-day + week-over-week spike detection with Slack / email alerts.
- **Optimization recommendations** — actionable insights with projected dollar savings.
- **Open connector layer** — MIT-licensed, read-only. Audit exactly what we query; every connector is documented in `docs/connectors/`.

## Supported Platforms

| Category | Platforms |
|----------|-----------|
| **AI &amp; LLM APIs** | Anthropic (Claude), OpenAI, Gemini / Vertex AI, **Claude Code (local JSONL)** |
| **Pipelines** | dbt Cloud, Fivetran, Airbyte |
| **BI &amp; Analytics** | Looker, Tableau, Omni |
| **Warehouses** | BigQuery, Databricks, Snowflake |
| **Cloud** | AWS (21 services) |
| **CI/CD** | GitHub Actions, GitLab CI |
| **Data Quality** | Monte Carlo |

Full per-platform pricing model, auth requirements, SKU taxonomy, and gotchas live under [`docs/connectors/`](docs/connectors/). The authoritative cross-platform spec is [`docs/connector-ground-truth.md`](docs/connector-ground-truth.md).

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Next.js 15 │────▶│  FastAPI     │────▶│  MongoDB 7   │
│  Frontend   │     │  Backend     │     │              │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │
                    ┌──────┴───────┐     ┌──────────────┐
                    │  AI Agent    │     │  Redis 7     │
                    │  (15+ tools) │     │  (cache)     │
                    └──────┬───────┘     └──────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    Anthropic           dbt Cloud          AWS
    OpenAI              Fivetran           BigQuery
    Gemini              Airbyte            Snowflake
         ...              ...                ...
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts |
| Backend | FastAPI, Python, Pydantic |
| Database | MongoDB 7 (Motor async driver) |
| Cache | Redis 7 (with in-memory fallback) |
| Auth | JWT (access + refresh tokens) + Google OAuth |
| AI | Claude (Anthropic) with tool use — supports OpenAI as alternative |
| Deployment | Docker Compose (5 containers) + Nginx reverse proxy |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- An LLM API key (Anthropic or OpenAI) for the AI agent
- At least one platform to connect (Snowflake, AWS, dbt Cloud, etc.)

### 1. Clone and configure

```bash
git clone https://github.com/njain006/costly-oss.git
cd costly-oss

# Copy example env and fill in your values
cp backend/.env.example backend/.env
```

Edit `backend/.env` with your settings:

```env
# Required: Generate a random secret
JWT_SECRET=<run: openssl rand -hex 32>

# Required: Generate an encryption key for stored credentials
ENCRYPTION_KEY=<run: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Required for AI agent (pick one)
LLM_API_KEY=<your-anthropic-or-openai-api-key>
LLM_PROVIDER=anthropic  # or "openai"
LLM_MODEL=claude-sonnet-4-20250514  # or "gpt-4o"

# Optional: Google OAuth (for Google Sign-In)
GOOGLE_CLIENT_ID=<your-google-oauth-client-id>

# Optional: Email (for password reset)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<your-email>
SMTP_PASSWORD=<your-app-password>
```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

This starts 5 containers:

| Service | Port | Description |
|---------|------|-------------|
| frontend | 3000 | Next.js app |
| backend | 8000 | FastAPI API |
| mongodb | 27017 | Database |
| redis | 6379 | Cache |
| nginx | 80/443 | Reverse proxy |

### 3. Open the app

Visit **http://localhost:3000** and create an account. Then follow the multi-platform [/setup](http://localhost:3000/setup) guide to connect your first platform, or jump straight into the in-app **Platforms → Add** flow.

> For deeper ops guidance — the `docker-compose.override.yml` pattern for mounting your local `~/.claude` directory into the Claude Code connector, first-sync expectations per platform, SMTP + TLS, and a production hardening checklist — read [`docs/deployment.md`](docs/deployment.md).

### Local development (without Docker)

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend-next
npm install
npm run dev
```

## Project Structure

```
costly/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI app, scheduler, startup
│       ├── config.py            # Pydantic settings from .env
│       ├── database.py          # MongoDB client + indexes
│       ├── deps.py              # Auth dependencies
│       ├── models/              # Pydantic request/response models
│       ├── routers/             # API route handlers
│       ├── services/            # Business logic
│       │   ├── snowflake.py     # Snowflake SQL queries
│       │   ├── agent.py         # AI agent with tool use
│       │   ├── expert_agents.py # Platform-specific AI experts
│       │   ├── unified_costs.py # Multi-platform cost normalization
│       │   ├── anomaly_detector.py # Cost spike detection
│       │   ├── pricing.py       # Custom pricing engine
│       │   ├── aws_connector.py # AWS Cost Explorer connector
│       │   └── ...              # 15+ platform connectors
│       ├── knowledge/           # Expert agent knowledge bases (markdown)
│       └── utils/
├── frontend-next/
│   └── src/
│       ├── app/                 # Next.js App Router pages
│       │   ├── (dashboard)/     # Auth-guarded route group
│       │   ├── login/           # Auth pages
│       │   └── page.tsx         # Landing page
│       ├── components/          # React components + shadcn/ui
│       ├── hooks/               # Custom React hooks
│       ├── lib/                 # API client, utils, formatters
│       └── providers/           # Auth + date range context
├── nginx/                       # Reverse proxy config
├── docker-compose.yml
└── CLAUDE.md                    # AI assistant context
```

## Adding a New Connector

1. Create `backend/app/services/connectors/<platform>_connector.py`
2. Implement the `BaseConnector` interface with `test()` + `fetch_costs()` methods
3. Register in `CONNECTOR_MAP` in `services/unified_costs.py`
4. Add platform to `PLATFORM_KEYWORDS` in `services/expert_agents.py`
5. Add an expert knowledge base in `backend/app/knowledge/<platform>.md`
6. Document pricing model, auth, SKU taxonomy, and gotchas in `docs/connectors/<platform>.md`

See [`docs/architecture.md`](docs/architecture.md) for module responsibilities, request lifecycle, and the full extension checklist.

## Environment Variables

See [`backend/.env.example`](backend/.env.example) for all configuration options.

| Variable | Required | Description |
|----------|----------|-------------|
| `JWT_SECRET` | Yes | Secret key for JWT token signing |
| `ENCRYPTION_KEY` | Yes | Fernet key for encrypting stored credentials |
| `LLM_API_KEY` | Yes | Anthropic or OpenAI API key for AI agent |
| `LLM_PROVIDER` | No | `anthropic` (default) or `openai` |
| `GOOGLE_CLIENT_ID` | No | For Google OAuth sign-in |
| `SMTP_*` | No | For password reset emails |
| `CORS_ORIGINS` | No | JSON array of allowed origins |

## Documentation

| Doc | Purpose |
|-----|---------|
| [`docs/architecture.md`](docs/architecture.md) | System diagram, module responsibilities, request lifecycle, caching + auth model. |
| [`docs/deployment.md`](docs/deployment.md) | Self-host recipe: Docker Compose, `docker-compose.override.yml` pattern, env vars, first-sync expectations, hardening. |
| [`docs/connector-ground-truth.md`](docs/connector-ground-truth.md) | Authoritative spec: canonical data source, auth, SKU taxonomy, and gotchas for every connector. |
| [`docs/connector-roadmap-2026.md`](docs/connector-roadmap-2026.md) | What's shipping next per connector. |
| [`docs/connectors/`](docs/connectors/) | One per-platform knowledge base (17 files). |
| [`docs/agent-chat-ux.md`](docs/agent-chat-ux.md) | AI agent conversational UX spec. |
| [`docs/dashboard-visualization-spec.md`](docs/dashboard-visualization-spec.md), [`docs/chart-patterns.md`](docs/chart-patterns.md) | Dashboard + chart specs. |
| [`CHANGELOG.md`](CHANGELOG.md) | What shipped and when. |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)
