# Deployment

How to self-host Costly with Docker Compose. The canonical reference deployment runs five containers on a single host and proxies everything through nginx.

> Audience: operators self-hosting the MIT OSS build. The hosted version at https://costly.cdatainsights.com uses the same compose file plus Let's Encrypt certs and a managed MongoDB.

---

## 1. Prerequisites

- Docker 24+ and Docker Compose v2 (`docker compose`, not `docker-compose`)
- ~2 GB RAM minimum on the host. The included `t3.small` / 2 GB swap EC2 target works but builds are slow — prefer 4 GB+ for development.
- One outbound-reachable LLM API key (Anthropic or OpenAI) for the AI agent.
- At least one platform credential you want to connect (Snowflake, AWS, dbt Cloud, Anthropic, OpenAI, Gemini, Claude Code, Databricks, BigQuery, Fivetran, Airbyte, Monte Carlo, Looker, Tableau, Omni, GitHub Actions, GitLab CI).

---

## 2. Clone and generate secrets

```bash
git clone https://github.com/njain006/costly-oss.git
cd costly-oss
cp backend/.env.example backend/.env
```

Generate the two required secrets and paste them into `backend/.env`:

```bash
# JWT signing secret (hex, 64 chars)
openssl rand -hex 32

# Fernet encryption key (urlsafe base64, 44 chars)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Do not reuse the `ENCRYPTION_KEY` across environments.** Stored platform credentials are encrypted at rest with Fernet; rotating the key invalidates every saved connection.

---

## 3. Required environment variables

Fill these in `backend/.env` before starting Compose:

| Variable | Required | Notes |
|----------|----------|-------|
| `JWT_SECRET` | yes | From `openssl rand -hex 32`. |
| `ENCRYPTION_KEY` | yes | From `Fernet.generate_key()`. Do not change after connections are saved. |
| `LLM_API_KEY` | yes | Anthropic or OpenAI key used by the AI agent. |
| `LLM_PROVIDER` | no | `anthropic` (default) or `openai`. |
| `LLM_MODEL` | no | Defaults to `claude-sonnet-4-20250514`. |
| `MONGO_URL` | no | Defaults to `mongodb://mongodb:27017` in Compose. |
| `REDIS_URL` | no | Defaults to `redis://redis:6379` in Compose. |
| `CORS_ORIGINS` | no | JSON array of allowed origins. Defaults to `["http://localhost:3000"]`. |
| `GOOGLE_CLIENT_ID` | no | Enables Google Sign-In on the login page. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | no | Enables password-reset emails and alert notifications. |
| `APP_URL` | no | Public URL baked into password-reset emails. Defaults to `http://localhost:3000`. |

The frontend separately needs `NEXT_PUBLIC_API_URL` — this is passed as a build-arg via `docker-compose.yml` (see step 5). Next.js inlines it at **build time**, not runtime, so changing it requires a `docker compose build frontend`.

---

## 4. Bring up the stack

```bash
docker compose up -d
```

This starts five containers:

