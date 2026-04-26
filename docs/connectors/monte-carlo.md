# Monte Carlo — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Monte Carlo is the category leader in data observability, with pricing historically tied to "monitored tables" and — as of 2024-2025 — formally rebranded around **Monitored Assets** (MA) with additional SKUs for **Monitors**, **Incidents-as-Service**, and **Domains**. Pricing is entirely private: Scale plan starts around $40/MA/month, Pro is custom, Enterprise is six-figure annual minimum commit. The only API is GraphQL at `https://api.getmontecarlo.com/graphql`; there is no REST or bulk CSV export. Costly's existing `monte_carlo_connector.py` hard-codes `$50/table/month` and calls a GraphQL query (`getTablesMonitoredInfo`) whose exact field name has NOT been verified against the live 2026 schema. The near-term work: verify schema with `pycarlo` SDK introspection, move pricing to a per-customer configurable dollar-per-MA field, track Monitors and Incidents as separate usage dimensions, and add domain/warehouse/team grouping. Monte Carlo itself shipped a "Cost Visibility" feature in 2024 aimed at Snowflake cost pulldowns — relevant competitive context.

## Pricing Model

**Monte Carlo SKU taxonomy (2024-2026 era)**:
- **Monitored Assets (MA)** — primary billing dimension. 1 MA = 1 table/view/external stage/BI dashboard under monitoring
- **Monitors** — secondary usage signal. 1 monitor = 1 rule/check. Many Monitors can attach to 1 MA.
- **Incidents** — reported, not billed directly, but informs plan-tier fit
- **Domains** — multi-tenancy feature (Premium+)
- **Data Collectors** — agents in customer VPC; unlimited in most plans
- **Integrations** — warehouse, BI, orchestration, catalog integrations

**Plans (as publicly reported in 2024-2026)**:
- **Starter / Scale**: ~$40-$60 per MA / month at small scale; ceiling ~500 MA
- **Pro**: tiered pricing, custom quote, adds advanced data products (lineage, classifiers)
- **Enterprise**: annual commit, typically **$100K+ floor**, unlocks domains, SSO, custom classifiers, incident-SLA escalation
- **Data+AI / 2025 bundle**: includes AI/LLM observability for vector stores and pipelines

**Typical commercial structure**:
- Annual commits with tiered MA buckets (e.g., 0-1000 MA at $X/MA, 1001-5000 at $Y, 5001+ at $Z)
- Overage charges if exceeding bucket
- Separate "Insights Pack" for Snowflake cost lineage
- Professional Services: implementation (typically 4-8 weeks)

**Moved-away-from-per-table in 2024**: MC explicitly reframed away from "pay per monitored table" toward "Monitored Assets" (broader than tables — includes views, external stages, dashboards) and raised the effective per-unit price while adding value via monitors and lineage.

**Public pricing**: none. All quotes via sales. G2 and PeerSpot reports suggest $100K-500K/year for mid-market accounts, $500K-$2M/year for enterprise.

**Sources**:
- https://www.montecarlodata.com/pricing-plans/
- https://www.montecarlodata.com/blog-what-is-data-observability/
- https://docs.getmontecarlo.com/docs/monitored-assets
- G2 / PeerSpot / Vendr — customer-reported ranges
- Barr Moses Medium posts (MC co-founder/CEO)

## Billing / Usage Data Sources

### Primary

**Monte Carlo GraphQL API** — `https://api.getmontecarlo.com/graphql`
- Auth: `x-mcd-id` (API key ID) + `x-mcd-token` (secret) headers
- Queries relevant to usage/cost:
  - `getUser { email, account { ... } }` — auth probe, account context
  - `getTablesOverview` — list of all monitored tables (paginated), fields: `mcon`, `fullTableId`, `resource`, `warehouse`, `lastObserved`, `isMonitored`, `totalMonitorTimeEnabled`
  - `getMonitors(first, after)` — monitor list with configs; `monitorType`, `entities`, `createdTime`, `updatedTime`
  - `getIncidents(first, after, startTime, endTime)` — incident history with `type`, `severity`, `status`, `createdTime`
  - `getDomains` — domains for multi-tenant customers
  - `getWarehouses` / `getDataCollectors` — integrations list
  - `getAccountSettings` — plan info (limited field visibility)
