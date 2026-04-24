# Snowflake — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Snowflake is the canonical cost target for Costly and the most battle-tested of our warehouse connectors: it pulls compute + serverless + storage from `ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` (the already-billed-USD view) with automatic fallback to `ACCOUNT_USAGE.METERING_DAILY_HISTORY`, plus Cortex AI, nine serverless credit lines, and per-user/role/query-tag attribution via `QUERY_ATTRIBUTION_HISTORY`. Grade today: **B+ (strong compute coverage, weak query-cost-to-table drill-down and zero support for AI Budgets / Gen-2 warehouses / Iceberg egress).** Top gap: we do not yet pull `WAREHOUSE_LOAD_HISTORY`, `QUERY_HISTORY` (query-level USD), or the new `AI_SERVICES_USAGE_HISTORY` view that GA'd April 2026 with the AI Budgets framework.

## Pricing Model (from vendor)

Snowflake prices compute and storage separately, with serverless lines layered on top. All values below reflect the **April 2026 on-demand list** — capacity contracts and Enterprise/Premier Support deals routinely discount 10-45%.

### Compute credits (per-hour credit consumption for virtual warehouses)

| Size | Credits/hour | Nodes |
|------|--------------|-------|
| XS | 1 | 1 |
| S | 2 | 2 |
| M | 4 | 4 |
| L | 8 | 8 |
| XL | 16 | 16 |
| 2XL | 32 | 32 |
| 3XL | 64 | 64 |
| 4XL | 128 | 128 |
| 5XL | 256 | 256 |
| 6XL | 512 | 512 |

Snowpark-optimized warehouses (memory-heavy) use **1.5× credits** at each size. "Gen-2" standard warehouses (GA March 2025, now default on new accounts) bill at the same credit rate but deliver roughly 2.1× per-dollar performance on TPC-DS-style workloads per Snowflake's published benchmarks (https://www.snowflake.com/blog/introducing-snowflake-generation-2-standard-warehouses/). Gen-2 warehouses do not show up in a separate view — detection is via `WAREHOUSES.RESOURCE_CONSTRAINT='STANDARD_GEN_2'`.

### Credit prices (USD/credit) — on-demand April 2026

| Edition | AWS us-east-1 | AWS eu-west-1 | Azure East US 2 | GCP us-central1 | AWS us-gov-west-1 |
|---------|---------------|---------------|-----------------|-----------------|-------------------|
| Standard | $2.00 | $2.60 | $2.25 | $2.10 | $3.10 |
| Enterprise | $3.00 | $3.90 | $3.70 | $3.30 | $4.70 |
| Business Critical | $4.00 | $5.20 | $4.95 | $4.40 | $6.25 |
| VPS | by quote | by quote | by quote | by quote | $6.25 |

Capacity (pre-purchased) customers typically pay $1.40-$2.70 on Enterprise depending on commit size ($100K-$10M). Tier-1 accounts with EDPs (Enterprise Discount Programs, 3-year commits > $5M) have been quoted as low as **~$1.10/credit Enterprise**.

### Storage (per TB/month)

| Type | On-demand | Capacity (typical) |
|------|-----------|---------------------|
| Active + Time-Travel + Fail-Safe (unified) | $23.00 (AWS US, GCP US) | $20.00 |
| Active + TT + FS (Azure, EU regions) | $25.00-$46.00 | $22.00-$40.00 |

Snowflake does **not** bill TT/FS separately — they share the active-storage per-TB price — but `DATABASE_STORAGE_USAGE_HISTORY` splits active vs failsafe bytes and `TABLE_STORAGE_METRICS` exposes time-travel bytes, so Costly can surface them as separate spend lines for optimization recommendations.

Hybrid tables (Unistore, GA June 2025) have a **separate storage SKU at ~$250-400/TB/month** billed via `HYBRID_TABLE_STORAGE` in `USAGE_IN_CURRENCY_DAILY`. Iceberg tables billed at $23/TB on external storage when using Snowflake-managed catalog; no storage charge for externally-managed catalogs (customer pays S3/GCS/Azure directly).

### Serverless credit lines (billed in credits at warehouse credit rate unless noted)

| SKU | Rate | View |
|-----|------|------|
| Serverless Tasks | 1.2× compute credits | `SERVERLESS_TASK_HISTORY` |
| Snowpipe (file) | 0.06 credits per 1K files + per-second compute | `PIPE_USAGE_HISTORY` |
| Snowpipe Streaming (rowset) | 0.01 credits per 1K rows + per-hour client | `SNOWPIPE_STREAMING_CLIENT_HISTORY` |
| Automatic Clustering | actual compute credits | `AUTOMATIC_CLUSTERING_HISTORY` |
| Materialized View Refresh | 1.0× compute credits | `MATERIALIZED_VIEW_REFRESH_HISTORY` |
| Search Optimization | build + maintain credits | `SEARCH_OPTIMIZATION_HISTORY` |
| Replication (DB + failover) | 1.0× compute credits + per-GB egress | `REPLICATION_USAGE_HISTORY`, `REPLICATION_GROUP_USAGE_HISTORY` |
| Query Acceleration Service | 1.0× compute credits | `QUERY_ACCELERATION_HISTORY` |
| Cortex LLM Functions (COMPLETE/EMBED/TRANSLATE/SENTIMENT) | token credits, e.g. llama3-70b 0.4 credits/M input tokens, 1.2 credits/M output tokens | `CORTEX_FUNCTIONS_USAGE_HISTORY` |
| Cortex Analyst | per-message credits (~0.67 credits/message) | `CORTEX_ANALYST_USAGE_HISTORY` |
| Cortex Search (serving) | 1.0× compute + credits-per-query | `CORTEX_SEARCH_SERVING_USAGE_HISTORY` |
| Document AI | per-page credits | `DOCUMENT_AI_USAGE_HISTORY` |
| Snowflake ML Feature Store / Model Registry | compute credits + storage | `ML_FEATURE_STORE_USAGE_HISTORY` |
| Snowpark Container Services | SPCS service credits (per node type) | `SNOWPARK_CONTAINER_SERVICES_HISTORY` |
| Event Tables / Logging | 0.5 credits/GB ingested | `EVENT_USAGE_HISTORY` |
| Data Transfer (egress) | $0.02-$0.12/GB by region | `DATA_TRANSFER_HISTORY` |
| Iceberg external volume requests | per-request at storage-provider rate | `ICEBERG_TABLE_REQUESTS_HISTORY` (preview → GA Q1 2026) |

