# BigQuery — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

BigQuery is Costly's GCP warehouse connector — it pulls per-job cost from `INFORMATION_SCHEMA.JOBS_BY_PROJECT` (bytes-billed × on-demand rate) and storage from `INFORMATION_SCHEMA.TABLE_STORAGE`. The current implementation is the thinnest of the three warehouses: it is on-demand-pricing-only, single-region (`region-us` hard-coded), has no Editions / reservations / BI Engine / BigQuery ML / AI functions support, and never reads Cloud Billing export or `JOBS_BY_ORGANIZATION`. Grade today: **C (works for small on-demand shops, wrong for 80%+ of 2026 BigQuery customers who are on Editions).** Top gap: no Editions detection — on Autoscaling Editions, `bytes_billed × $6.25/TB` massively overcounts real spend because bytes-billed is zero for slot-reservation queries.

## Pricing Model (from vendor)

BigQuery in 2026 has two parallel compute models, plus a storage dimension and a growing list of AI/ML SKUs.

### On-demand (legacy default, still available)

- **Compute**: **$6.25 / TiB scanned** (bytes billed). First 1 TiB/month free per billing account.
- Old-school query pricing; billed per-query based on `bytes_billed` in `INFORMATION_SCHEMA.JOBS*`. 10 MB minimum per query. Flat ~$6.25/TiB in `US`/`EU` multi-region since 2023 price revision (was $5).
- **Regional deltas**: `asia-northeast1` $7.50, `europe-west3` $7.00, `us-central1` $6.25, `us-east1` $6.25. Regions vary ±10-30%. See https://cloud.google.com/bigquery/pricing#on_demand_pricing.

### Editions (introduced July 2023, default on new billing accounts as of October 2024)

Slot-based compute, billed per slot-hour. Three editions:

| Edition | $/slot-hour (pay-as-you-go) | 1-yr commitment | 3-yr commitment |
|---------|-----------------------------|------------------|-------------------|
| Standard | $0.04 | N/A (no commits) | N/A |
| Enterprise | $0.06 | $0.036 (40% off) | $0.024 (60% off) |
| Enterprise Plus | $0.10 | $0.06 (40% off) | $0.04 (60% off) |

- **Standard Edition**: basic workloads, no commitments, no BI Engine, no column-level security, no customer-managed encryption keys (CMEK).
- **Enterprise Edition**: adds column-level security, CMEK, private-endpoint, materialized views, authorized routines.
- **Enterprise Plus**: adds disaster-recovery with cross-region replication, multi-region support for secured datasets.
- **Autoscaling**: default on Editions; scales between `baseline_slots` and `max_slots`. Baseline = 0 allowed (pure autoscale).
- **Commitments**: 1-year and 3-year commitments lock a baseline; overage billed at pay-as-you-go Edition rate.
- Regional deltas: Enterprise is $0.07 in `asia-northeast1`, $0.065 in `europe-west3`, $0.06 in `us-central1`.

### Storage

| Type | Price (USD/GiB/month) |
|------|-----------------------|
| Active logical storage | $0.02 |
| Long-term logical storage (>90 days unchanged) | $0.01 |
| Active physical storage (compressed, opt-in) | $0.04 |
| Long-term physical storage | $0.02 |
| Time travel (7 days default, up to 7 days) | included in storage (billed as long-term after TT expires) |
| Fail-safe (additional 7 days) | included in storage |

- **Physical vs logical**: opt-in via `ALTER SCHEMA SET OPTIONS (storage_billing_model = 'PHYSICAL')`. Typical savings 20-60% for highly compressible data (JSON/strings), neutral or negative for dense numeric.
- **First 10 GiB/month free** per billing account.
- **Regional deltas**: ±10-20%.

### Streaming + loads

- **Streaming inserts (legacy tabledata.insertAll)**: $0.010 per 200 MiB.
- **Storage Write API**: $0.025 per GiB (default), $0.040 with exactly-once semantics.
- **Batch loads, exports, copy jobs**: free (but quota-limited).

### BigQuery BI Engine (in-memory accelerator)

- $0.0416 per GiB-hour reserved capacity.
- Typical config: 10-100 GiB reservation, only useful for Looker Studio / Connected Sheets / Looker.
- Billed via `INFORMATION_SCHEMA.BI_ENGINE_USAGE_HISTORY`.

