# Fivetran — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Fivetran is a managed-ELT SaaS that provides 500+ pre-built "connectors" (source integrations) that land data in the customer's warehouse. Pricing is consumption-based on **Monthly Active Rows (MAR)**, a proprietary row-counting metric. Understanding Fivetran cost requires understanding MAR: "an active row is any row that is inserted, updated, or deleted within a given month — counted once regardless of how many times it changes." A table with 10M rows where 100K change daily bills as 100K MAR not 3M MAR.

Costly's current `fivetran_connector.py` iterates groups → connectors → a `/usage/connectors/{id}` endpoint and falls back to `/connectors/{id}/syncs`. The `/usage` endpoint is **not a documented Fivetran REST API** — it appears in some third-party wrappers and community code but returns 404 on production Fivetran accounts as of 2026-04. The documented path for usage is the Account > Usage dashboard (no API) and, in 2024+, the Platform Connector (Fivetran's own dbt package that lands usage data in the warehouse). This is the single biggest correctness issue in Costly's connector.

Authoritative sources:
- https://fivetran.com/docs/rest-api
- https://fivetran.com/docs/rest-api/api-reference
- https://fivetran.com/pricing
- https://fivetran.com/docs/usage-based-pricing/mar
- https://fivetran.com/docs/logs/fivetran-platform
- https://github.com/fivetran/dbt_fivetran_log
- https://fivetran.com/docs/core-concepts/architecture

## Pricing Model (from vendor)