### Cloud Services allowance

10% of daily compute credits are free — billed as `CREDITS_USED_CLOUD_SERVICES + CREDITS_ADJUSTMENT_CLOUD_SERVICES` (the adjustment is negative up to the 10% cap). `USAGE_IN_CURRENCY_DAILY` already nets this out; `METERING_DAILY_HISTORY` requires manual adjustment. Costly's connector handles both paths.

### Commitments, discounts, EDPs

- **On-demand**: Pay monthly, highest per-unit cost.
- **Capacity**: Annual commitment ($50K-$10M+), 15-40% discount, credits roll forward only if not expired.
- **Enterprise Discount Program (EDP)**: 3-year, $5M+ TCV, 30-50% discount. Includes Priority Support.
- **Premier Support** flat fee for 24/7 response.
- **Regional deltas**: AWS US cheapest, AWS GovCloud 55% premium, Azure 10-25% premium in Europe, GCP close to AWS.
- **Edition premium**: Enterprise adds ~50% over Standard, Business Critical adds ~33% over Enterprise (HIPAA/PCI posture), VPS (Virtual Private Snowflake) is priced by quote.

Sources:
- https://www.snowflake.com/pricing/
- https://www.snowflake.com/pricing/pricing-guide/
- https://docs.snowflake.com/en/user-guide/admin-usage-billing-credits
- https://www.snowflake.com/blog/introducing-snowflake-generation-2-standard-warehouses/

## Billing / Usage Data Sources

### Primary

**`SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY`** (the canonical source; requires ORGADMIN-granted `SNOWFLAKE.ORGANIZATION_USAGE_VIEWER` database role).

Returns already-billed USD per day per account per service type, nets the 10% Cloud Services allowance, honors on-demand-vs-capacity pricing, handles currency conversion for non-USD accounts. One row per `(usage_date, account_name, service_type, usage_type)`.

```sql
SELECT
    USAGE_DATE,
    ACCOUNT_NAME,
    SERVICE_TYPE,
    USAGE_TYPE,
    SUM(USAGE) AS USAGE,
    ANY_VALUE(USAGE_UNITS) AS USAGE_UNITS,
    SUM(USAGE_IN_CURRENCY) AS USAGE_IN_CURRENCY,
    ANY_VALUE(CURRENCY) AS CURRENCY
FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY
WHERE USAGE_DATE >= DATEADD(day, -:days, CURRENT_DATE())
GROUP BY 1, 2, 3, 4;
```

Auth: Key-pair recommended (`rsa_key`), with a dedicated role, e.g.:

```sql
CREATE ROLE COSTLY_READER;
GRANT DATABASE ROLE SNOWFLAKE.ORGANIZATION_USAGE_VIEWER TO ROLE COSTLY_READER;
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE COSTLY_READER;
GRANT USAGE ON WAREHOUSE COSTLY_WH TO ROLE COSTLY_READER;
GRANT ROLE COSTLY_READER TO USER COSTLY_SERVICE;
```

Latency: ~15 min–3 hours typical (Snowflake docs commit ≤2 hours).

### Secondary / Fallback

- **`SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY`** — credits per day per service type, with `CREDITS_ADJUSTMENT_CLOUD_SERVICES` for the 10% rebate. Latency 30 min-2 hours. Requires `IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE`.
- **`SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`** — per-warehouse credit lines. Finer grain but has only `CREDITS_USED_COMPUTE` + `CREDITS_USED_CLOUD_SERVICES` (no net), so the 10% allowance is only correctly applied when joined with `METERING_DAILY_HISTORY`.
- **`METERING_HISTORY`** — hourly (versus daily) resolution; useful for intra-day spike detection but costs 24× more rows.
- **Snowsight Cost Management** UI — reads the same views; for eyeball sanity-checks only.
- **Account billing CSV export (deprecated)** — the old `/api/statement` endpoint retired 2024-Q4; no longer available.
- **Snowflake Organization Account** (introduced 2025-Q3) — single login to the `ORGADMIN` parent that owns all billing. Required for multi-account consolidation in large orgs. See https://docs.snowflake.com/en/user-guide/organizations-manage.

### Gotchas