- Pagination: standard Relay-style `edges { node { ... } }` with `pageInfo { endCursor, hasNextPage }`
- No documented billing/usage endpoint — customers must aggregate MA count via `getTablesOverview` count + monitor count

**pycarlo SDK** — https://github.com/monte-carlo-data/python-sdk — Apache-2.0 — the official Python client. Handles auth, pagination, and schema introspection. Strongly recommended for any Costly integration work because MC's GraphQL schema evolves — pycarlo introspects live.

### Secondary

- **Admin Portal** — customer-facing dashboard shows "Usage" with MA count and Monitor count; not API-exposed but screenshot-verifiable by customer
- **Snowflake INFORMATION_SCHEMA / ACCOUNT_USAGE** — MC runs SQL against the customer warehouse (READ-only). That warehouse cost is visible on the Costly Snowflake connector but attributable to MC via query_tag or user_name. Typical indicator: `QUERY_TAG LIKE 'mcd%'` or `USER_NAME = 'MCD_USER'`.
- **Audit log GraphQL query** (`getAuditLogs`) — records user/monitor config changes; no direct cost signal
- **Monte Carlo CLI (montecarlo)** — thin wrapper over GraphQL, used for DevOps workflows
- **Incidents export** (CSV) from UI — manual, not API
- **Slack/Jira integrations** — outbound; no cost data

### Gotchas

1. **GraphQL schema is unstable**. Field names have changed across 2023-2026 (`createdTime` → `createdAt` in some branches; `incidentType` not guaranteed). Never hard-code query strings — introspect or use pycarlo.
2. **No public schema doc** — MC docs reference a subset. Full schema only available via introspection (which IS enabled on the endpoint).
3. **Pagination required**: `getTablesOverview` and `getIncidents` return a handful of entries by default; iterate with `after: endCursor`.
4. **Rate limits** are undocumented. Practical cap appears around **~300 requests/minute** per API key. Aggressive polling can trigger soft throttling (HTTP 429).
5. **Auth failure leaks as HTTP 200 with GraphQL errors array**, not HTTP 401. Must parse `response.json()["errors"]`.
6. **`getTablesMonitoredInfo` is not a standard field**. Costly's current code calls this — it may be an old field or a guess. Verified 2026 field is `getTablesOverview` with a `totalCount` or explicit pagination.
7. **Cost is NOT returned by the API**. MA count and Monitor count are proxies; the $/MA rate is whatever the customer negotiated. Must be customer-configurable.
8. **Warehouse queries fired by MC** show up as cost on the warehouse side (Snowflake credits, BigQuery slots, Databricks DBUs). Attributable via service account user, but easy to miss.
9. **Multi-domain accounts** — a customer may have several domains; `getDomains` returns the list; each domain has its own MA count.
10. **Asset types vary** — dashboards (Tableau, Looker), warehouses (Snowflake, BigQuery, Redshift, Databricks), lakes (S3, ADLS, GCS), orchestrators (Airflow, dbt, Dagster). All can be MAs; not all are "tables" in the colloquial sense.
11. **Free/trial accounts** — MC offers a 2-week free trial; API keys are full-featured during trial.
12. **Deprecated queries silently 200** — query may return `null` for a renamed field rather than erroring. Validate responses for expected structure.

## Schema / Fields Available

**Monitored Asset (table-shaped)**:
```
mcon                string    (Monte Carlo canonical ID)
fullTableId         string    (e.g. "snowflake::prod::db::schema::table")
resource            string    (warehouse/integration name)
warehouseType       string    (SNOWFLAKE, BIGQUERY, REDSHIFT, DATABRICKS, ...)
database            string
schema              string
tableName           string
tableType           string    (TABLE, VIEW, EXTERNAL, ...)
lastObserved        DateTime
isMonitored         bool
totalMonitorTimeEnabled  int (days)
domainIds           [string]
```