### BigQuery ML

- **Built-in models** (linear, logistic, K-means, time series, boosted trees, AutoML Tables, DNN): billed at the standard compute rate (on-demand bytes or Editions slots).
- **ARIMA/time-series training**: $250 per model + compute.
- **External models (Vertex AI calls)**: billed by Vertex AI separately.
- **Remote models / GENERATE_TEXT** via Vertex AI: per-character or per-token Vertex prices (Gemini 2.5 Flash ~$0.15/M input tokens at time of writing).
- **Vector search** (`CREATE VECTOR INDEX`, `VECTOR_SEARCH`): $200 per TB indexed + compute.

### Cloud Data Transfer Service

- $0.30 per TB for scheduled transfers.

### Omni (cross-cloud BQ)

- Different rates per source cloud; AWS S3 via Omni: ~$7.50/TB scanned; Azure Blob: ~$9.50/TB.

### Commitments / EDPs

- **Editions commitments**: 1-yr = 40% off, 3-yr = 60% off; baseline slots only, overage is pay-as-you-go.
- **Enterprise Agreement / Committed Use Discount (CUD)**: Google Cloud enterprise-wide agreement; typical 15-30% discount on Editions if signed at the CUD level.
- **Google Cloud Marketplace Private Offer**: bespoke pricing; requires AE involvement.

Sources:
- https://cloud.google.com/bigquery/pricing
- https://cloud.google.com/bigquery/docs/editions-intro
- https://cloud.google.com/bigquery/docs/reservations-intro
- https://cloud.google.com/bigquery/docs/storage_pricing
- https://cloud.google.com/bigquery/docs/bi-engine-intro
- https://cloud.google.com/bigquery-ml/pricing
- https://cloud.google.com/blog/products/data-analytics/introducing-new-bigquery-pricing-editions

## Billing / Usage Data Sources

### Primary

**Cloud Billing BigQuery export** — canonical source for actual billed USD. Requires enabling the `detailed usage cost` export to BigQuery, typically writes to `project_id.billing_export.gcp_billing_export_resource_v1_<ID>`.

```sql
SELECT
  usage_start_time::DATE AS day,
  project.id             AS project_id,
  service.description    AS service,
  sku.description        AS sku,
  SUM(cost)              AS cost_usd,
  SUM(usage.amount)      AS usage_amount,
  ANY_VALUE(usage.unit)  AS usage_unit,
  SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS credits_usd
FROM `PROJECT.billing_export.gcp_billing_export_resource_v1_BILLING_ACCOUNT_ID`
WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL :days DAY)
  AND service.description = 'BigQuery'
GROUP BY 1,2,3,4
ORDER BY 1;
```

Latency: up to 24 h for final values (retroactive corrections can trickle in for 72 h).

Permissions: requires `billing_export` table grant (`roles/bigquery.dataViewer` on the export dataset) + knowledge of the billing account ID. Customers must enable the export; it is not on by default.

**`INFORMATION_SCHEMA.JOBS_BY_PROJECT`** — per-job metadata for the project the service account is in; no org/folder rollup.

```sql
SELECT
  DATE(creation_time)        AS day,
  project_id,
  user_email,
  reservation_id,
  job_type,
  statement_type,
  cache_hit,
  total_bytes_billed,
  total_bytes_processed,
  total_slot_ms,
  query_info.query_hashes.normalized_literals AS query_hash,
  labels
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL :days DAY)
  AND state = 'DONE';
```

Permissions: `bigquery.jobs.listAll` + `bigquery.resourceViewer`. Latency: 3-5 min.

**`INFORMATION_SCHEMA.JOBS_BY_ORGANIZATION`** — org-wide job metadata (requires `roles/bigquery.resourceAdmin` at the org level). Best source for multi-project fleets.

**`INFORMATION_SCHEMA.JOBS_TIMELINE_BY_PROJECT`** — per-second slot utilization (for queue-depth / autoscaling analysis).

**`INFORMATION_SCHEMA.RESERVATIONS_TIMELINE`** — slot reservations per second.

**`INFORMATION_SCHEMA.RESERVATION_CHANGES`** — reservation config diffs.