- **ORGANIZATION_USAGE latency can be 24-48 h** on brand-new accounts until the first billing cycle closes. If yesterday is empty, do not assume ingestion failed — recompute for D-2.
- **`USAGE_IN_CURRENCY_DAILY` is account-local** for currency (EUR/AUD/GBP). Always convert using the `CURRENCY` column or a daily FX table; otherwise summing produces garbage.
- **Iceberg external-managed tables**: storage is zero on Snowflake's side but compute and `ICEBERG_TABLE_REQUESTS_HISTORY` (per-request) still bill. Easy to miss.
- **Cortex billing** shows up as `AI_SERVICES` in `USAGE_IN_CURRENCY_DAILY`. Costly maps this to `ai_inference`. Sub-categorization (per LLM model) only available via `CORTEX_FUNCTIONS_USAGE_HISTORY`.
- **Snowpark Container Services** nodes bill in SPCS-specific credits (not warehouse credits) — `SNOWPARK_CONTAINER_SERVICES_HISTORY` required; frequently overlooked.
- **Delta (Unistore Hybrid Tables)** has its own `HYBRID_TABLE_STORAGE` line at ~10× standard storage price — flag any customer using Unistore.
- **Region mismatch**: `USAGE_IN_CURRENCY_DAILY` runs against the ORGADMIN role in its home account/region. If the customer's Org is in AWS US-East-1 but the account is in Azure Europe, currency + region pricing is still correct (Snowflake derives from the account's region), but the `REGION` column requires joining to `ORGANIZATION_USAGE.CONTRACT_ITEMS`.
- **Flat-rate capacity** customers: `USAGE_IN_CURRENCY_DAILY` shows the *effective* rate, but `ACCOUNT_USAGE.METERING_DAILY_HISTORY` emits credits at list — if Costly uses the fallback without a `credit_price_usd` override the total will overstate cost. Remediation: always override `credit_price_usd` when capacity is detected (look for `CONTRACT_ITEMS.CONTRACT_TYPE = 'CAPACITY'`).
- **Clouds Services free allowance** is a *daily* 10% budget — you cannot net-aggregate across months without pulling daily rows first.
- **View refresh windows**: ACCOUNT_USAGE views lag 30 min-3 h for most tables, 45-90 min for `QUERY_HISTORY`, 8 h for `ACCESS_HISTORY`, 12 h for `DATABASE_STORAGE_USAGE_HISTORY`.
- **`QUERY_ATTRIBUTION_HISTORY` only attributes warehouse compute credits** — not Cloud Services, not serverless. For the full picture you still need `QUERY_HISTORY.CREDITS_USED_CLOUD_SERVICES`.

## Schema / Fields Available

### `ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY`

| Column | Type | Notes |
|--------|------|-------|
| `ORGANIZATION_NAME` | TEXT | Parent org |
| `CONTRACT_NUMBER` | TEXT | For multi-contract orgs |
| `ACCOUNT_NAME` | TEXT | Child account |
| `ACCOUNT_LOCATOR` | TEXT | Alphanumeric |
| `REGION` | TEXT | e.g. AWS_US_EAST_1 |
| `SERVICE_LEVEL` | TEXT | Standard / Enterprise / BC / VPS |
| `USAGE_DATE` | DATE | Daily |
| `SERVICE_TYPE` | TEXT | WAREHOUSE_METERING, CLOUD_SERVICES, SERVERLESS_TASK, PIPE, AUTO_CLUSTERING, MATERIALIZED_VIEW, SEARCH_OPTIMIZATION, REPLICATION, QUERY_ACCELERATION, AI_SERVICES, STORAGE, DATA_TRANSFER, LOGGING, HYBRID_TABLE_STORAGE, ICEBERG_TABLE_REQUESTS, SNOWPIPE_STREAMING, etc. |
| `USAGE_TYPE` | TEXT | e.g. overage-compute, capacity-compute, on-demand-storage |
| `USAGE` | NUMBER | Raw units (credits / TB-hours / requests) |
| `USAGE_UNITS` | TEXT | credits / TB / bytes / requests |
| `USAGE_IN_CURRENCY` | NUMBER | **Billed USD (or local)** |
| `CURRENCY` | TEXT | USD/EUR/AUD/GBP/CAD |
| `BALANCE_SOURCE` | TEXT | 2025+: free / capacity / on-demand / rollover |
| `IS_ADJUSTMENT` | BOOLEAN | Credits/refunds |

### `ACCOUNT_USAGE.METERING_DAILY_HISTORY`

| Column | Type | Notes |
|--------|------|-------|
| `USAGE_DATE` | DATE | |
| `SERVICE_TYPE` | TEXT | |
| `CREDITS_USED_COMPUTE` | NUMBER | Gross compute |
| `CREDITS_USED_CLOUD_SERVICES` | NUMBER | Gross cloud services |
| `CREDITS_ADJUSTMENT_CLOUD_SERVICES` | NUMBER | ≤0, 10% allowance |
| `CREDITS_BILLED` | NUMBER | Net billed credits |

### `ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`

| Column | Type |
|--------|------|
| `START_TIME`, `END_TIME` | TIMESTAMP_LTZ |
| `WAREHOUSE_ID`, `WAREHOUSE_NAME`, `WAREHOUSE_SIZE` | TEXT |
| `CREDITS_USED_COMPUTE`, `CREDITS_USED_CLOUD_SERVICES`, `CREDITS_USED` | NUMBER |

### `ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY` (GA Jan 2024)

| Column | Type |
|--------|------|
| `START_TIME`, `END_TIME` | TIMESTAMP_LTZ |
| `QUERY_ID`, `QUERY_HASH`, `PARENT_QUERY_ID`, `ROOT_QUERY_ID` | TEXT |
| `USER_NAME`, `ROLE_NAME`, `WAREHOUSE_NAME` | TEXT |
| `WAREHOUSE_SIZE`, `WAREHOUSE_TYPE` | TEXT |
| `QUERY_TAG` | TEXT |
| `CREDITS_ATTRIBUTED_COMPUTE` | NUMBER |

### `ACCOUNT_USAGE.QUERY_HISTORY` (full per-query spectrum — not yet used by Costly)

Notable cost-relevant columns:

