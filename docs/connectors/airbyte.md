# Airbyte — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Airbyte is an open-source ELT platform with three deployment flavors that matter for cost intelligence: (1) **Airbyte OSS** (self-hosted Community edition — free software, customer pays only infra), (2) **Airbyte Self-Managed Enterprise** (on-prem + license — annual), and (3) **Airbyte Cloud** (SaaS, usage-based). Each has a completely different API surface, authentication model, URL shape, and cost structure. This is the single biggest source of confusion for cost tooling.

In 2024 Airbyte shifted Cloud from "capacity plans" to a **Credit-based consumption model**, introducing Airbyte Credits and transparent per-row pricing that bands connector types. Database/API: **$10 per 1M rows synced**; File: **$3-$10 per GB**; custom connectors differ. As of 2026-04 there are capped-plan options again for predictability.

Costly's current `airbyte_connector.py` tries to call `{base_url}/workspaces` and `{base_url}/connections` with a Bearer token. This works for Airbyte Cloud (`https://api.airbyte.com/v1`) but **does not work** for OSS. OSS uses the Config API at `http://<host>:8001/api/v1/...` with POST requests and JSON bodies like `{"workspaceId": "..."}` — no GET, no Bearer, only optional Basic auth. Connector as-written is Cloud-compatible only despite claiming OSS support.

Authoritative sources:
- https://reference.airbyte.com (Airbyte Cloud API)
- https://docs.airbyte.com/api-documentation (overview)
- https://airbyte.com/pricing
- https://docs.airbyte.com/using-airbyte/core-concepts/
- https://docs.airbyte.com/enterprise-setup/
- https://github.com/airbytehq/airbyte (OSS repo)
- https://docs.airbyte.com/using-airbyte/configuring-api-access (local vs cloud auth)

## Pricing Model (from vendor)