**`INFORMATION_SCHEMA.ASSIGNMENTS`** — which projects / folders / orgs are assigned to which reservations.

**`INFORMATION_SCHEMA.TABLE_STORAGE`** / **`INFORMATION_SCHEMA.TABLE_STORAGE_USAGE_TIMELINE_BY_PROJECT`** — active vs long-term storage, logical vs physical bytes, per-table daily history (up to 180 days).

**`INFORMATION_SCHEMA.STREAMING_TIMELINE_BY_PROJECT`** — streaming ingestion bytes.

**`INFORMATION_SCHEMA.BI_ENGINE_STATISTICS_BY_PROJECT`** — BI Engine acceleration rates.

**`INFORMATION_SCHEMA.ML_PROCESSED_INPUT_ROWS_BY_PROJECT`** — BQML training cost proxy.

### Secondary / Fallback

- **GCP Cost Management / Billing Console** — readable via Cloud Billing API v1 (`services/6F81-5844-456A`).
- **Cloud Monitoring** — `bigquery.googleapis.com/` metrics (slots_used, bytes_scanned). Useful for live alerting but not for cost.
- **FinOps Hub** — Google's native console (https://console.cloud.google.com/bigquery/admin/finops-hub). Includes recommendations but not a programmatic API.
- **BigQuery Recommender (Active Assist)** — https://cloud.google.com/recommender/docs/recommenders#bigquery. Emits "idle capacity", "overprovisioned reservation", "partitioning opportunity" recommendations via API.
- **Asset Inventory** for reservation/assignment discovery.
- **Legacy per-project billing CSV export** (deprecated Aug 2024).

### Gotchas

- **Editions vs on-demand**: On Editions (slot-based), `total_bytes_billed` is `NULL` or zero in `JOBS_BY_PROJECT` — queries are billed by reservation, not bytes. Multiplying 0 × $6.25/TB gives $0, drastically underreporting cost. Costly's current formula is wrong for Editions customers.
- **Region encoding**: `region-us` in SQL ≠ `us-central1`. The multi-region `US` covers all US regions. Customers in `eu` vs `europe-west3` see different INFORMATION_SCHEMA datasets. Our hard-coded `region-us` breaks everything non-US.
- **`JOBS` vs `JOBS_BY_PROJECT` vs `JOBS_BY_USER` vs `JOBS_BY_FOLDER` vs `JOBS_BY_ORGANIZATION`**: Different row visibility + different permissions. `JOBS_BY_PROJECT` is most accessible but only covers the project the query runs in.
- **Cache hits are free**: `cache_hit = true` ⇒ cost 0; still shows `total_bytes_processed`. Must filter.
- **Script jobs** (`statement_type = 'SCRIPT'`) are parents of child statements; their `total_bytes_billed` is the sum of children. Double-counting risk if both are included.
- **Dry-run jobs** have `dry_run=true` and zero cost but may appear with `total_bytes_processed > 0`.
- **Load/copy/export jobs** are free but show up in JOBS. Filter by `job_type = 'QUERY'`.
- **Slot-ms on-demand**: shown in JOBS but doesn't reflect cost under on-demand.
- **Multi-region storage vs regional storage**: `US` multi-region is slightly more expensive than a single region (~+15%); replication cost is borne by Google.
- **BI Engine**: reservation billed per-hour even when idle; not captured in JOBS_* views — needs `BI_ENGINE_USAGE_HISTORY`.
- **ML cost**: BQML training bills under slot-hours or on-demand, but Vertex AI remote calls bill externally — must join with Vertex billing export.
- **Physical storage datasets**: a mixed schema (some datasets physical, some logical) makes flat cost calculation error-prone; always query `TABLE_STORAGE.storage_billing_model` first.
- **Latency**: Cloud Billing export can be hours behind; `INFORMATION_SCHEMA.JOBS*` is ~3-5 min.
- **First 1 TiB/month free** applies at the billing-account level on on-demand. Summing raw `bytes_billed × $6.25/TB` includes the free tier; only `Cloud Billing export` already accounts for it.
- **Streaming insert quota pricing** (legacy): $0.010/200 MiB; Storage Write API has a different rate sheet.
- **Flex slots (deprecated)**: still billed on a small number of legacy accounts; look in `RESERVATIONS` for `edition IS NULL`.
- **Cross-project billing**: queries can run in one project but scan tables in another; `JOBS_BY_PROJECT` only shows the former.
- **Regional INFORMATION_SCHEMA**: each region has its own copy; pull multiple regions if customer is multi-region.