- `EXECUTION_TIME` (ms), `COMPILATION_TIME`, `QUEUED_PROVISIONING_TIME`, `QUEUED_OVERLOAD_TIME`
- `CREDITS_USED_CLOUD_SERVICES` (per-query cloud services share)
- `BYTES_SCANNED`, `BYTES_SPILLED_TO_LOCAL_STORAGE`, `BYTES_SPILLED_TO_REMOTE_STORAGE`
- `PARTITIONS_SCANNED`, `PARTITIONS_TOTAL`
- `ROLE_NAME`, `USER_NAME`, `WAREHOUSE_NAME`, `WAREHOUSE_SIZE`, `QUERY_TAG`
- `QUERY_TYPE` (SELECT, INSERT, COPY, CTAS, ...)

### `ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY`

| Column | Type |
|--------|------|
| `USAGE_DATE` | DATE |
| `DATABASE_NAME` | TEXT |
| `AVERAGE_DATABASE_BYTES` | NUMBER (active bytes, average over day) |
| `AVERAGE_FAILSAFE_BYTES` | NUMBER |

### `ACCOUNT_USAGE.TABLE_STORAGE_METRICS`

| Column | Type |
|--------|------|
| `TABLE_CATALOG`, `TABLE_SCHEMA`, `TABLE_NAME` | TEXT |
| `ID` | TEXT |
| `ACTIVE_BYTES`, `TIME_TRAVEL_BYTES`, `FAILSAFE_BYTES`, `RETAINED_FOR_CLONE_BYTES` | NUMBER |
| `IS_TRANSIENT`, `DELETED` | BOOLEAN |
| `LAST_DDL` | TIMESTAMP_LTZ |

### `ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY` (utilization — not yet used by connector)

| Column | Type |
|--------|------|
| `START_TIME`, `END_TIME` | TIMESTAMP_LTZ |
| `WAREHOUSE_ID`, `WAREHOUSE_NAME` | TEXT |
| `AVG_RUNNING`, `AVG_QUEUED_LOAD`, `AVG_QUEUED_PROVISIONING`, `AVG_BLOCKED` | NUMBER |

Use case: detect under-utilized warehouses (AVG_RUNNING << size) for downsize recommendations.

### `ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY`

| Column | Type |
|--------|------|
| `START_TIME`, `END_TIME` | TIMESTAMP_LTZ |
| `WAREHOUSE_ID`, `WAREHOUSE_NAME` | TEXT |
| `USER_NAME` | TEXT |
| `FUNCTION_NAME` | TEXT (COMPLETE, EMBED_TEXT_768, TRANSLATE, SENTIMENT, SUMMARIZE, EXTRACT_ANSWER, CLASSIFY_TEXT) |
| `MODEL_NAME` | TEXT (llama3-70b, mistral-large, arctic, claude-3-5-sonnet, ...) |
| `TOKENS` | NUMBER |
| `TOKEN_CREDITS` | NUMBER |

### `ACCOUNT_USAGE.AI_SERVICES_USAGE_HISTORY` (GA April 2026)

New unified view introduced with the AI Budgets feature, consolidates Cortex Functions, Analyst, Search, Document AI, and Universal Search in one row-per-day table. Costly does **not** query this yet.

## Grouping Dimensions

- **Warehouse** — primary attribution for compute; pair with `WAREHOUSE_SIZE` to detect oversized.
- **Database / Schema / Table** — storage and (via `QUERY_HISTORY.DATABASE_NAME` + object-scan columns) query cost.
- **User** — `QUERY_ATTRIBUTION_HISTORY.USER_NAME`; detect rogue personas.
- **Role** — `ROLE_NAME`; natural team boundary if the customer follows RBAC hygiene.
- **Query tag** — free-text on each session (`ALTER SESSION SET QUERY_TAG = 'bi:looker:marketing'`). Best dimension for cross-cutting attribution when customer has adopted tagging.
- **Query hash** — normalized SQL fingerprint; groups parameterized queries.
- **Service type** — compute / cloud services / each serverless SKU separately.
- **Workload** — derived by Costly (not native) from `QUERY_TAG` patterns + `USER_NAME` heuristics.
- **Account** — in ORGANIZATION_USAGE, per-account breakdown for multi-tenant orgs.
- **Region** — `CONTRACT_ITEMS.REGION`; egress is the dominant per-region cost delta.
- **Warehouse size** — XS → 6XL.
- **Warehouse type** — STANDARD, SNOWPARK-OPTIMIZED, STANDARD_GEN_2.

## Open-Source Tools Tracking This Platform