| Service | Port (host) | Purpose |
|---------|-------------|---------|
| `nginx` | 80, 443 | Reverse proxy; terminates TLS (Let's Encrypt mount) and routes `/api/` → backend, `/` → frontend. |
| `frontend` | 3000 | Next.js 15 standalone build. |
| `backend` | 8000 | FastAPI with 4 Uvicorn workers. |
| `mongodb` | 27017 | Database. Persistent volume `mongo_data`. |
| `redis` | 6379 | Cache. Persistent volume `redis_data`. In-memory fallback if unreachable. |

All ports except 80/443 are bound to `127.0.0.1` by default — nginx is the only public entry point.

Open http://localhost:3000 (or your configured domain) and create an account.

---

## 5. The `docker-compose.override.yml` pattern

Docker Compose automatically merges `docker-compose.override.yml` into `docker-compose.yml` if it exists. The repo `.gitignore`s this file so each host can add per-deployment tweaks without polluting the canonical compose.

Common overrides:

### Mount your local Claude Code transcripts (for the Claude Code connector)

The Claude Code connector reads `~/.claude/projects/**/*.jsonl` on disk. In a container, it needs those files mounted in. Create `docker-compose.override.yml`:

```yaml
services:
  backend:
    volumes:
      - ${HOME}/.claude:/root/.claude:ro
```

Then re-up: `docker compose up -d backend`. The connector defaults to `Path.home() / ".claude" / "projects"`; if your home layout differs, override via the connection's `projects_dir` credential field.

### Expose MongoDB or Redis to the host

```yaml
services:
  mongodb:
    ports:
      - "0.0.0.0:27017:27017"
```

### Pin an image digest for reproducibility

```yaml
services:
  mongodb:
    image: mongo:7@sha256:<digest>
```

Never commit `docker-compose.override.yml` — that's why it's gitignored. Commit a `docker-compose.override.example.yml` alongside it if your deployment has a standard shape.

---

## 6. First sync expectations

After you add a platform connection under **Platforms → Add**, the first sync can take a while depending on the source:

| Connector | First-sync cost | First-sync latency |
|-----------|-----------------|--------------------|
| Snowflake | ~0 (read-only `ORGANIZATION_USAGE` / `ACCOUNT_USAGE`) | 10–60 s |
| AWS (Cost Explorer) | **$0.01 per API call** — watch out | 30 s – 3 min |
| AWS (CUR 2.0 via Athena) | Athena scan cost (usually < $0.05) | 1–5 min |
| BigQuery | BigQuery slot/scan cost on `INFORMATION_SCHEMA.JOBS` + billing export | 30 s – 2 min |
| Databricks | ~0 (`system.billing.usage` + `system.billing.list_prices`) | 30 s – 2 min |
| Anthropic | ~0 (Admin API) | 10–30 s |
| OpenAI | ~0 (Usage + Costs API) | 30 s – 2 min (8 buckets) |
| Gemini / Vertex | BigQuery scan cost on billing export | 30 s – 3 min |
| Claude Code | ~0 (local file read) | 1–10 s per 100 MB of JSONL |
| dbt Cloud / Fivetran / Airbyte / Monte Carlo / Looker / Tableau / Omni / GitHub / GitLab | ~0 (REST APIs) | 10–60 s |

Usage reports for **today** are typically incomplete on every platform (15 min – 36 h lag depending on source). Expect "today" numbers to update overnight. See per-connector gotchas under `docs/connectors/*.md`.

Background sync runs on the backend scheduler; manual syncs are triggered from the Platforms page.

---

## 7. Upgrading

```bash
git pull
docker compose build frontend backend
docker compose up -d
```

Next.js inlines `NEXT_PUBLIC_*` at build time, so always rebuild the frontend image when you change `NEXT_PUBLIC_API_URL` or any public env var.

---

## 8. Troubleshooting

**`ENCRYPTION_KEY` lost or rotated** — stored platform credentials can no longer be decrypted. Drop the `connections` MongoDB collection and reconnect each platform.

**Frontend hits the wrong backend URL** — `NEXT_PUBLIC_API_URL` was not re-baked. Rebuild: `docker compose build --no-cache frontend && docker compose up -d frontend`.

**Claude Code connector returns zero rows in Docker** — your `~/.claude` is not mounted. See step 5.

**Redis unreachable warnings** — the cache falls back to an in-memory TTL dict. Functionally fine for a single backend replica; add Redis back for multi-replica deployments.

**Out-of-memory during `docker compose build`** — the Next.js production build on a 1.9 GB host needs swap. If builds still OOM, build the frontend image on a larger machine and `docker push` / `docker save` + `docker load` onto the deployment host.

---

## 9. Production hardening checklist

- [ ] Put Costly behind HTTPS (nginx + Let's Encrypt is wired up; point certs at `/etc/letsencrypt/live/<your-domain>/`).
- [ ] Set `CORS_ORIGINS` to exactly your public domain — don't leave `localhost` in production.
- [ ] Set `APP_URL` to your public domain so password-reset emails link correctly.
- [ ] Restrict MongoDB and Redis to `127.0.0.1` (default) — nothing but the backend should reach them.
- [ ] Back up the `mongo_data` volume on a schedule — it holds users, connections, alerts, and history.
- [ ] Rotate `JWT_SECRET` on a regular cadence (this forces all existing sessions to re-login — do not do it on a whim).
- [ ] Never rotate `ENCRYPTION_KEY` without a key-rotation migration script — it will brick every saved connection.
- [ ] Configure SMTP so password-reset and alert notifications actually deliver.
- [ ] Mount logs to a persistent volume or ship them to your log aggregator — the compose file currently relies on `docker logs`.

See `docs/architecture.md` for the request lifecycle, module responsibilities, and cache / auth architecture that underpin these ops decisions.