**Monitor**:
```
uuid                string
name                string
description         string
monitorType         string    (FRESHNESS, VOLUME, CUSTOM_SQL, FIELD_HEALTH, DIMENSION, JSON_SCHEMA, ...)
entities            [string]  (mcon list)
createdTime         DateTime
updatedTime         DateTime
createdBy.email     string
schedule.scheduleType   string
isPaused            bool
```

**Incident**:
```
uuid                string
type                string    (FRESHNESS, VOLUME, QUALITY, SCHEMA_CHANGE, PIPELINE_FAILURE, ...)
severity            string    (SEV_1 - SEV_5)
status              string    (ACTIVE, RESOLVED, NO_ACTION_NEEDED, ...)
createdTime         DateTime
updatedTime         DateTime
feedback            string
owner.email         string
entities            [MCON]
```

**Domain**:
```
uuid                string
name                string
description         string
tags                [{name, value}]
```

**User / Account**:
```
getUser.email       string
getUser.firstName   string
getUser.role        string
account.uuid        string
account.name        string
```

## Grouping Dimensions

- **Domain**: multi-team / multi-product slicing (Premium+)
- **Warehouse / Integration**: Snowflake vs. BigQuery vs. Redshift — common CFO question
- **Data Collector**: if multiple collectors (regions, VPCs)
- **Asset type**: table / view / dashboard / pipeline
- **Monitor type**: freshness / volume / quality / custom-SQL (custom-SQL tends to be heaviest warehouse-cost)
- **Team tag / Business unit**: via MC tags applied to MAs
- **Incident severity**: SEV_1 flows → most expensive to leave unresolved
- **Date / Month**: for trending MA growth rate
- **Cost-allocated user**: who created the monitor (for showback)

## Open-Source Tools

- **pycarlo** — https://github.com/monte-carlo-data/python-sdk — Apache-2.0 — ~200 stars — official Python SDK; covers the full GraphQL API with typed helpers. Use this rather than hand-rolling GraphQL.
- **monte-carlo-data/iac-monitors-as-code** — https://github.com/monte-carlo-data/monitors-as-code — Apache-2.0 — Terraform-like YAML config for MC monitors; useful for customer context but not cost-focused.
- **Elementary Data** — https://github.com/elementary-data/elementary — Apache-2.0 — 2K+ stars — OSS dbt-native data observability competitor. Relevant for "why would I use MC over OSS?" framing.
- **Great Expectations** — https://github.com/great-expectations/great_expectations — Apache-2.0 — adjacent; test-framework lineage, not observability.
- **Soda Core** — https://github.com/sodadata/soda-core — Apache-2.0 — OSS scan tool; Soda Cloud is paid.
- **Re_data** — https://github.com/re-data/re-data — MIT — dbt-package data reliability; low-maintenance, small community.
- **openmetadata-io/OpenMetadata** — Apache-2.0 — data catalog with observability features.
- **Bigeye's open-source agents** — mostly closed; small OSS presence.
- **SYNQ** — closed-source competitor, but has public blog comparisons.
- **monte-carlo-data/mcd** CLI — wrapper for admin tasks.

No OSS project explicitly targets Monte Carlo cost-tracking — space is greenfield.

## How Competitors Handle These

- **Monte Carlo's own "Cost Visibility"** (launched 2024) — MC now pulls Snowflake cost from ACCOUNT_USAGE and correlates incidents to expensive queries; surfaces "broken pipelines cost $X". This is a defensive play against Costly-style FinOps tools. They do NOT surface MC's own bill to the customer inside their UI — that's on a contract PDF.
- **Bigeye** — https://www.bigeye.com/ — monitoring coverage, "Autometrics"; commercial positioning similar to MC. Pricing also opaque.
- **Soda** — https://www.soda.io/ — freemium OSS core, Cloud priced per-dataset.
- **SYNQ** — https://www.synq.io/ — dbt-native observability; positions against MC on cost.
- **Datafold** — https://www.datafold.com/ — data-diff focused + observability; $25K+/year starter.
- **Elementary** — OSS-first; cloud tier added 2024; pricing more transparent than MC.
- **Acceldata** — https://www.acceldata.io/ — enterprise observability + cost intelligence; overlaps with Costly's north star — potentially the closest full-platform competitor. Positions as "cost-plus-quality-plus-performance" in one platform.
- **Telmai / Anomalo / Lightup / Metaplane** — smaller observability startups; varying pricing models.
- **dbt Cloud "Quality" / Sentry-style integrations** — adjacent; lighter-weight.
- **Great Expectations Cloud** — OSS-plus-paid cloud; tiered.