**Airbyte Open Source / Community**
- Free software, Apache 2.0 (with some BSL-licensed enterprise components separated).
- Deployed via Docker Compose, Kubernetes (Helm), or abctl (Airbyte's new deployment CLI as of 2024).
- Cost = customer's infra: compute (worker pods), object storage (logs/state), DB (Postgres for config).
- No vendor bill. No row-based cost. Cost intelligence = compute + storage.

**Airbyte Self-Managed Enterprise**
- Same binaries + enterprise features (SSO, RBAC, multi-tenant, audit, CMK, PrivateLink).
- Annual license — typical $50K-$300K list, negotiated.
- Still customer-hosted; customer pays infra.

**Airbyte Cloud — Credits-based (current model)**
- Purchase Airbyte Credits at ~$2.50/credit list (committed), some discounting on annual commits.
- Credits consumed per sync activity:
  - **Database & API connectors**: $10 / 1,000,000 rows synced (approx 4 credits/1M rows)
  - **File-based connectors** (S3, GCS, Azure, Google Drive): $3-$10 / GB tiered
  - **Custom / Low-code connectors (Connector Builder)**: same as database tier
- Free initial sync tier: first 14 days of historical sync often free per connection.
- Unused credits roll over 1 year.
- See https://airbyte.com/pricing and https://docs.airbyte.com/using-airbyte/credits-faq

**Airbyte Cloud — Capped plans (reintroduced 2024)**
- **Free**: 10K rows/month, limited connectors, for trial.
- **Team**: ~$360/month flat, 15 connectors, RBAC.
- **Business**: ~$1,250/month flat with row volume included.
- **Enterprise Cloud**: usage+committed, SSO, 24/7 support.

**Key nuances:**
- Rows-synced counting differs from Fivetran's MAR. Airbyte counts **every row touched in every sync** — a row that changes daily for 30 days = 30 rows, not 1. Consequently on high-frequency syncs, Airbyte can be more expensive than the same workload on Fivetran, or less expensive if the sync frequency is lower. Optimization lever: reduce sync frequency or use incremental+deduped modes.
- **Incremental vs Full Refresh** — a Full Refresh syncs all rows every run; expensive on Cloud. Incremental + Append/Dedup syncs only changed rows.
- **Source → Destination pairs**: each is a "Connection"; billing is per-connection rows.
- **Sync retries** — failed syncs that retry bill rows twice (once per attempt). Airbyte Cloud only bills successful sync rows? Ambiguous — community threads suggest partial syncs are billed; official doc is unclear.

## Billing / Usage Data Sources

### Primary

**Airbyte Cloud API v1** — https://reference.airbyte.com
Base: `https://api.airbyte.com/v1`
Auth: `Authorization: Bearer <access_token>` — OAuth2 client credentials flow. Token expires ~15 min.
Getting a token: POST `https://api.airbyte.com/v1/applications/token` with `client_id` + `client_secret` → returns `access_token`.

Key endpoints:
- `GET /workspaces` — workspaces list (paginated)
- `GET /workspaces/{workspaceId}`
- `GET /connections` — all connections (paginated); filter by `workspaceIds`
- `GET /connections/{connectionId}`
- `GET /jobs` — sync jobs history; filter by `connectionId`, `status`, `createdAtStart`, `createdAtEnd`. Paginated with `offset`+`limit`.
- `GET /jobs/{jobId}` — job detail with `bytesSynced`, `rowsSynced`, `jobType`, `startTime`, `lastUpdatedAt`, `duration`, `status`
- `GET /sources`, `GET /destinations`
- `GET /sources/{id}`, `GET /destinations/{id}`

No `/usage` or `/credits` endpoint exposed publicly. Credit consumption visible only in Cloud UI.

**Airbyte OSS / Self-Managed Config API** — https://docs.airbyte.com/api-documentation
Base: `http://<host>:8001/api/v1` (when deployed via abctl locally) or `http://<host>:8006/api/v1` or `http(s)://<your-domain>/api/v1` depending on ingress.
Auth: NONE by default (localhost), or Basic auth if reverse-proxy enforces, or SSO in Enterprise. Bearer token is NOT supported on OSS Config API.
Request style: **POST with JSON body**, not GET with query params. This is a legacy style from the pre-Cloud era.
Key endpoints:
- `POST /workspaces/list` — body `{}` — returns all workspaces
- `POST /connections/list` — body `{"workspaceId": "..."}` 
- `POST /connections/get` — body `{"connectionId": "..."}`
- `POST /jobs/list` — body `{"configId": "<connectionId>", "configTypes": ["sync"]}` — paginated via `pagination.pageSize` + `pagination.rowOffset`
- `POST /jobs/get` — body `{"id": jobId}`
- `POST /sources/list`, `POST /destinations/list`

**Airbyte OSS has also released an Airbyte API** (different from Config API): starting 0.50+, a REST-style `/api/v1` that mirrors Cloud's API shape. This is enabled via the `airbyte-api-server` service. URL: `http://<host>:8006/v1/...` or equivalent. Cleaner but not default on every deployment; abctl enables it.

**Airbyte Terraform provider** — https://registry.terraform.io/providers/airbytehq/airbyte — reads config; not for usage but useful for resource enumeration.

### Secondary

- **Cloud Billing page** — https://cloud.airbyte.com/billing — human-only; shows credit balance, consumption chart, row-by-row breakdown per connection. No export.
- **Audit logs** — https://docs.airbyte.com/cloud/managing-airbyte-cloud/audit-logs — Enterprise only.
- **Webhooks** — Airbyte can POST to a URL on sync complete/failed — https://docs.airbyte.com/cloud/managing-airbyte-cloud/manage-notifications
- **Temporal (internal workflow engine)** — OSS exposes workflow history via Temporal UI at `:8080`, which has rich sync-attempt data but is an undocumented interface.
- **Airbyte logs** — written to object storage (S3/GCS/local); structured JSON with per-stream rows_extracted and bytes_extracted.
- **Datadog / Prometheus metrics** — Airbyte OSS exposes `/metrics` on some services when `METRIC_CLIENT=otel` or similar is set.

### Gotchas

1. **Cloud vs OSS API mismatch.** Bearer token → Cloud. Basic/none → OSS Config API. GET → Cloud. POST-with-body → OSS Config API. Costly's code assumes GET+Bearer uniformly — breaks on OSS.
2. **OAuth token management for Cloud.** Cloud API tokens are short-lived (15 min). Need refresh logic. Costly treats `api_token` as a long-lived bearer — will fail after first 15 min if given a real OAuth access token; only works if customer pastes a long-lived Personal Access Token (not officially supported for production).
3. **`/jobs` pagination.** Cloud uses `offset`+`limit`; OSS Config API uses `pagination.rowOffset`+`pagination.pageSize`; OSS Airbyte API (new) uses `offset`+`limit`. Three patterns.
4. **`rowsSynced` semantic.** On Cloud this is the billable unit. On OSS it's whatever the source emitted; doesn't translate to cost without a $/row assumption.
5. **Sync modes.** Full Refresh vs Incremental syncs produce very different row counts. A 10M row table on full refresh daily = 300M rows/month; on incremental only changed rows.
6. **Failed attempts.** A sync can have multiple attempts (retries). `job.attempts[].status` matters. The `rowsSynced` at the job level is the sum of attempts that emitted rows — can double-count.
7. **Self-hosted has no cost.** In OSS mode, there are no rows-based cost dollars. Costly's current `self-hosted → cost = 0` is technically correct but misleading; compute+storage cost is real and should be attributed from the K8s/EC2 bill separately.
8. **Connector version churn.** A source connector version bump can change row-counting behavior. Upstream OSS releases multiple times per week.
9. **`connections` endpoint** response shape varies: Cloud returns `{"data": [...]}`, OSS returns `{"connections": [...]}`. Costly handles both via `data.get("data", data.get("connections", []))` — ok but fragile.
10. **Rate limits.** Cloud API: 60 req/min typical. OSS: none enforced; customer's machine-limit.

## Schema / Fields Available

From Cloud `GET /jobs/{jobId}`:
```
jobId                 integer
status                "running"|"succeeded"|"failed"|"cancelled"|"incomplete"
jobType               "sync"|"reset"
startTime             iso8601
lastUpdatedAt         iso8601
duration              string  PT5M30S (ISO 8601)
bytesSynced           integer
rowsSynced            integer
connectionId          string
```

From Cloud `GET /connections/{connectionId}`:
```
connectionId          string
name                  string
sourceId              string
destinationId         string
workspaceId           string
status                "active"|"inactive"|"deprecated"
schedule              object  {scheduleType, cronExpression, ...}
dataResidency         "auto"|"us"|"eu"
namespaceDefinition   "source"|"destination"|"customformat"
namespaceFormat       string
nonBreakingSchemaUpdatesBehavior  "ignore"|"disable_connection"|"propagate_columns"|"propagate_fully"
configurations        {streams: [...]}  each stream has syncMode, primaryKey, cursorField
```

From OSS `POST /jobs/list` attempt detail:
```
attempts[].id
attempts[].createdAt, endedAt
attempts[].status
attempts[].totalStats.recordsEmitted
attempts[].totalStats.bytesEmitted
attempts[].totalStats.stateMessagesEmitted
attempts[].streamStats[].streamName
attempts[].streamStats[].stats.recordsEmitted
```

## Grouping Dimensions

- **Workspace** — top-level tenant; Cloud typically 1, Enterprise multiple
- **Connection** — source+destination pair
- **Source** — input system (Postgres, Salesforce, S3)
- **Destination** — warehouse/lake
- **Stream** — specific table/entity within a source (finest grain on OSS)
- **Sync mode** — full_refresh vs incremental; critical cost lever
- **Job type** — sync vs reset (a reset re-runs history)
- **Date** — daily bucket from `startTime`

## Open-Source Tools

Airbyte is itself open source, so its ecosystem is largely OSS:

1. **Airbyte itself** — https://github.com/airbytehq/airbyte — Connector Builder, 550+ connectors, platform.
2. **airbyte-api SDK (Python)** — https://github.com/airbytehq/airbyte-api-python-sdk — generated from OpenAPI.
3. **airbyte-api SDK (JS)** — https://github.com/airbytehq/airbyte-api-js-sdk
4. **Terraform provider** — https://github.com/airbytehq/terraform-provider-airbyte
5. **Airbyte Octavia CLI** — deprecated in favor of Terraform.
6. **abctl** — https://github.com/airbytehq/abctl — official deployment CLI, replaces docker-compose path.
7. **Dagster airbyte integration** — https://github.com/dagster-io/dagster/tree/master/python_modules/libraries/dagster-airbyte — orchestration + observability.
8. **Airflow Airbyte operator** — https://github.com/apache/airflow/tree/main/providers/src/airflow/providers/airbyte
9. **Prefect airbyte integration** — prefect-airbyte collection.
10. **dbt-airbyte** — community package to normalize Airbyte-landed schemas.
11. **Airbyte Connector Builder** — low-code web UI for custom connectors.
12. **PyAirbyte** — https://github.com/airbytehq/PyAirbyte — run Airbyte connectors locally as a Python library (no platform). Useful for ad-hoc ingest.
13. **airbyte-ci** — CI tooling for connector development.
14. **airbyte_protocol** — https://github.com/airbytehq/airbyte-protocol — protobuf/JSON schema for source/destination communication.
15. **Community connector catalogs** — many connectors live under `airbyte-integrations/connectors/source-*/` in the main repo.

No single OSS project focuses on Airbyte **cost observability** specifically — this is a gap. Most cost tooling piggybacks on the Cloud UI or computes in-house from the Jobs API.

## How Competitors Handle Airbyte

**Airbyte Cloud's own observability** — https://cloud.airbyte.com — Connection page shows sync history, rows synced, job duration, success rate. Billing page shows credit consumption. No shareable export.

**Airbyte OSS UI** — `http://<host>:8000` — Connection page shows sync history and rows; no cost (OSS has no vendor cost).

**Open Source OSS Dashboard (community)** — various Grafana dashboards on GitHub for Airbyte Kubernetes deployments (CPU/memory per worker pod, job queue depth). Example: https://grafana.com/grafana/dashboards/17026 (and successors).

**SYNQ** — https://synq.io — ingests Airbyte jobs as part of pipeline observability; surfaces row counts, sync duration, failure rate. Cost is secondary.

**Datafold** — does diffs across Airbyte-landed data; not cost-focused.

**Monte Carlo** — freshness monitoring for Airbyte-landed tables.

**Datadog Airbyte integration** — https://docs.datadoghq.com/integrations/airbyte/ — pulls Prometheus metrics; useful for OSS cost via pod resource tracking.

**Vantage** — no first-class Airbyte integration yet (2026-04). For OSS, you use Vantage's K8s/EKS integration to pull pod cost, then tag by namespace.

**CloudZero** — same story as Vantage for OSS.

What dashboards typically surface:
- Rows synced per connection (daily, weekly, monthly)
- Credit burn rate (Cloud)
- Sync duration p50/p95 per connection
- Failed sync count
- Idle connections (active but never sync)
- Sync mode audit (which are full refresh — candidates for incremental)

## Books / Published Material

- **"Airbyte: Building an Open Source Data Integration Platform"** — community-written O'Reilly shorts and blog series.
- **"Fundamentals of Data Engineering"** — Joe Reis — covers Airbyte as an ELT option.
- **Airbyte blog** — https://airbyte.com/blog — covers pricing, OSS vs Cloud, use cases.
- **Airbyte docs** — https://docs.airbyte.com — surprisingly comprehensive, reference-grade.
- **Michel Tricot / John Lafleur talks** — Airbyte co-founders; Data Council, Data Engineer Summit.
- **Benn Stancil's Substack** — ELT market commentary, Airbyte-vs-Fivetran pieces.
- **Locally Optimistic** — practitioner posts on adopting Airbyte OSS.
- **Seattle Data Guy** — Airbyte reviews.
- **"The Informed Company"** — cost-aware ELT.
- **Airbyte "ELT Field Guide"** ebook — https://airbyte.com/elt-field-guide
- **Community-run conferences** — "Airbyte Move(fast)" events.
- **MDS podcast episodes** with Michel Tricot.
- **dbt × Airbyte joint whitepapers** — several on ELT + analytics engineering.
- **Airbyte "Migrating from Fivetran"** guide.

## Vendor Documentation Crawl

- Overview: https://docs.airbyte.com
- API: https://reference.airbyte.com (Cloud)
- Config API (OSS): https://airbyte-public-api-docs.s3.us-east-2.amazonaws.com/rapidoc-api-docs.html
- Deployment (abctl): https://docs.airbyte.com/using-airbyte/getting-started/oss-quickstart
- Helm chart: https://github.com/airbytehq/airbyte-platform/tree/main/charts/airbyte
- Pricing: https://airbyte.com/pricing
- Credits FAQ: https://docs.airbyte.com/using-airbyte/credits-faq
- Enterprise setup: https://docs.airbyte.com/enterprise-setup/
- Cloud OAuth: https://docs.airbyte.com/cloud/managing-airbyte-cloud/configuring-api-access
- Audit logs: https://docs.airbyte.com/cloud/managing-airbyte-cloud/audit-logs
- Notifications: https://docs.airbyte.com/cloud/managing-airbyte-cloud/manage-notifications
- Changelog / GitHub releases: https://github.com/airbytehq/airbyte/releases
- Connector catalog: https://docs.airbyte.com/integrations/

## Best Practices

1. **Detect deployment type first.** Based on `base_url`:
   - `api.airbyte.com` → Cloud (GET + Bearer + OAuth refresh)
   - Else → OSS (POST + optional Basic + JSON body)
   Branch the HTTP calls accordingly.

2. **For Cloud, implement OAuth refresh.** Cache access token with a 14-minute expiry; refresh proactively. Store `client_id`/`client_secret` (not long-lived bearer).

3. **For OSS, prefer the new Airbyte API** at `:8006/v1` when available (more REST-like, less legacy POST). Fall back to Config API at `:8001/api/v1` if not.

4. **Only bill rows for Cloud.** OSS rows do not map to vendor cost. Infra cost (K8s/EC2) comes from the AWS connector.

5. **Price bands.** Cloud database/API: $10/1M rows. Cloud file: $3-10/GB. Default $10/1M rows unless connector service is in {s3, gcs, azure-blob, google-drive, dropbox, file, sftp, ftp}. Surface both pricing bands in config.

6. **Exclude `reset` jobs from billed rows** where possible — resets are replay, not incremental.

7. **Aggregate at job-attempt level, not job level.** A job with 3 retries may have 3x rows at the attempts level but correctly reports unique rows at the job level.

8. **Sync-mode audit.** Report connections using Full Refresh where Incremental is available. Major cost lever.

9. **Rate-limit protection.** 60 req/min on Cloud; hit lightly.

10. **Bucket by dataResidency.** EU vs US accounts may have different pricing (some enterprise contracts regionalize).

## Costly's Current Connector Status

File: `backend/app/services/connectors/airbyte_connector.py`

What it does well:
- Distinguishes Cloud vs non-Cloud via `self.is_cloud` check on URL.
- Aggregates jobs into daily buckets per connection with bytes, records, duration.
- Correctly skips zero-cost/zero-records rows.
- Uses `$15/1M records` cost — close-ish to actual Airbyte Cloud $10/1M (documented as $10 current).
- Does not attempt to infer cost for OSS (returns 0).

Gaps:
- **OSS auth is wrong.** `Bearer <api_token>` on an OSS Config API returns 401 or 404 depending on ingress.
- **OSS endpoints are wrong.** GET `/connections` on OSS Config API returns `{"error": "method not allowed"}`. Correct: POST `/connections/list` with `{"workspaceId": ...}` body.
- **Cloud OAuth not implemented.** Treats `api_token` as long-lived bearer. Works with a Personal Access Token but those are ephemeral/unsupported for prod.
- **Pricing is $15/1M** — current Airbyte Cloud is $10/1M. Off by 50%.
- **File connectors not handled differently** — should be priced per GB.
- **No connector-service-type detection** — `source.name` is used as a string but not mapped to a family.
- **No pagination on `/jobs`** — `limit=100` is the ceiling; high-volume connections (sub-minute sync) produce >100 jobs/month easily.
- **`status=succeeded` filter** on jobs excludes partial syncs that still incurred rows. Might under-count.
- **OSS "self-hosted cost = 0"** is defensible but should ideally cross-reference the infra connector (AWS EKS / EC2) to show true cost.
- **No workspace filtering.** Fetches all connections regardless of workspace — Enterprise customers with multiple workspaces get mixed data.

## Gaps

- **Cloud OAuth client-credential flow.** Required for production.
- **OSS API support (real).** Three API variants (legacy Config POST, new Airbyte API GET, Enterprise) need branching.
- **File connector pricing.** GB-based; requires mapping by `source.sourceType`.
- **Sync-mode awareness.** Surface Full Refresh connections as cost-optimization opportunities.
- **Per-stream attribution.** Cloud Jobs API returns stream-level stats; useful for "which table costs most".
- **Retry / attempt accounting.** Don't double-count retried syncs.
- **Data residency / region.** Cloud API uses same base URL but contracts vary.
- **Self-hosted infra cost mapping.** Cross-link to AWS/K8s connector to attribute EKS pod cost to Airbyte namespaces.
- **Credit balance / burn rate.** Would require a private/internal Cloud endpoint not currently exposed.

## Roadmap

Phase 1 (2-3 days):
- Correct OSS path. Accept `host` + optional `username`/`password` credentials. POST to `/api/v1/workspaces/list` body `{}`; POST `/api/v1/connections/list` body `{"workspaceId": ...}`; POST `/api/v1/jobs/list` body `{"configId": connectionId, "configTypes": ["sync"], "pagination": {"pageSize": 100, "rowOffset": N}}`.
- Update Cloud pricing to $10/1M rows.
- Add pagination for `/jobs` on both Cloud and OSS.
- Add `cost_is_estimate: True` in metadata.

Phase 2 (3-5 days):
- OAuth2 client-credentials flow for Cloud: accept `client_id` + `client_secret`; manage token refresh; fall back to legacy long-lived PAT for existing installs.
- File-connector detection and GB-based pricing.
- Aggregate rows at attempt level to avoid retry double-count.

Phase 3 (1 week):
- Per-stream breakdown (Cloud + OSS).
- Sync-mode audit report.
- Self-hosted infra attribution (join with AWS EKS cost if both connectors active).
- Workspace-aware bucketing.

Phase 4:
- Credit-balance scraping (if/when Cloud API exposes it).
- Connector-version churn tracking.
- Anomaly detection on rows-per-sync spikes.
- Recommend incremental+dedupe migrations.

## Change Log

- 2026-04-24: Initial knowledge-base created

## Re-recording contract fixtures

Contract tests for this connector live at `backend/tests/contract/test_airbyte.py`
and load JSON fixtures from `backend/tests/fixtures/airbyte/`. The fixtures are
intentionally hand-written from the public API docs so they don't leak any
real account data — every contributor can run the suite offline.

To capture fresh fixtures against a real Airbyte Cloud account when the API
schema drifts, set credentials and run pytest with `--record-mode=once`:

```bash
cd backend
AIRBYTE_API_TOKEN=xxx \
    pytest tests/contract/test_airbyte.py --record-mode=once
```

Then sanitize the captured JSON (strip account ids, emails, tokens) before
committing. See `docs/testing/contract-tests.md` for the philosophy.