Five SKU bands as of 2026-04 (https://fivetran.com/pricing):

**Free**
- 500K MAR/month, max 5 users, 1 destination
- All connectors available, 5-min sync interval floor (slower than paid)
- No log connector, no Platform Connector

**Starter — usage-based, $0-$1,000/mo typical**
- No MAR cap; priced on tiered MAR curve
- All standard connectors
- 15-min sync minimum, email support
- Published per-MAR tier (approximate, negotiated):
  - 0-250K MAR: baseline ~$500/mo floor
  - 250K-500K MAR: +$1.50/1K MAR
  - 500K-1M: +$1.25/1K MAR
  - 1M-10M: ~$1.00/1K MAR (volume discount)
  - 10M+: negotiate

**Standard — typical $1K-$10K/mo**
- 5-min sync interval
- dbt Core / Fivetran Transformations
- Priority support, SLA
- Slightly lower per-MAR rate than Starter

**Enterprise — typical $10K-$100K+/mo, annual committed**
- 1-min sync interval
- Fivetran Transformations Scheduler advanced features
- SSO, SCIM, private networking (PrivateLink, VPC peering)
- Custom connector SDK
- Priority support with named CSM

**Business Critical — top tier, $50K-500K+/mo**
- Data residency controls (EU, APAC, US)
- HIPAA BAA, PCI
- FedRAMP (US Gov)
- Customer-managed keys (CMK)
- Hybrid Deployment (run connectors in customer's cloud)

**Connector families & exceptions:**
- **Database connectors** (Postgres, MySQL, SQL Server, Oracle, MongoDB): priced per MAR as described.
- **File connectors** (S3, GCS, Azure Blob, Google Sheets, Google Drive, Box): priced per volume (GB) not per MAR. ~$3-$10/GB depending on plan.
- **Event connectors** (Segment, Snowplow, webhooks): priced per event row.
- **Application connectors** (Salesforce, HubSpot, Zendesk, Stripe, NetSuite): per MAR.
- **"Lite" connectors** (community-built, less-SLA): priced at ~50% of standard MAR rate.
- **High Volume Agent (HVA)** for log-based CDC from SQL Server/Oracle: separate licensing, per-compressed-log-GB.

**Consumption credits vs direct MAR billing:**
Fivetran historically billed monthly on MAR usage. In 2023+ they introduced **Fivetran Credits** for annual committed customers — prepay a credit pool, consume against it on the same MAR/volume curve. Unused credits expire annually. This makes monthly cost unpredictable on pure MAR but gives committed customers a budget ceiling.

**Free initial sync** — Fivetran famously bills MAR only on *incremental* changes. The full historical initial load is free. Re-sync (after schema drift) triggers MAR spike.

**Transformations billing** — Fivetran Transformations (dbt Core in Fivetran) is **free on Standard+** when using Fivetran-scheduled runs, and the integrated Transformation Scheduler is included. External dbt Cloud is separate billing (see dbt-cloud.md).

**Monthly commitment floor** — Starter typically has a $500/mo floor even if you use 0 MAR.

## Billing / Usage Data Sources

### Primary

**Fivetran REST API v1** — https://fivetran.com/docs/rest-api
Base: `https://api.fivetran.com/v1`
Auth: HTTP Basic with `api_key` + `api_secret` (from Account Settings → API Config)
Documented endpoints:
- `GET /groups` — groups (destinations) list
- `GET /groups/{id}` — single group
- `GET /groups/{id}/connectors` — connectors within group
- `GET /connectors/{id}` — single connector detail (includes `sync_frequency`, `schedule_type`, `paused`, `succeeded_at`, `failed_at`, `setup_state`, `sync_state`, `schema`, `service`, `source_sync_details`)
- `GET /destinations/{id}` — destination config
- `GET /users` — user list
- `GET /teams` — teams & permissions
- `GET /metadata/connectors` — catalog of available connector types
- `GET /groups/{id}/service-account` — destination service account

**Undocumented/internal endpoints referenced in the community:**
- `/usage/connectors/{id}` — what Costly currently attempts; returns 404 in production. Likely an internal analytics endpoint not exposed to customers.
- `/connectors/{id}/syncs` — also not documented in official REST reference; works in some cases but undocumented.

**The documented usage data path is NOT the REST API.** Fivetran exposes usage via:

**Fivetran Platform Connector** — https://fivetran.com/docs/logs/fivetran-platform
This is a first-party Fivetran connector that writes Fivetran's own operational data INTO the customer's destination warehouse. It lands tables like:
- `fivetran_platform.connector` — connector configs
- `fivetran_platform.log` — sync event logs
- `fivetran_platform.mar_table_daily` — **the MAR table** with `measured_date`, `connector_id`, `schema_name`, `table_name`, `incremental_rows`, `free_rows`, `total_mar`
- `fivetran_platform.mar_connector_daily` — connector-level MAR rollup
- `fivetran_platform.account_membership`, `destination_membership`, `group_membership`, `user`, `role_membership`
- `fivetran_platform.transformation_runs`
- `fivetran_platform.incremental_mar` — per-sync delta
- `fivetran_platform.active_volume` — volume for file connectors

This connector must be enabled explicitly (free on all tiers). Once enabled, MAR data is queryable in the customer's warehouse.

**dbt package for Platform Connector** — https://github.com/fivetran/dbt_fivetran_log — models on top of the raw logs to produce `fivetran__connector_status`, `fivetran__mar_summary`, `fivetran__usage_mar_destination_history`.

### Secondary

- **Fivetran UI Usage page** — https://fivetran.com/account/usage — human-only; shows MAR by connector, by destination, by month with a 13-month history. No export API.
- **Invoice CSV export** — Enterprise admins can download monthly invoices from the billing portal; machine-parseable but no API.
- **Event notifications / webhooks** — Fivetran can POST to a customer URL on sync success/fail/schema-change — https://fivetran.com/docs/rest-api/webhooks. Doesn't include MAR.
- **Cloud Function quickstart** — https://github.com/fivetran/cloud_functions — GCP/AWS samples that poll the REST API.
- **Fivetran Audit Log** — shipped via Platform Connector table `fivetran_platform.audit_user_activity`.

### Gotchas

1. **No official `/usage` endpoint.** The REST API does not expose MAR or cost. Costly's current code will silently fail past the `except: pass` on every real customer. This is the top priority fix.
2. **MAR vs rows_synced.** A single row updated daily for 30 days = **1 MAR** but **30 rows_synced**. Computing `sum(rows_synced)` will overstate MAR by 10-100x on high-churn tables. Do not use sync counts as a proxy.
3. **Free rows** — rows synced during the initial historical load are free. `free_rows` column in `mar_table_daily` must be subtracted when computing billable MAR.
4. **Re-sync events.** A re-sync can blow past monthly MAR in a single day. Flag connectors with `setup_state != "connected"` or recent `forced` re-syncs.
5. **Connector-family pricing.** MAR doesn't apply to file/volume connectors. `service` field must be mapped to family (database/application/file/event) before costing.
6. **Regional API.** Fivetran EU accounts use `api.fivetran.com` too but data stays in EU. Business Critical customers on dedicated infra may have custom base URLs — rare but check.
7. **API pagination.** All list endpoints paginate with `cursor` query param and `next_cursor` in response (not offset/limit). Costly's connector does not paginate `/groups` — fine for small accounts, broken for customers with 100+ destinations.
8. **Rate limit.** 3 requests/sec per API key; 300 burst. Not published clearly.
9. **Basic auth secrets.** `api_secret` is a real secret — treat as password. Fivetran rotates on demand.
10. **Schema change billing.** A schema change (new column) triggers a historical backfill on that column → MAR spike — shows as `free_rows = true` usually, but edge cases exist.
11. **Deleted connectors** — once deleted, historical MAR is retained in `mar_connector_daily` but the connector id resolves 404 on `/connectors/{id}`. Costly's `if resp.status_code != 200: return []` handles this but silently.
12. **Paused connectors** continue to bill MAR on already-synced rows? No — a paused connector stops incremental sync, so no new MAR. But the connector still counts as a "connector" for plan-level limits.

## Schema / Fields Available

From `GET /groups`:
```
id              string      "group_abc"
name            string      destination name
created_at      iso8601
```

From `GET /groups/{id}/connectors`:
```
id                    string      connector unique id
group_id              string
service               string      "salesforce", "postgres", ...
service_version       integer
schema                string      destination schema name
paused                bool
pause_after_trial     bool
connected_by          string      user_id
created_at            iso8601
succeeded_at          iso8601     last successful sync
failed_at             iso8601     last failure
sync_frequency        integer     minutes
schedule_type         "auto"|"manual"
status.setup_state    "connected"|"incomplete"|"broken"
status.sync_state     "scheduled"|"syncing"|"paused"|"rescheduled"
status.update_state   "on_schedule"|"delayed"|"rescheduled"
status.is_historical_sync  bool
status.tasks          []     pending tasks
status.warnings       []
daily_sync_time       "HH:MM"
source_sync_details   object  service-specific
```

From Platform Connector `mar_table_daily`:
```
measured_date         date
connector_id          string
schema_name, table_name  string
incremental_rows      integer   active rows
free_rows             integer   non-billable (initial sync, reprocess)
total_mar             integer   = incremental_rows (redundant column)
```

## Grouping Dimensions

- **Group / Destination** — typically one per warehouse (prod_snowflake, stage_snowflake)
- **Connector** — one per source instance (e.g., prod_salesforce, prod_hubspot)
- **Source type / service** — salesforce, postgres, s3, ...
- **Source schema / table** — within-connector detail from `mar_table_daily`
- **User / Team** — who created the connector (RBAC)
- **Connector family** — database / application / file / event / lite
- **Date** — daily MAR is the finest grain available

Recommended dashboards: MAR by connector (top 10), MAR trend 30d, MAR by connector-family, re-sync events, failed connector count.

## Open-Source Tools

1. **dbt_fivetran_log** (official) — https://github.com/fivetran/dbt_fivetran_log — canonical MAR + status models. Depends on Platform Connector being enabled.

2. **Fivetran dbt packages (source-specific)** — https://github.com/orgs/fivetran/repositories — there's a separate dbt package for almost every Fivetran source connector (fivetran/dbt_salesforce_source, fivetran/dbt_hubspot_source, fivetran/dbt_netsuite_source, etc). Over 60 packages. They land raw Fivetran tables into clean staging layers.

3. **Terraform provider** — https://registry.terraform.io/providers/fivetran/fivetran — official. IaC for connectors; useful for audit + drift detection.

4. **Fivetran Python client** — https://github.com/fivetran/fivetran-api-client — thin REST wrapper.

5. **fivetran-sdk** — https://github.com/fivetran/fivetran_sdk — Connector SDK for writing custom connectors (Enterprise only).

6. **Cloud Functions samples** — https://github.com/fivetran/cloud_functions — serverless polling.

7. **dbt_fivetran_utils** — https://github.com/fivetran/dbt_fivetran_utils — macros used by all Fivetran dbt packages.

8. **fivetran-api-postman** — https://github.com/fivetran/postman_collections — Postman collections for API exploration.

9. **Airflow provider** — https://github.com/astronomer/airflow-provider-fivetran — DAG-based orchestration.

10. **Prefect Fivetran tasks** — prefect-fivetran integration.

11. **Dagster integration** — dagster-fivetran exposes sync status as assets.

12. **Community log aggregators** — various Snowflake/BigQuery Slack-bot samples for MAR alerts.

Most reusable for Costly: **dbt_fivetran_log + Platform Connector**. If the customer has it enabled, Costly can read `fivetran_platform.mar_connector_daily` directly from their warehouse — no Fivetran API calls needed, and the data is authoritative.

## How Competitors Handle Fivetran

**Fivetran's own Usage page** — https://fivetran.com/account/usage — native MAR by connector, 13-month rollup. No cost translation (shows MAR, user does the math). No API.

**Fivetran Transformations Hub** — UI for dbt runs executed within Fivetran. Separate from cost.

**Vantage Fivetran connector** — https://www.vantage.sh/integrations/fivetran — pulls MAR via their direct integration (not a public API, a private partnership). Surfaces MAR by connector, cost projections, rightsizing (e.g., "this connector's sync frequency is every 5 min but data only changes once/hour — reduce to save 50% MAR").

**CloudZero Fivetran** — https://www.cloudzero.com/integrations/fivetran/ — similar, more enterprise-focused.

**SYNQ** — https://synq.io — pipeline observability across Fivetran + dbt + warehouse; MAR surfaced but cost is secondary.

**Metaplane** — had Fivetran integration (dbt Labs acquired Metaplane 2025, roadmap uncertain).

**Monte Carlo** — https://docs.getmontecarlo.com/docs/fivetran-data-collector — ingests Fivetran logs for freshness monitoring; not primarily cost.

**Select.dev** — Snowflake-focused, Fivetran support added 2024 for total-ingestion-cost view.

What they recommend:
- MAR by connector with $ projected-end-of-month
- Sync frequency optimizer — reduce frequency where source changes are infrequent
- Connector health — broken connectors consume support attention
- Re-sync alerts — re-syncs are MAR-expensive
- Deleted connector archive — don't lose history when a connector is removed

## Books / Published Material

- **"Modern Data Stack" ebook** — Fivetran's own — https://www.fivetran.com/resources/ebook/modern-data-stack
- **"Fundamentals of Data Engineering"** — Joe Reis — Fivetran ELT chapter
- **Fivetran blog** — https://www.fivetran.com/blog — tagged "pricing", "MAR" has official explainers
- **"The Informed Company"** — cost chapter includes Fivetran MAR.
- **Benn Stancil's Substack** — critiques of Fivetran pricing model
- **Locally Optimistic** — practitioner posts on "is Fivetran worth it" cost analyses
- **Seattle Data Guy** — Fivetran vs Airbyte cost comparisons
- **dbt Discourse** — Fivetran-related threads
- **"Data Engineering with dbt"** — Roberto Zagni — Fivetran ingestion patterns
- **CloudZero blog** — Fivetran cost optimization series
- **Vantage blog** — MAR optimization tips
- **Fivetran REINVENT 2024 whitepaper** — competitive pricing analysis vs Airbyte, Stitch, Matillion
- **MDS podcast episodes** on Fivetran — multiple with Fivetran leadership
- **"High Performance Spark"** — tangentially relevant for batch-size tuning of destination loads

## Vendor Documentation Crawl

- Overview: https://fivetran.com/docs/rest-api
- Reference: https://fivetran.com/docs/rest-api/api-reference
- OpenAPI JSON: https://api.fivetran.com/v1/openapi.json (publicly available)
- Auth: https://fivetran.com/docs/rest-api/getting-started
- Pagination: https://fivetran.com/docs/rest-api/getting-started#pagination
- Webhooks: https://fivetran.com/docs/rest-api/webhooks
- Platform Connector: https://fivetran.com/docs/logs/fivetran-platform
- MAR explained: https://fivetran.com/docs/usage-based-pricing/mar
- Pricing: https://fivetran.com/pricing
- Connectors catalog: https://fivetran.com/docs/connectors
- Regions: https://fivetran.com/docs/using-fivetran/fivetran-dashboard/account-settings#regions
- Service Account SDK: https://github.com/fivetran/fivetran_sdk
- Changelog: https://fivetran.com/docs/changelog

## Best Practices

1. **Prefer Platform Connector over REST API for cost.** Ask the customer to enable the free Platform Connector. Then Costly's Snowflake/BigQuery connector can query `fivetran_platform.mar_connector_daily` directly. This is authoritative and free.

2. **Fall back to REST API for connector metadata** (`/groups`, `/connectors`) — REST is correct for config/state but wrong for MAR.

3. **Use `incremental_rows - free_rows`** (not `total_mar`) for billable MAR when available.

4. **Map `service` to connector family** for family-level aggregation. Maintain a lookup table: `postgres`, `mysql`, `sqlserver`, `oracle`, `mongodb` → database; `salesforce`, `hubspot`, `zendesk`, ... → application; `s3`, `gcs`, `azure_blob`, `google_drive`, `box`, `google_sheets`, `ftp` → file; `webhooks`, `segment`, `snowplow` → event.

5. **Surface `sync_frequency` per connector.** Many connectors are set to 5 min unnecessarily. Flag connectors where source change rate < sync frequency.

6. **Alert on re-sync.** Track `forced_sync_count_last_30d`. A forced re-sync can 10x MAR for a month.

7. **Track paused connectors.** A paused connector with a recent `paused_at` is cost-neutral going forward.

8. **Map MAR → $ using customer's tier.** Require the customer to enter their tier (Free/Starter/Standard/Enterprise/BC) and a custom $/MAR override. Default curves below:
   - Starter: $1.50/1K MAR after 500K free
   - Standard: $1.25/1K MAR
   - Enterprise: $1.00/1K MAR with volume bands
   - Free: $0/MAR below 500K, N/A above
   These are estimates; actual contracts negotiated.

9. **File-connector billing is volume-based.** Check `service` against file list; use `bytes_synced` not MAR for those.

10. **API pagination via cursor.** All list endpoints may return >100 items; use `next_cursor` loop.

## Costly's Current Connector Status

File: `backend/app/services/connectors/fivetran_connector.py`

What it does well:
- Correctly uses HTTP Basic auth with api_key + api_secret.
- Tests connection via `/groups` — a real documented endpoint.
- Iterates groups → connectors, preserving group names for resource labels.
- Graceful error swallow at the top-level (returns empty list on failure).

Gaps:
- **Calls undocumented `/usage/connectors/{id}` endpoint** — returns 404 in production. Silent except.
- **Fallback uses `/connectors/{id}/syncs`** — also undocumented and returns rows_synced, not MAR. MAR ≠ rows_synced; this overestimates for high-churn tables.
- **No pagination** — `_get_groups` and `_get_connectors` return first page only. Enterprise customers with 100+ connectors will have truncated data.
- **No file-connector handling** — S3/GCS priced by volume, not MAR; treated identically.
- **Pricing hardcoded at $1/1M MAR** — too simplistic and wrong for Starter ($1.50/1K MAR after 500K free).
- **No Platform Connector path** — the authoritative data source is ignored entirely.
- **No `free_rows` subtraction** — initial sync rows counted as billable.
- **Granular daily aggregation** depends on sync history shape, which Fivetran doesn't guarantee.
- **No rate limiting / retry** — 3 req/sec ceiling not respected.
- **Regional / BC custom base URLs** not supported.

## Gaps

- **MAR via Platform Connector.** Needs a cross-connector pattern: if both Fivetran and Snowflake connections exist in Costly, automatically query `fivetran_platform.mar_connector_daily` from Snowflake. This would become the primary data source and REST the fallback.
- **File connector support.** Different billing model entirely.
- **Event connector support.** Per-event pricing, different again.
- **Connector-family lookup table.** Hardcode in Python, maintained manually.
- **Pricing tier config.** Customer should enter their Fivetran tier + any custom negotiated rate in a Mongo config.
- **Sync-frequency waste detection.** Opportunity: show connectors where the actual change rate is 10% of the sync frequency → recommend lower frequency.
- **Invoice reconciliation.** No programmatic access to actual invoice; can only approximate. Communicate `cost_is_estimate: true` like dbt Cloud does.
- **Transformations billing.** Not tracked at all.

## Roadmap

Phase 1 (1-2 days):
- Remove the `/usage/connectors/{id}` call; it returns 404.
- Add cursor-based pagination to `/groups` and `/groups/{id}/connectors`.
- Add connector-family classification in a constants file.
- Mark cost as estimate (`cost_is_estimate: True`).
- Add 429/5xx retry with exponential backoff.

Phase 2 (2-3 days):
- Ingest Platform Connector tables when available. Add a "Fivetran cost uses warehouse data" banner in UI if Platform Connector is detected in the linked warehouse.
- Support file connectors (detect via service list; use `bytes_synced`).
- Pricing tier config form in Costly settings: tier dropdown + optional custom $/MAR + monthly minimum.

Phase 3 (3-5 days):
- Sync-frequency optimizer report.
- Re-sync / forced-sync event detection and alert.
- Per-table MAR breakdown when Platform Connector data is available.
- Transformations usage tracking.

Phase 4:
- Predictive end-of-month MAR forecast with confidence intervals.
- Anomaly detection on MAR spikes.
- Automated recommendation: "This connector syncs every 5 min but changes 1x/hour → switch to hourly to save ~$X/mo".

## Change Log

- 2026-04-24: Initial knowledge-base created

## Re-recording contract fixtures

Contract tests for this connector live at `backend/tests/contract/test_fivetran.py`
and load JSON fixtures from `backend/tests/fixtures/fivetran/`. The fixtures are
intentionally hand-written from the public API docs so they don't leak any
real account data — every contributor can run the suite offline.

To capture fresh fixtures against a real Fivetran account when the API
schema drifts, set credentials and run pytest with `--record-mode=once`:

```bash
cd backend
FIVETRAN_API_KEY=xxx FIVETRAN_API_SECRET=yyy \
    pytest tests/contract/test_fivetran.py --record-mode=once
```

Then sanitize the captured JSON (strip account ids, emails, tokens) before
committing. See `docs/testing/contract-tests.md` for the philosophy.