## Schema / Fields Available

### `INFORMATION_SCHEMA.JOBS_BY_PROJECT` (core)

| Column | Type | Notes |
|--------|------|-------|
| `creation_time`, `start_time`, `end_time` | TIMESTAMP | |
| `project_id`, `project_number` | STRING/INT | |
| `user_email` | STRING | SA or user |
| `job_id` | STRING | |
| `job_type` | STRING | QUERY, LOAD, EXPORT, COPY |
| `statement_type` | STRING | SELECT, INSERT, CREATE_TABLE_AS_SELECT, SCRIPT |
| `priority` | STRING | INTERACTIVE, BATCH |
| `state` | STRING | DONE / PENDING / RUNNING |
| `error_result` | RECORD | Last error |
| `cache_hit` | BOOL | Free if true |
| `total_slot_ms` | INT64 | Slot-ms across job lifetime |
| `total_bytes_processed` | INT64 | Bytes read (on-demand reference) |
| `total_bytes_billed` | INT64 | Billable bytes; 0 under Editions |
| `reservation_id` | STRING | `<project>:<region>.<reservation>` when Editions |
| `edition` | STRING | `STANDARD` / `ENTERPRISE` / `ENTERPRISE_PLUS` |
| `destination_table` | RECORD | |
| `referenced_tables` | RECORD[] | |
| `labels` | RECORD[] (ARRAY<STRUCT<key, value>>) | Key attribution vector |
| `query_info.query_hashes.normalized_literals` | STRING | Hash grouping |
| `timeline` | RECORD[] | Per-second timeline (slot_ms, queued) |
| `total_modified_partitions` | INT64 | DML writes |

### `INFORMATION_SCHEMA.TABLE_STORAGE`

| Column | Type | Notes |
|--------|------|-------|
| `project_id`, `table_schema`, `table_name` | STRING | |
| `creation_time`, `storage_last_modified_time` | TIMESTAMP | |
| `total_rows`, `total_partitions` | INT64 | |
| `total_logical_bytes`, `active_logical_bytes`, `long_term_logical_bytes` | INT64 | |
| `total_physical_bytes`, `active_physical_bytes`, `long_term_physical_bytes`, `time_travel_physical_bytes`, `fail_safe_physical_bytes` | INT64 | |
| `storage_billing_model` | STRING | LOGICAL / PHYSICAL |

### `INFORMATION_SCHEMA.RESERVATIONS`

| Column | Notes |
|--------|-------|
| `reservation_name`, `project_id`, `edition`, `slot_capacity`, `ignore_idle_slots`, `autoscale` RECORD (max_slots, current_slots), `concurrency`, `creation_time` |

### `INFORMATION_SCHEMA.ASSIGNMENTS`

| Column | Notes |
|--------|-------|
| `reservation_name`, `job_type` (PIPELINE / QUERY / CONTINUOUS), `assignee_type`, `assignee_id` |

### Cloud Billing Export

| Column | Notes |
|--------|-------|
| `billing_account_id`, `service`, `sku`, `usage_start_time`, `usage_end_time`, `project.*`, `labels`, `cost`, `currency`, `usage.amount`, `usage.unit`, `credits`, `invoice.month`, `cost_type`, `export_time` |

## Grouping Dimensions

- **Project** (`project_id`) — primary GCP billing unit.
- **Folder / Organization** — up-stack from project.
- **User** (`user_email`) — includes service accounts.
- **Reservation** (`reservation_id`) — slot reservation; groups Edition spend.
- **Job type** — QUERY, LOAD, EXPORT, COPY (most ignored for cost; only QUERY bills).
- **Statement type** — SELECT vs DML; useful to split read vs write.
- **Labels** — custom key-value on queries, tables, datasets (`bq query --label=team:analytics`) — best attribution dimension when customer has label discipline.
- **Dataset / Table** — per-object storage, query-referenced tables for scan attribution.
- **Region** — multi-region vs regional pricing deltas.
- **SKU** (from Cloud Billing export) — canonical split of compute vs streaming vs BI engine vs ML vs storage.
- **Edition** — STANDARD / ENTERPRISE / ENTERPRISE_PLUS rate differential.
- **Query hash** — `query_info.query_hashes.normalized_literals` — for query-level roll-up across parameterized runs.