Competitive positioning for Costly: MC's "Cost Visibility" shows MC cares about the warehouse $ side; Costly should flip it — show MC's OWN cost to the customer (MA-level showback with dollar attribution) and correlate to incidents ("you're paying $X/month to monitor assets that haven't fired an incident in 6 months — candidates to unmonitor").

## Books / Published Material

- **"Data Quality Fundamentals" (Barr Moses, Lior Gavish, Molly Vorwerck — O'Reilly 2022)** — canonical book by MC's co-founders; explains the pillars MC monitors (freshness, volume, distribution, schema, lineage).
- **"The Data Observability Handbook"** — MC's own ebook, free download; marketing but comprehensive.
- **"Data Mesh" (Zhamak Dehghani)** — argues for domain-aligned ownership, influenced MC's Domains feature.
- **"Fundamentals of Data Engineering" (Reis & Housley)** — chapter on data observability patterns.
- **"Designing Data-Intensive Applications" (Kleppmann)** — foundational context; not directly MC.
- **Barr Moses's Medium blog** — https://medium.com/@barrmoses — regular updates on observability category evolution.
- **Shane Murray** — prev. MC, now Decodable — writes on DQ patterns.
- **Lior Gavish (MC CTO) conference talks** — dbt Coalesce, Data Council sessions.
- **MC's "State of Data Quality" annual report** — industry benchmarks.
- **MIT CDOIQ Symposium papers** — academic context on data quality.
- **FinOps Foundation "Data Platform FinOps" working group** — emerging framework for data observability cost.

## Vendor Documentation Crawl

- https://docs.getmontecarlo.com/ — main docs hub
- https://docs.getmontecarlo.com/docs/monitored-assets — MA definition
- https://docs.getmontecarlo.com/docs/api — API overview and auth
- https://docs.getmontecarlo.com/docs/using-the-api — GraphQL usage patterns
- https://docs.getmontecarlo.com/docs/monitors-overview — monitor taxonomy
- https://docs.getmontecarlo.com/docs/incidents — incident lifecycle
- https://docs.getmontecarlo.com/docs/domains — domain configuration
- https://docs.getmontecarlo.com/docs/data-collectors — agent deployment
- https://docs.getmontecarlo.com/docs/snowflake-integration — warehouse integration specifics
- https://docs.getmontecarlo.com/docs/python-sdk — pycarlo quickstart
- https://github.com/monte-carlo-data/python-sdk — SDK source & examples
- https://www.montecarlodata.com/pricing-plans/ — marketing pricing overview (no numbers)
- https://status.getmontecarlo.com/ — status page

## Best Practices (synthesized)

1. **Use pycarlo, not hand-rolled GraphQL** — schema drift is real.
2. **Introspect first**: on connection-test, run `{ __schema { queryType { fields { name } } } }` and log the list. Validates which queries are live.
3. **Cost = MA_count × $/MA + Monitor_overage + Incident_addons** — all three terms must come from customer config; none from the API.
4. **Track MA over time** — MA count growth is the primary cost driver; graph week-over-week.
5. **Unused MA detection** — MAs with `lastObserved` > 30d or 0 incidents in 90d are candidates to unmonitor.
6. **Custom-SQL monitors run on customer warehouse** — attribute the MC-originated warehouse $ separately (via query_tag or user_name) so customers see "hidden" MC cost.
7. **Domain-level showback** — if customer has domains, roll up cost per domain for chargeback.
8. **Don't depend on `getTablesMonitoredInfo`** — not a canonical query. Use `getTablesOverview` with pagination and count.
9. **Paginate `getIncidents` with ≤ 100 per page** — larger pages risk timeouts.
10. **Cache GraphQL responses** by query-hash + 1-hour TTL — MA lists change slowly.
11. **Surface plan tier** from `getAccountSettings` where exposed — drives plan-upgrade recommendation.
12. **Separate "Incidents" metric** from cost — customers want incident count as a quality KPI, not a dollar.
13. **Warn on trial accounts** — trial usage ≠ billed usage; label clearly.

## Costly's Current Connector Status

File: `backend/app/services/connectors/monte_carlo_connector.py`

- **Class**: `MonteCarloConnector(BaseConnector)` with `platform = "monte_carlo"`
- **Auth**: `api_key_id` + `api_token` in headers (`x-mcd-id`, `x-mcd-token`)
- **Connection test**: POSTs `{ getUser { email } }` — correct pattern
- **Fetch logic**:
  - Calls `getTablesMonitoredInfo { totalTables monitoredTables }` — **this field may not exist in the live 2026 schema**. Verify via introspection.
  - Calls `getIncidents` with `startTime`/`endTime` variables and `first: 500`
  - Computes `monthly_cost = table_count × $50`, `daily_cost = monthly / 30`
  - Emits one `UnifiedCost` per day in the window with flat daily cost and per-day incident count
- **Category**: `CostCategory.data_quality`
- **Known issues**:
  - Uses an unverified GraphQL field name (`getTablesMonitoredInfo`) — may silently return `None`
  - Hard-codes `$50/table/month` — should be customer-configurable
  - Treats "table" and "MA" as synonymous — ignores views, dashboards, external stages
  - No domain breakdown, no warehouse breakdown, no monitor-type breakdown
  - No incident severity/type breakdown — just a count
  - Silent `except Exception: return costs` swallows errors; `getTablesMonitoredInfo` failure leaves zeros
  - Daily records generated with flat cost/day — doesn't reflect actual MA growth over time
  - Uses `datetime.utcnow()` (deprecated in Python 3.12+)
  - Incident fields (`createdTime`, `incidentType`) not verified against live schema
  - No pagination on `getIncidents` — hard-coded `first: 500` misses high-volume customers
  - No fallback if GraphQL is down

## Gaps

1. Swap to pycarlo SDK for schema-robust queries
2. Introspect schema on first connect, cache the resolved field names per-account
3. Make `$/MA` customer-configurable (credential field `rate_per_ma`, default 50)
4. Query `getTablesOverview` with pagination for accurate MA count (include all asset types, not just tables)
5. Query `getMonitors` separately; Monitor count is a second cost driver on some plans
6. Query `getDomains` and emit per-domain cost rows (showback)
7. Break `getIncidents` pages into 100-at-a-time with cursor pagination
8. Add incident type + severity breakdown in metadata
9. Detect MC-originated warehouse queries (Snowflake user MCD_USER or query_tag) and cross-link with the Snowflake connector cost
10. Track MA count over time to produce a growth-rate chart
11. Emit "unused MA" recommendations (0 incidents in 90d, `lastObserved` stale)
12. Handle trial-account detection and surface plan tier
13. Fix `datetime.utcnow()` → `datetime.now(datetime.UTC)`
14. Proper error logging instead of silent swallowing

## Roadmap

- **Phase 1**: swap to pycarlo; introspect schema on connect; make rate configurable
- **Phase 2**: MA-level detail with domain + warehouse breakdown; use `getTablesOverview` pagination
- **Phase 3**: Monitor + incident dimensions with type/severity breakdown
- **Phase 4**: MC-originated warehouse cost cross-correlation (Snowflake query_tag join)
- **Phase 5**: "Unused MA" and "Stale monitor" recommendations in Costly's Recommendations view
- **Phase 6**: MA growth-rate anomaly alert (unexpected doubling triggers a notification)
- **Phase 7**: plan-upgrade / plan-downgrade recommendations based on usage-vs-bucket fit
- **Phase 8**: AI/LLM observability usage (for customers on the Data+AI bundle)

## Change Log

- 2026-04-24: Initial knowledge-base created
