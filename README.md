# Costly — Open-Source Data Platform Cost Intelligence

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An open-source, AI-powered cost intelligence platform for data teams. Connect 15+ platforms — warehouses, pipelines, BI tools, AI APIs, CI/CD — and see every dollar your data stack costs in one dashboard.

## What it does

- **Unified cost dashboard** — single pane of glass across all connected platforms
- **AI cost agent** — ask questions about your spend in natural language (15+ tools, platform-specific expert knowledge)
- **Anomaly detection** — automatic spike detection with Z-score, day-over-day, and week-over-week analysis
- **Optimization recommendations** — actionable insights with projected dollar savings
- **Custom pricing** — plug in your negotiated rates (Snowflake credits, AWS EDP, per-model AI pricing)
- **AI Spend Intelligence** — cross-provider AI cost dashboard (OpenAI vs Anthropic vs Gemini) with token breakdowns, model-level costs, and migration recommendations
- **Per-platform deep dives** — warehouse sizing, query patterns, storage analysis, cost attribution

## Supported Platforms

| Category | Platforms |
|----------|-----------|
| **Warehouses** | Snowflake, BigQuery, Databricks |
| **Cloud** | AWS (21 services) |
| **Pipelines** | dbt Cloud, Fivetran, Airbyte |
| **BI & Analytics** | Looker, Tableau, Omni |
| **AI & ML** | OpenAI, Anthropic, Gemini/Vertex AI |
| **CI/CD** | GitHub Actions, GitLab CI |
| **Data Quality** | Monte Carlo |

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Next.js 15  │────▶│  FastAPI      │────▶│  MongoDB 7   │
│  Frontend    │     │  Backend      │     │              │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │
                    ┌──────┴───────┐     ┌──────────────┐
                    │  AI Agent    │     │  Redis 7     │
                    │  (15+ tools) │     │  (cache)     │
                    └──────┬───────┘     └──────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    Snowflake            AWS           dbt Cloud
    BigQuery          Anthropic         OpenAI
    Databricks        Fivetran          GitHub
         ...              ...              ...
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
cd costly-oss  # rename if you prefer
# or: git clone https://github.com/njain006/costly-oss.git costly
cd costly

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

Visit **http://localhost:3000** and create an account. Then connect your first platform.

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

1. Create `backend/app/services/<platform>_connector.py`
2. Implement the `BaseConnector` interface with `fetch_costs()` method
3. Register in `CONNECTOR_MAP` in `services/unified_costs.py`
4. Add platform to `PLATFORM_KEYWORDS` in `services/expert_agents.py`
5. Optionally add a knowledge base in `backend/app/knowledge/<platform>.md`

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)