## Open-Source Tools Tracking This Platform

| Project | URL | Stars | License | Data source | What it does |
|---------|-----|-------|---------|-------------|--------------|
| **bigquery-utils** (Google Cloud) | https://github.com/GoogleCloudPlatform/bigquery-utils | ~1K | Apache 2.0 | INFO_SCHEMA | Official community helpers: partition detectors, UDFs, cost queries. |
| **bq-pipelines** (CARTO) | https://github.com/CartoDB/carto-analytics-toolbox-bigquery | ~220 | BSD | Various | BQ tile functions for geospatial + admin queries. |
| **BigQuery Admin Resource Center** | https://cloud.google.com/bigquery/docs/admin-intro | — | — | INFO_SCHEMA | Canonical admin dashboards + reference queries. |
| **dbt-bigquery** | https://github.com/dbt-labs/dbt-bigquery | ~870 | Apache 2.0 | — | dbt adapter; includes cost-aware materialization helpers. |
| **dbt_artifacts (Brooklyn Data)** | https://github.com/brooklyn-data/dbt_artifacts | ~320 | Apache 2.0 | dbt artifact tables | Run history with BQ-specific cost fields. |
| **dbt-bigquery-monitoring** | https://github.com/kents00/dbt-bigquery-monitoring | ~90 | MIT | INFO_SCHEMA | Community dbt package modelled on Select's Snowflake package — daily spend, per-reservation, per-user. |
| **bq-cost-estimator** (Google) | https://cloud.google.com/bigquery/docs/estimate-costs | — | — | DRY_RUN API | Estimates cost for a given query via dry-run. |
| **BigQuery FinOps Starter (Looker Studio)** | https://cloud.google.com/blog/products/data-analytics/finops-for-bigquery-with-looker-studio | — | — | Cloud Billing + INFO_SCHEMA | Free Looker Studio template dashboards. |
| **bq-slot-utilization** | https://github.com/GoogleCloudPlatform/bigquery-reservation-toolkit | ~120 | Apache 2.0 | RESERVATIONS_TIMELINE | Reservation sizing + autoscaling tuning. |
| **bigquery-job-anomaly-detector** | https://github.com/GoogleCloudPlatform/bigquery-anomaly-detection | — | Apache 2.0 | JOBS | Detects cost spikes per user/label. |
| **Google FinOps Hub** | https://console.cloud.google.com/bigquery/admin/finops-hub | — | — | Billing + INFO_SCHEMA | Native Google FinOps view; source of many ideas. |
| **Looker Reservations Monitoring Block** | LookerML marketplace | — | — | JOBS + RESERVATIONS | Paid, but structure is public. |
| **bq_partition_metadata** | https://github.com/googleapis/python-bigquery | ~750 | Apache 2.0 | — | Python SDK with cost-estimation helpers. |

## How Competitors Handle This Platform

### Vantage (https://vantage.sh)

- Includes a BigQuery tile; pulls Cloud Billing export; provides per-project, per-service, per-label roll-ups. Not deep on reservations / slot-utilization. Mid-tier.

### CloudZero (https://cloudzero.com)

- Ingests Cloud Billing export, lets you allocate BigQuery costs to business units via labels. Weak on job-level drill-down.

### Google Cloud FinOps Hub

- Native, free, powerful. Covers: top projects, top jobs, reservation utilization, capacity recommendations, partitioning recommendations. Limited customization, no multi-cloud.

### dbt Cloud native cost insights

- Shows dbt-invocation-level cost by joining dbt run metadata with BigQuery JOBS via invocation-id labels. Requires dbt Cloud; covers only dbt workloads.

### Looker cost dashboards (Google Marketplace)

- Free Looker Studio templates modelled on the FinOps Hub; flexible if customer has Looker.

### Revefi (https://revefi.com)