| Project | URL | Stars | License | Data source | What it does |
|---------|-----|-------|---------|-------------|--------------|
| **dbt-snowflake-monitoring** (Select.dev) | https://github.com/get-select/dbt-snowflake-monitoring | ~1.4K | Apache 2.0 | `ACCOUNT_USAGE.QUERY_HISTORY`, `WAREHOUSE_METERING_HISTORY`, `DATABASE_STORAGE_USAGE_HISTORY`, `QUERY_ATTRIBUTION_HISTORY` | De facto standard dbt package for cost modeling. Computes per-query cost, per-warehouse daily spend, per-tag / per-role rollups. **This is the benchmark every Snowflake cost tool is measured against.** |
| **dbt_snowflake_query_tags** (Select) | https://github.com/get-select/dbt_snowflake_query_tags | ~430 | Apache 2.0 | N/A — injects dbt-invocation metadata into `QUERY_TAG` | Enables dbt-level attribution downstream. |
| **Chaos Genius** | https://github.com/chaos-genius/chaos_genius | ~700 | MIT | ACCOUNT_USAGE (Snowflake plugin) | Open-source FinOps + anomaly detection. Dormant since mid-2024 but fork-friendly. |
| **Snowflake Admin Scripts (SF Labs)** | https://github.com/Snowflake-Labs/sfguide-tasty-bytes-cost-management | N/A | Apache 2.0 | ACCOUNT_USAGE | Snowflake's own reference scripts for Cost Management Guide. |
| **snowflake-cost-optimization** (AltimateAI) | https://github.com/AltimateAI/snowflake-cost-optimization | ~180 | MIT | ACCOUNT_USAGE | Open recipes covering auto-suspend audits, warehouse right-sizing, idle-table detection. |
| **finops-snowflake** (apache-airflow-providers-snowflake community) | https://github.com/lazyhelo/finops-snowflake | ~60 | MIT | ACCOUNT_USAGE | Airflow DAG bundle; good reference for daily extraction jobs. |
| **dbt-snowflake-utils** (Fishtown community) | https://github.com/Montreal-Analytics/dbt_snowflake_utils | ~110 | Apache 2.0 | Various | Utility macros for cost-aware materializations. |
| **SnowBot** (community) | https://github.com/Snowflake-Labs/snowbot-usage | N/A | Apache 2.0 | ACCOUNT_USAGE | Slack bot for daily spend digest. |
| **Snowflake Query Profile Parser** | https://github.com/Snowflake-Labs/sf_query_profile_parser | ~60 | Apache 2.0 | QUERY_HISTORY + EXPLAIN | Extracts spill, partition-pruning, join-skew signals — feeds recommendation engine. |
| **snowflake-labs/cost-usage-dashboards** | https://github.com/Snowflake-Labs/snowflake-labs-tasty-bytes (various) | N/A | Apache 2.0 | ACCOUNT_USAGE | Streamlit-in-Snowflake cost dashboards. |
| **Keebo open-source agent stubs** | (private; some public blog gists) | — | — | N/A | Keebo shares detection SQL in their blog. |
| **Flex.io Warehouse Analyzer** | https://github.com/flex-io/snowflake-warehouse-analyzer | ~40 | MIT | WAREHOUSE_LOAD_HISTORY + WAREHOUSE_METERING_HISTORY | Outputs right-size recommendations. |

**Implication for Costly**: `dbt-snowflake-monitoring` sets the bar for per-query attribution + warehouse rollups. We should either (a) invoke it directly by having Costly write results to a staging schema and running the package on the customer's Snowflake, or (b) re-implement the 5-6 core fact models natively. Today we do neither — we compute at the row level in Python, which loses the composability dbt offers.

## How Competitors Handle This Platform

### Select.dev — the deepest native tool (https://select.dev)