- Unified SF/DBX/BQ; for BQ specifically, does per-job anomaly detection and per-label attribution. Opens GitHub PRs against dbt repos for optimization.

### Unravel (https://unravel.io)

- BQ coverage is slot-utilization focused; recommends reservation sizing; weaker on DML and ML cost lines.

### Carto BigQuery Analytics Toolbox

- Not a cost tool but often cited; includes admin tiles for query cost.

### Finout (https://finout.io)

- Virtual tagging via labels; strong if customer labels discipline is consistent.

### Keebo

- Expanding beyond Snowflake to BigQuery in 2025; beta product for autoscaling slot tuning.

### Chaos Genius

- Limited BQ support; Snowflake-first OSS but ingests billing export.

## Books / Published Material / FinOps Literature

- **"BigQuery: The Definitive Guide"** (O'Reilly, 2nd ed 2024) — Valliappa Lakshmanan, Jordan Tigani. Chapter 9 covers pricing + optimization; pre-Editions but principles still valid.
- **"Data Science on the Google Cloud Platform"** (O'Reilly, 2nd ed 2023) — Lakshmanan.
- **"Google BigQuery Cost Optimization Guide"** — https://cloud.google.com/bigquery/docs/best-practices-costs. Official.
- **"Introduction to BigQuery Editions and Reservations"** — https://cloud.google.com/bigquery/docs/editions-intro.
- **Google Cloud FinOps blog series** — https://cloud.google.com/blog/topics/financial-services/finops-on-gcp (several BigQuery-specific posts 2024-2025).
- **BigQuery Admin Reference Guide** (free Google ebook, 2024).
- **FinOps Foundation — BigQuery playbook** (community contribution) — https://www.finops.org/wg/bigquery.
- **Cloud FinOps** (2nd ed, O'Reilly, 2023) — Storment + Fuller — BigQuery case studies in Ch. 13.
- **Google Data Cloud Summit** (annual, April) — sessions on Editions cost optimization, slot autoscaling, BI Engine ROI.
- **Felipe Hoffa's blog** (former Google DA): https://hoffa.medium.com — BigQuery query-optimization posts.
- **Jordan Tigani's blog** (former BQ co-founder; now MotherDuck CEO): https://motherduck.com/blog — contrarian takes on BQ cost.
- **Paul Brebner's Instaclustr posts** on BQ cost modeling.
- **Forrest Brazeal** — cost-optimization humor + content.

## Vendor Documentation Crawl

- **Pricing overview**: https://cloud.google.com/bigquery/pricing
- **Editions pricing**: https://cloud.google.com/bigquery/pricing#bqml-pricing (also covers reservations)
- **Storage pricing**: https://cloud.google.com/bigquery/pricing#storage
- **On-demand analysis**: https://cloud.google.com/bigquery/pricing#analysis_pricing_models
- **Streaming inserts**: https://cloud.google.com/bigquery/pricing#streaming-pricing
- **BI Engine pricing**: https://cloud.google.com/bigquery/pricing#bi_engine_pricing
- **BQML pricing**: https://cloud.google.com/bigquery-ml/pricing
- **Editions intro**: https://cloud.google.com/bigquery/docs/editions-intro
- **Reservations intro**: https://cloud.google.com/bigquery/docs/reservations-intro
- **Slot autoscaling**: https://cloud.google.com/bigquery/docs/reservations-autoscaling
- **Storage billing model**: https://cloud.google.com/bigquery/docs/information-schema-table-storage-usage
- **Cost controls**: https://cloud.google.com/bigquery/docs/custom-quotas
- **Cost optimization best practices**: https://cloud.google.com/bigquery/docs/best-practices-costs
- **Release notes (2025)**: https://cloud.google.com/bigquery/docs/release-notes
- **Release notes (2026)**: https://cloud.google.com/bigquery/docs/release-notes#2026
- **INFO_SCHEMA.JOBS*** reference: https://cloud.google.com/bigquery/docs/information-schema-jobs
- **INFO_SCHEMA.TABLE_STORAGE**: https://cloud.google.com/bigquery/docs/information-schema-table-storage
- **FinOps Hub**: https://console.cloud.google.com/bigquery/admin/finops-hub
- **Cloud Billing export schema**: https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables

Notable 2025-2026 changes:
- **Oct 2024**: Editions became default for new billing accounts.
- **Feb 2025**: Storage Write API pricing revised downward by 15%.
- **Jun 2025**: Continuous queries GA — new SKU for real-time materialized pipelines.
- **Sep 2025**: BigQuery Studio Data Preparation GA — billed at Editions slot rate (was free preview).
- **Nov 2025**: Vertex AI ↔ BigQuery remote models now surface in JOBS with `model_type` field.
- **Jan 2026**: Data Governance + Column-level masking now bills under Enterprise Plus slot rate.
- **Mar 2026**: Slot autoscaling SLO improved — scale-down delay reduced from 60s to 30s.
- **Apr 2026**: Vector Search GA moved from separate SKU to compute + $200/TB index; reservation utilization now visible in RESERVATIONS_TIMELINE.

## Best Practices (synthesized)

1. **Prefer Cloud Billing export** over `INFORMATION_SCHEMA.JOBS_*` when total USD accuracy matters (especially on Editions). Use JOBS for *attribution* (user, label, query, bytes).
2. **Detect Editions**: if `reservation_id` is not null on JOBS rows → Editions; don't apply on-demand bytes math. Instead cost = `total_slot_ms / 3.6e6 × edition_rate`.
3. **Partition + cluster every large table**: reduce `bytes_billed` by 80-95%. Biggest single lever on on-demand.
4. **Enable `require_partition_filter = true`** on wide tables so unpartitioned scans are forbidden.
5. **Convert to physical storage billing** for tables with high compression ratio (check `active_logical_bytes / active_physical_bytes > 2.5`).
6. **Lower time-travel** to 2 days on staging datasets (default 7).
7. **Move old tables to long-term storage** by stopping writes — automatic after 90 days of immutability, 50% cheaper.
8. **Use BI Engine** only when Looker/Connected-Sheets concurrency > 10 interactive users; otherwise reservation waste.
9. **Right-size reservations** using `RESERVATIONS_TIMELINE`: if p95 utilization < 50% for 14 days, shrink baseline.
10. **Use autoscale with baseline 0** for bursty pipelines; reserve baseline for predictable workloads.
11. **Attach labels to every job** via dbt profile / Airflow operator / bq command (`--label=team:fin,env:prod`). Without labels, attribution is limited to user_email.
12. **Cache hits are free** — make sure cache is enabled (default) and session roles are stable (cache keyed on user+query).
13. **Avoid `SELECT *`** — always project columns; BQ is columnar.
14. **Materialized views** for high-frequency aggregations — BQ maintains them incrementally.
15. **Cost controls**: per-project quotas (`custom quotas`) and Budgets with Pub/Sub alerts.
16. **BQML remote calls**: batch, cache, use cheapest model that meets quality bar.
17. **Script jobs**: de-dupe to avoid counting parent + children in rollups.
18. **Audit dry-runs**: if dry-run cost estimate > threshold, block the run via authorization check.

## Costly's Current Connector Status

Source: `backend/app/services/connectors/bigquery_connector.py` (~250 lines; minimal).

**Implemented:**
- `_get_access_token()`: OAuth2 via service account JSON. Falls back from `google.auth` SDK to manual JWT flow.
- `test_connection()`: Lists datasets via `/bigquery/v2/projects/<id>/datasets`.
- `fetch_costs()`: Queries `region-us.INFORMATION_SCHEMA.JOBS`, aggregates per day/user/project, multiplies `bytes_billed` by `BQ_COST_PER_TB = $6.25`.
- `_fetch_storage_costs()`: Queries `region-us.INFORMATION_SCHEMA.TABLE_STORAGE`, uses `$0.02/GB/month` for logical active storage (1/30th daily).
- Category mapping: `compute` for query, `storage` for storage.

**Not implemented:**
- **Cloud Billing export** — the canonical USD source. Completely absent.
- **Editions / reservations** detection. Always assumes on-demand.
- `JOBS_BY_ORGANIZATION` / `JOBS_BY_FOLDER`.
- Multi-region support — hard-coded `region-us`.
- Statement-type filter — currently only filters `state=DONE AND statement_type IS NOT NULL`, which includes LOAD/COPY/EXPORT (which are free but muddy attribution).
- Cache-hit filter — cache-hit jobs are billed at $0; currently included.
- Script de-dup (parent-child double count).
- BI Engine, BQML, Continuous Queries, Storage Write API, Streaming, Data Preparation, Vector Search, Omni.
- Reservations sizing / slot utilization from `RESERVATIONS_TIMELINE` / `JOBS_TIMELINE_BY_PROJECT`.
- Per-label attribution (labels column ignored).
- Long-term vs active storage split.
- Physical vs logical storage model detection.
- Per-region pricing deltas.
- Per-edition pricing.
- Recommender API (Active Assist) integration.
- `user=` resource format is `project/user`; should be per-user with labels as richer dimension.

**Grade: C.** Fine for a toy BQ project on pure on-demand; wrong for any customer on Editions (which is now the default). Storage math ignores long-term vs active and physical vs logical.

## Gaps Relative to Best Practice

1. **Editions blindness** — the #1 bug. Any customer on Enterprise Edition has `total_bytes_billed = 0` for all slot-reservation queries; connector reports $0.
2. **No Cloud Billing export ingestion**, so we never see actual billed USD.
3. **Hard-coded `region-us`** — single-region only.
4. **No labels** — no attribution beyond user_email.
5. **No reservation detail** — cannot recommend right-sizing.
6. **No slot-utilization** — cannot recommend autoscale tuning.
7. **No long-term / physical storage split** — always assumes active-logical.
8. **No cache-hit / dry-run filter** — potential noise.
9. **No statement-type filter** — LOAD/COPY/EXPORT muddy compute line.
10. **No BI Engine / BQML / streaming / vector search / Omni / continuous-query coverage.**
11. **No per-region pricing deltas** — us pricing applied globally.
12. **No commit discount handling** — 1-yr / 3-yr commitments underfactored.
13. **No Recommender API** integration.
14. **No multi-project or org-level rollup** — the service account's `project_id` is all we see.
15. **No data freshness** signal — user doesn't see the 24-h billing-export lag.
16. **No rate-limit / retry / pagination** on the REST query endpoint; a 10K-row response will crash silently.
17. **Synchronous `httpx`** in an async context — blocks the event loop.

## Roadmap

### Near-term (next 2 weeks)

- Add Editions detection: if `reservation_id IS NOT NULL` on any jobs, pivot the cost formula to `total_slot_ms / 3.6e6 × edition_rate_usd`.
- Parameterize region: multi-region datasets (`US`, `EU`) + explicit regional (`us-central1`, `europe-west3`, etc.) via credentials dict.
- Add label extraction + group-by labels in the output.
- Add cache-hit + script + load/copy/export filters.
- Add long-term vs active storage split and support `PHYSICAL` storage billing.

### Medium-term (next 4-6 weeks)

- Cloud Billing export ingestion as primary path when customer provides export dataset ID. INFORMATION_SCHEMA becomes the enrichment layer.
- `JOBS_BY_ORGANIZATION` for multi-project rollup.
- Reservations + assignments + timeline for sizing recommendations.
- BI Engine, BQML, Streaming, Storage Write API, Continuous Queries coverage (via Cloud Billing export SKUs).
- Active Assist / Recommender API integration for native optimization hints.
- Region-aware default pricing.
- Per-edition rate table.
- Data freshness badge.

### Long-term (2-3 months)

- Slot autoscaling recommendation engine (input: `RESERVATIONS_TIMELINE` + `JOBS_TIMELINE`).
- Partition-filter + clustering opportunity detection (from `information_schema.table_options` + JOBS referenced_tables).
- Unit-economics: cost per dbt model, per Looker dashboard, per user, per tenant (via labels).
- Write-back actions: approved PATCH `reservations.patch` to resize baseline; `ALTER SCHEMA SET OPTIONS (storage_billing_model='PHYSICAL')`.
- Vertex AI cost join for BQML remote model charges.
- "BigQuery Expert" agent (per `costly-expert-agents.md`).
- dbt-bigquery-monitoring package integration — either invoke on customer side or replicate models in Costly.

## Change Log

- 2026-04-24: Initial knowledge-base created by overnight research run.