- **UI**: Per-warehouse daily spend chart, per-query cost drill-down, "Where is my spend going?" treemap by warehouse → user → query hash. Excellent right-sizing report per warehouse showing `avg_running` vs `credits_used` over 30 days.
- **Data pipeline**: Runs the `dbt-snowflake-monitoring` package on the customer's own Snowflake account nightly; materializes `query_history_enriched`, `daily_spend`, `hourly_spend` tables; Select then reads those directly.
- **Key feature**: Automatic warehouse auto-suspend tuning agent (opt-in writes to customer's Snowflake to ALTER WAREHOUSE … SET AUTO_SUSPEND = n).
- **Pricing**: $500-$5,000/month depending on spend tier. Enterprise plans include credit-back SLAs.
- **Positioning**: "Snowflake FinOps at the DBA layer". Built by ex-Snowflake engineers (Niall Woodward, Ian Whitestone).

### Keebo — autonomous optimization (https://keebo.ai)

- **UI**: Warehouse configurations page showing current vs Keebo-recommended `WAREHOUSE_SIZE`, `AUTO_SUSPEND`, `SCALING_POLICY`. Savings meter across 30/60/90 days.
- **Mechanism**: Agent runs against Snowflake with elevated role; continuously re-sizes warehouses based on queue depth, then credits back the customer for the delta.
- **Claims**: 25-40% reduction on warehouse spend.
- **Public content**: https://keebo.ai/blog; they share many SQL snippets for detecting queue overload.

### Espresso AI (https://espresso.ai)

- **Claims**: 70% savings via query-plan rewriting + result caching. 2024-2025 Series A.
- **Approach**: LLM-based SQL rewriter that intercepts queries via a proxy layer, rewrites to hit cached partitions or use clustering keys, and transparently returns results. Also ships an autonomous warehouse-sizing agent.
- **Challenge**: Proxy architecture requires Snowflake driver replacement — heavier integration than read-only.

### Chaos Genius / Flexera (enterprise)

- **Flexera** (Flexera One Cloud Cost Optimization): Generic multi-cloud/data-platform FinOps; Snowflake module ingests `USAGE_IN_CURRENCY_DAILY`, renders treemap + time-series + anomaly flags. Integrates with procurement workflows (chargeback, showback). Enterprise sales, $50K+/yr.
- **Chaos Genius**: OSS version goes deep on anomaly detection; decent Snowflake coverage.

### Unravel (https://unravel.io)

- **Multi-platform**: DBX + SF + BQ in one UI. Per-query recommendations powered by their query-execution capture. Enterprise-heavy sales motion.
- **Snowflake-specific**: query replay, warehouse right-sizing, but less depth than Select.dev.

### Revefi (https://revefi.com)

- **Unified + AI agent**: Detects anomalies, creates Slack alerts, and opens **GitHub PRs** against customer dbt repos with fix recommendations. Claims 6-month payback.
- **Coverage**: SF + DBX + BQ.
- **Differentiator**: Agent that can "write code" to fix issues. Aspirational model for Costly's expert agents.

### Vantage (https://vantage.sh)

- Generic multi-cloud FinOps. Snowflake tile is relatively shallow — pulls `USAGE_IN_CURRENCY_DAILY`, renders cost by service. No warehouse-level right-sizing or query-level attribution.
- Strength: unified billing across AWS + GCP + Azure + Snowflake + DBX.

### CloudZero (https://cloudzero.com)

- Enterprise unit-economics platform. Snowflake support is mid-tier: pulls credits per warehouse, lets you map warehouses → business units for showback. Weak on query-level attribution.

### Finout (https://finout.io)

- FinOps with strong virtual-tagging. Snowflake tile reads `USAGE_IN_CURRENCY_DAILY`, supports chargeback, less deep on optimization.

### Datadog Cloud Cost Management (https://www.datadoghq.com/product/cloud-cost-management/)

- 2025 Snowflake integration; pulls `ACCOUNT_USAGE` views via Datadog Agent. Fine for correlation with app metrics, shallow for DBA-level optimization.

### Snowsight Cost Management (Snowflake native)

- Built into Snowsight UI. Shows org-wide spend, per-warehouse/service breakdown, alerts. Solid foundation but not actionable (no recommendations, no automatic sizing).
- **AI Budgets** (GA April 2026): Set a budget per service, get auto-alerts when 50/80/100% hit; includes forecasted burn rate. See https://docs.snowflake.com/en/user-guide/budgets.

## Books / Published Material / FinOps Literature

### Snowflake-specific

- **"Snowflake: The Definitive Guide"** (O'Reilly, 2nd ed 2023) — Joyce Kay Avila, Jim Cummings, Chris Blaisdell. Chapter 14 ("Managing Costs and Performance") is canonical. Missing post-2024 Cortex/serverless expansion.
- **"Efficient Snowflake"** — Snowflake's own free resource hub: https://www.snowflake.com/resource/efficient-snowflake/. Includes "The Snowflake Cost Optimization Playbook" (PDF, 2024).
- **Select.dev Cost Optimization eBook**: https://select.dev/resources. Most detailed practitioner guide on the internet — covers warehouse right-sizing, clustering, materialized views, query profiling, dbt cost tagging.
- **Niall Woodward's blog** (Select co-founder): https://niallrees.com, https://select.dev/blog. Deep multi-part series: "How to Reduce Snowflake Costs" (10+ posts).
- **Ian Whitestone's blog** (Select co-founder): https://ianwhitestone.work. Strong on query optimization and FinOps automation.
- **Tomáš Sobotík** (Snowflake Data Superhero): https://www.tomassobotik.net. Practitioner deep dives.
- **"Mastering Snowflake Solutions"** (Apress, 2024) — Adam Morton.
- **"Snowflake Cookbook"** (Packt, 2024) — Hamid Mahmood Qureshi.
- **Snowflake Resource Monitors docs**: https://docs.snowflake.com/en/user-guide/resource-monitors — built-in hard-stop on credit overruns.
- **Snowflake Warehouse Best Practices**: https://docs.snowflake.com/en/user-guide/warehouses-considerations.

### Cross-platform

- **"Cloud FinOps"** (2nd ed, O'Reilly, 2023) — J.R. Storment + Mike Fuller. Chapter 13 covers data-platform FinOps with Snowflake/BQ/DBX call-outs.
- **FinOps Foundation framework**: https://www.finops.org/framework/. Capability-led; Snowflake maps cleanly onto "Data Workloads" domain added in the 2024 revision.
- **Snowflake Summit talks** (annual, typically June): "Cost Optimization Deep Dive" sessions each year. 2024 and 2025 recordings on Snowflake's YouTube.
- **Data Cloud Summit 2025**: session "AI Budgets in Practice" previewed the April 2026 GA.
- **dbt Coalesce** conference annually has a "Cost-aware dbt" track.
- **Cloud Cost Handbook** (cloudcosthandbook.com, Vantage) — open chapter on Snowflake.

## Vendor Documentation Crawl

2025-2026 Snowflake pricing / billing / release-note walk:

- **Pricing landing page**: https://www.snowflake.com/pricing/
- **Pricing guide PDF** (Apr 2026 edition): https://www.snowflake.com/pricing/pricing-guide/
- **Admin billing credits**: https://docs.snowflake.com/en/user-guide/admin-usage-billing-credits
- **Cost Management overview**: https://docs.snowflake.com/en/user-guide/cost-management
- **Resource Monitors**: https://docs.snowflake.com/en/user-guide/resource-monitors
- **Budgets (AI Budgets GA April 2026)**: https://docs.snowflake.com/en/user-guide/budgets
- **ORGANIZATION_USAGE views**: https://docs.snowflake.com/en/sql-reference/organization-usage
- **ACCOUNT_USAGE views**: https://docs.snowflake.com/en/sql-reference/account-usage
- **USAGE_IN_CURRENCY_DAILY**: https://docs.snowflake.com/en/sql-reference/organization-usage/usage_in_currency_daily
- **QUERY_ATTRIBUTION_HISTORY**: https://docs.snowflake.com/en/sql-reference/account-usage/query_attribution_history
- **METERING_DAILY_HISTORY**: https://docs.snowflake.com/en/sql-reference/account-usage/metering_daily_history
- **WAREHOUSE_LOAD_HISTORY**: https://docs.snowflake.com/en/sql-reference/account-usage/warehouse_load_history
- **TABLE_STORAGE_METRICS**: https://docs.snowflake.com/en/sql-reference/account-usage/table_storage_metrics
- **Cortex Functions pricing**: https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-pricing
- **Snowpark Container Services pricing**: https://docs.snowflake.com/en/developer-guide/snowpark-container-services/billing
- **Gen-2 warehouses**: https://www.snowflake.com/blog/introducing-snowflake-generation-2-standard-warehouses/ + https://docs.snowflake.com/en/user-guide/warehouses-overview#gen2-standard
- **Iceberg tables pricing**: https://docs.snowflake.com/en/user-guide/tables-iceberg-billing
- **Hybrid tables (Unistore)**: https://docs.snowflake.com/en/user-guide/tables-hybrid
- **Release notes archive (2025)**: https://docs.snowflake.com/en/release-notes/2025
- **Release notes archive (2026)**: https://docs.snowflake.com/en/release-notes/2026

Notable 2025-2026 changes relevant to cost tracking:
- **March 2025**: Gen-2 warehouses GA on new accounts (same credit rate, 2× perf).
- **June 2025**: Hybrid Tables (Unistore) GA; separate HYBRID_TABLE_STORAGE billing SKU.
- **Oct 2025**: Cortex pricing revised downward for Llama-3-70B; introduced Arctic-Instruct-2.
- **Dec 2025**: Organization Accounts GA (single ORGADMIN parent for consolidated billing).
- **Jan 2026**: Snowpipe Streaming v2 (SDK 2.0) — rowset billing refined; per-1K-rows.
- **Apr 2026**: **AI Budgets GA** — unified budget object covering Cortex/ML/Doc AI/Snowpark Container. New `AI_SERVICES_USAGE_HISTORY` view.
- **Apr 2026**: Iceberg Table Requests GA as billable SKU (`ICEBERG_TABLE_REQUESTS_HISTORY`).
- Deprecations: CSV billing export (removed Q4 2024).

## Best Practices (synthesized)

1. **Always prefer `USAGE_IN_CURRENCY_DAILY`**; fall back to `METERING_DAILY_HISTORY` only when the role lacks ORG access. Never mix the two in a single aggregate.
2. **Honor the 10% Cloud Services allowance** via `CREDITS_ADJUSTMENT_CLOUD_SERVICES`. Gross cloud services without adjustment overstates cost by 5-15%.
3. **Pull `QUERY_ATTRIBUTION_HISTORY`** for per-user/role/tag attribution; combine with `QUERY_HISTORY` for query-level stats (spill, scan, queue).
4. **Right-size warehouses using `WAREHOUSE_LOAD_HISTORY`**: if `AVG_RUNNING < 0.25 × num_cores_for_size` across 14 days, recommend downsize.
5. **Tune `AUTO_SUSPEND`** down to 60s for BI warehouses (query concurrency smooths warming), 300s for ELT warehouses. Default of 10 min wastes credits.
6. **Use Resource Monitors + AI Budgets** for hard stops and forecasted alerts.
7. **Tag every session** (`ALTER SESSION SET QUERY_TAG = 'service:environment:purpose'`); without tags, `QUERY_ATTRIBUTION_HISTORY` only gets you user+role.
8. **Separate workloads by warehouse**: BI, ELT, ad-hoc, dbt, reverse-ETL each get their own warehouse so utilization and spikes are attributable.
9. **Drop Time-Travel to 1 day** on staging/raw tables (default 1 day on Standard, 90 on Enterprise). `TABLE_STORAGE_METRICS.TIME_TRAVEL_BYTES` quickly reveals the biggest offenders.
10. **Drop `RETAINED_FOR_CLONE_BYTES`** from zero-copy clones that have outlived their purpose.
11. **Audit idle Search Optimization / Automatic Clustering** — they bill continuously even when the base table is rarely queried.
12. **Monitor Snowpipe cost-per-file**: small files (<16 MB) inflate the per-file overhead. Batch to 100-250 MB before ingestion.
13. **Gen-2 migration**: for customers still on Gen-1 warehouses, switching (same credit rate) commonly yields 25-40% throughput gain → smaller warehouses do the same work.
14. **Cortex**: choose the cheapest model that meets quality; Llama-3-8B is 8× cheaper than Llama-3-70B. Cache embeddings; avoid re-embedding unchanged text.
15. **Set per-warehouse Resource Monitors** even on capacity contracts (prevents runaway queries from burning through annual commit in days).

## Costly's Current Connector Status

Source: `/Users/jain/src/personal/costly/backend/app/services/connectors/snowflake_connector.py` (~1,220 lines, most mature connector in the repo).

**Implemented:**
- Primary path: `ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY` with full service-type mapping → `CostCategory` (compute, ingestion, storage, ai_inference, networking, orchestration).
- Fallback path: `ACCOUNT_USAGE.METERING_DAILY_HISTORY` with `CREDITS_ADJUSTMENT_CLOUD_SERVICES` netting for the 10% cloud services allowance. Second fallback to `WAREHOUSE_METERING_HISTORY`.
- Nine serverless credit lines: `SERVERLESS_TASK_HISTORY`, `PIPE_USAGE_HISTORY`, `AUTOMATIC_CLUSTERING_HISTORY`, `MATERIALIZED_VIEW_REFRESH_HISTORY`, `SEARCH_OPTIMIZATION_HISTORY`, `REPLICATION_USAGE_HISTORY`, `QUERY_ACCELERATION_HISTORY`, `SNOWPIPE_STREAMING_CLIENT_HISTORY`, and dual-path Cortex via `CORTEX_FUNCTIONS_USAGE_HISTORY` / `CORTEX_ANALYST_USAGE_HISTORY`.
- Attribution: `QUERY_ATTRIBUTION_HISTORY` surfaced as `team=role_name`, `project=query_tag`.
- Storage: `DATABASE_STORAGE_USAGE_HISTORY` split into active + failsafe per-database, plus `TABLE_STORAGE_METRICS` snapshot for time-travel.
- Pricing overrides via `PricingConfig` (credit_price_usd, per-warehouse-size prices, per-service-type prices, storage per-TB, prefer_org_usage flag).
- Permission errors wrapped in `SnowflakePermissionError` with exact `GRANT` remediation.
- Timezone-aware datetimes.

**Not implemented:**
- `WAREHOUSE_LOAD_HISTORY` (utilization for right-sizing recommendations).
- `QUERY_HISTORY` at the row level (per-query bytes-scanned, spill, queue, compile) — Costly has this in `services/snowflake.py` for the legacy dashboard, but the cost connector never ingests it.
- `ACCESS_HISTORY` (stale-table detection).
- `WAREHOUSE_EVENTS_HISTORY` (auto-suspend/resume patterns).
- `LOGIN_HISTORY`.
- New `AI_SERVICES_USAGE_HISTORY` (April 2026 GA).
- Iceberg requests (`ICEBERG_TABLE_REQUESTS_HISTORY`).
- Hybrid Tables storage (would come through `USAGE_IN_CURRENCY_DAILY` as `HYBRID_TABLE_STORAGE` today but category is just `storage` — no unit-economics surface).
- Snowpark Container Services (`SNOWPARK_CONTAINER_SERVICES_HISTORY`).
- Cortex Search Serving (`CORTEX_SEARCH_SERVING_USAGE_HISTORY`).
- Cortex per-model cost breakdown — today it all rolls up to `snowflake_cortex`.
- Gen-1 vs Gen-2 warehouse detection (migration savings recommendation).
- Organization-wide (multi-account) rollup via ORGADMIN (code does not iterate accounts).
- Write-back / recommendation execution (e.g., `ALTER WAREHOUSE ... SET AUTO_SUSPEND`).
- dbt-snowflake-monitoring package invocation.

**Grade: B+.** Coverage is strong on daily totals, breakdown is solid on serverless, but the drill-down dimension (query-level USD with scan/spill attribution) is absent. This is what Select.dev and Unravel lead with.

## Gaps Relative to Best Practice

1. **No query-level cost.** Costly shows daily totals + warehouse + user but cannot answer "which query cost the most?" without going back to the legacy `services/snowflake.py` dashboard path.
2. **No right-sizing recommendation** — `WAREHOUSE_LOAD_HISTORY` never ingested.
3. **No auto-suspend tuning** — `WAREHOUSE_EVENTS_HISTORY` never ingested.
4. **No stale-table / unused-index detection** — `ACCESS_HISTORY` not ingested.
5. **No Gen-2 migration flag** — `WAREHOUSES.RESOURCE_CONSTRAINT` not read.
6. **No Cortex per-model breakdown** — everything rolls up under `snowflake_cortex`.
7. **No Iceberg request line.**
8. **No Snowpark Container Services.**
9. **No `AI_SERVICES_USAGE_HISTORY`** (April 2026 GA) — we're missing the unified AI budget view that will become the canonical source.
10. **No multi-account rollup** even when customer uses Organization Accounts.
11. **No resource-monitor / budget integration** — we cannot surface "you're at 85% of your monthly budget" because we don't read `BUDGETS` metadata.
12. **No capacity-vs-on-demand detection** — customers on capacity contracts get overstated spend from the fallback path.
13. **Pricing defaults are list** — no region-aware pricing, no edition lookup from `CURRENT_ACCOUNT()`.
14. **No dbt-snowflake-monitoring integration** — we duplicate in Python what the dbt package already materializes on the customer side.
15. **No write-back optimization actions** — can recommend, cannot execute. Select.dev and Keebo do execute.
16. **No anomaly detection** built into the connector (handled elsewhere in app but not warehouse-aware).
17. **No freshness / latency display** — user doesn't know the 2-3 h view lag.

## Roadmap

### Near-term (next 2 weeks)

- Ingest `WAREHOUSE_LOAD_HISTORY` for under-utilization recommendations.
- Ingest `WAREHOUSE_EVENTS_HISTORY` for auto-suspend tuning.
- Add `AI_SERVICES_USAGE_HISTORY` for the new consolidated AI budget view.
- Surface capacity-vs-on-demand flag from `CONTRACT_ITEMS` and override `credit_price_usd` automatically.
- Add region-aware default pricing (derive from `CURRENT_REGION()` + edition lookup).
- Expose connector warnings to the dashboard (currently swallowed into `self.warnings`).

### Medium-term (next 4-6 weeks)

- Query-level cost ingestion: `QUERY_HISTORY` rows with `CREDITS_USED_CLOUD_SERVICES`, spill bytes, scan bytes, queue time.
- Cortex per-model breakdown.
- Iceberg + Snowpark Container Services + Hybrid Tables unit-economics surfaces.
- Gen-2 migration flag + savings estimate.
- Integrate `dbt-snowflake-monitoring` as an optional install path (Costly triggers the package run on the customer's Snowflake; reads the resulting mart).
- Data freshness badge on every tile (reads `LAST_USAGE_DATE` from each view).

### Long-term (2-3 months)

- Write-back optimization: approved actions that run `ALTER WAREHOUSE` via a separate role with `MODIFY` on specific warehouses (gated behind human approval per action).
- Multi-account rollup via Organization Accounts with per-account cost pages.
- Anomaly detection using `CORTEX_FORECAST` on per-warehouse daily series.
- Budget + Resource Monitor integration: read existing monitors, let the user create new ones from the UI.
- Full replica of `dbt-snowflake-monitoring` in Costly's own schema for customers who don't run dbt.
- Per-model pricing table kept fresh by a Costly-operated crawler of `snowflake.com/pricing` + release notes.
- "Snowflake Expert" agent (see `costly-expert-agents.md`) that ingests the full tool registry and can answer any cost/perf question about the customer's account.

## Change Log

- 2026-04-24: Initial knowledge-base created by overnight research run.
