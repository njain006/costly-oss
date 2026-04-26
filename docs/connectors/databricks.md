# Databricks — Connector Knowledge Base

_Last updated: 2026-04-24 by overnight research run_

## TL;DR

Databricks is Costly's lakehouse connector. The current implementation pulls DBU consumption from the deprecated account-level `/usage/download` CSV endpoint and estimates USD by multiplying DBUs by a hard-coded per-SKU price table, with a workspace-level cluster-list fallback that uses heuristic uptime math. Grade today: **C- (uses the deprecated CSV endpoint, does not query `system.billing.usage` + `system.billing.list_prices` system tables that GA'd October 2024, no Photon / Serverless / Model Serving / Vector Search / Jobs-over-Serverless split, and the DBU price table is out of date for 2026).** Top gap: the entire connector should pivot to Databricks **system tables** (`system.billing.usage` for DBU × list price, `system.access.audit` for attribution), which is the official, documented, GA replacement.

## Pricing Model (from vendor)

Databricks bills in **DBUs** (Databricks Units) — a normalized unit of compute-second at a reference VM type. A DBU is not a flat dollar rate; the USD/DBU varies by SKU (compute tier), plan tier (Standard / Premium / Enterprise), and cloud. On top of DBU charges, customers pay the underlying cloud provider (AWS EC2, Azure VM, GCP GCE) separately for VM time.

### USD per DBU (April 2026 list, pay-as-you-go; Enterprise tier default)

**AWS Databricks:**

| SKU | Standard | Premium | Enterprise |
|-----|----------|---------|------------|
| Jobs Compute (Classic) | $0.15 | $0.30 | $0.40 |
| All-Purpose Compute (Classic) | $0.40 | $0.55 | $0.75 |
| SQL Compute (Classic) | $0.22 | $0.22 | $0.22 |
| SQL Pro | — | $0.55 | $0.55 |
| SQL Serverless | — | — | $0.70 |
| Serverless Compute (general) | — | — | $0.70 |
| Jobs on Serverless | — | — | $0.35 |
| Delta Live Tables (Core) | — | — | $0.20 |
| Delta Live Tables (Pro) | — | $0.25 | $0.25 |
| Delta Live Tables (Advanced) | — | — | $0.36 |
| DLT Serverless | — | — | $0.44 |
| Model Serving (CPU) | — | — | $0.07 |
| Model Serving (GPU) | — | — | varies by GPU; $0.20-$7.00/DBU-hour scaled |
| Foundation Model Serving (pay-per-token, Llama/DBRX/Mixtral) | — | — | per-token SKU; billed via `FOUNDATION_MODELS` in system tables |
| Mosaic AI Vector Search | — | — | $0.42/DBU for serverless endpoint |
| MLflow + Feature Store | — | — | bundled with compute (no separate DBU) |
| Databricks Apps (serverless apps) | — | — | $0.70/DBU |
| Lakehouse Monitoring | — | — | compute SKU of attached workspace |
| Genie / Databricks AI/BI | — | — | $0.70/DBU serverless + per-query tokens |

**Azure Databricks** (bills through Azure Marketplace; DBU rates roughly match AWS but include Azure's margin):

| SKU | Standard | Premium | Enterprise |
|-----|----------|---------|------------|
| Jobs | $0.15 | $0.30 | $0.40 |
| All-Purpose | $0.40 | $0.55 | $0.75 |
| SQL Pro | — | $0.55 | $0.55 |
| Serverless | — | — | $0.88 |

**GCP Databricks** (bills through GCP Marketplace):

| SKU | Enterprise only |
|-----|-----------------|
| Jobs | $0.30 |
| All-Purpose | $0.55 |
| Serverless | $0.88 |

### Photon

Photon-enabled compute multiplies DBUs by **~2.0-2.9×** but typically delivers 3-8× performance on TPC-DS-style workloads (Databricks' published benchmark). Detection: `cluster.runtime.photon_accelerated = true` or `usage_metadata.cluster_source = 'JOB'` + `usage_metadata.job_runtime_version` contains "photon". Photon has its own SKU line in system tables (`JOBS_PHOTON`, `ALL_PURPOSE_PHOTON`).

### Underlying cloud (not billed by Databricks)

- **AWS**: EC2 instance-hour for classic clusters; billed on customer's AWS account (not visible in Databricks bill). Costly's AWS connector picks this up via Cost Explorer.
- **Azure / GCP**: Similarly — VM cost billed by cloud provider.
- **Serverless**: Databricks owns the compute, no separate cloud bill.

### Commitments + discounts

- **Databricks Committed Use (DCU)**: 1-year or 3-year commit on DBUs; typical 20-40% discount.
- **Photon commit**: folds into DCU.
- **Azure MACC (Microsoft Azure Consumption Commitment)**: Databricks consumption counts toward MACC on Azure.
- **Google Committed Use Discounts**: similar on GCP.
- **Enterprise Agreements**: custom pricing for $5M+ accounts.
- **Free trials**: first 14 days credit-back.

### Regional deltas

- Databricks publishes ~same DBU price across major regions, but cloud VM prices differ significantly. Serverless has regional surcharges (+10-25% in APAC, EU regions).

Sources:
- https://www.databricks.com/product/pricing
- https://www.databricks.com/product/pricing/product-pricing/instance-types
- https://docs.databricks.com/en/admin/system-tables/billing.html
- https://learn.microsoft.com/en-us/azure/databricks/admin/system-tables/billing
- https://docs.databricks.com/en/admin/account-settings/usage.html

## Billing / Usage Data Sources

### Primary

**Databricks system tables** — `system.billing.*`. GA'd October 2024 (AWS), then expanded to Azure and GCP. This is the canonical, documented source for cost data. Enable via the Account Console > Admin Settings > Enable Metastore System Schemas, then grant `USE SCHEMA system.billing` to the service principal.

**`system.billing.usage`** — one row per DBU line-item per hour (approximately), with full metadata:

```sql
SELECT
  account_id,
  workspace_id,
  sku_name,                  -- e.g. ENTERPRISE_JOBS_COMPUTE, ENTERPRISE_SQL_PRO_COMPUTE_US_EAST_N_VIRGINIA
  cloud,
  usage_start_time,
  usage_end_time,
  usage_date,
  usage_unit,                -- DBU or STORAGE_MB
  usage_quantity,            -- raw quantity
  usage_metadata,            -- STRUCT: cluster_id, job_id, warehouse_id, notebook_id, endpoint_id, instance_pool_id, node_type, run_name, job_run_id, source_dashboard_id, etc.
  identity_metadata,         -- STRUCT: run_as (user or SP)
  record_type,               -- ORIGINAL, RETRACTION, RESTATEMENT
  ingestion_date,
  billing_origin_product,    -- JOBS, ALL_PURPOSE, SQL, DLT, MODEL_SERVING, SERVERLESS_REAL_TIME_INFERENCE, FOUNDATION_MODEL, LAKEHOUSE_MONITORING, VECTOR_SEARCH, AUTOLOADER, APPS, INGESTION, DEFAULT_STORAGE
  product_features,          -- STRUCT: is_serverless, is_photon, etc.
  usage_type,                -- COMPUTE_TIME, STORAGE_SPACE, NETWORK_BYTES, API_CALLS, TOKEN, GPU_TIME
  custom_tags                -- MAP<string, string> (compute + job tags propagate here)
FROM system.billing.usage
WHERE usage_date >= current_date - :days
```

**`system.billing.list_prices`** — one row per SKU per effective price window:

```sql
SELECT
  sku_name,
  cloud,
  currency_code,
  price_start_time,
  price_end_time,
  pricing.default AS list_price_per_unit,
  pricing.effective_list.default AS effective_price_per_unit,  -- default USD
  pricing.promotional.default,
  usage_unit
FROM system.billing.list_prices
```

Cost in USD:

```sql
SELECT
  u.usage_date,
  u.workspace_id,
  u.sku_name,
  u.billing_origin_product,
  SUM(u.usage_quantity) AS dbus,
  SUM(u.usage_quantity * lp.pricing.default) AS list_cost_usd
FROM system.billing.usage u
JOIN system.billing.list_prices lp
  ON u.sku_name = lp.sku_name
  AND u.cloud = lp.cloud
  AND u.usage_start_time >= lp.price_start_time
  AND (lp.price_end_time IS NULL OR u.usage_start_time < lp.price_end_time)
WHERE u.usage_date >= current_date - :days
GROUP BY 1,2,3,4
```

Auth: service principal + M2M OAuth token; grant `USE CATALOG system`, `USE SCHEMA system.billing`, `SELECT ON TABLE system.billing.usage`, `SELECT ON TABLE system.billing.list_prices`. Use SQL Warehouse for execution via the Statement Execution API.

Latency: 6-24 hours for final values; `record_type=RESTATEMENT` can trickle in up to 14 days later.

### Secondary / Fallback

- **Account-level Billable Usage REST API** (`/api/2.0/accounts/{account_id}/usage/download`) — **deprecated** but still functional. Returns a CSV; this is what Costly currently uses. Official docs label this a legacy API; new accounts get system tables instead.
- **Workspace cluster list** (`/api/2.0/clusters/list`) — current cluster state; no historical cost.
- **Workspace jobs list + runs** (`/api/2.2/jobs/*`) — per-job runtime; can multiply by DBU-per-hour but heuristic.
- **SQL Warehouses** (`/api/2.0/sql/warehouses`) — warehouse config.
- **Azure Cost Management API** — Azure Databricks bill via Azure marketplace.
- **AWS Cost Explorer** — for EC2 under AWS Databricks.
- **Databricks Unity Catalog lineage tables** (`system.access.*`) — for attribution.
- **Databricks Audit log** (`system.access.audit`) — high-cardinality action log with user identity; 365 days retention.
- **MLflow experiment tracking**: to attribute model training spend.
- **Cost export via Delta Sharing** (some 2025 enterprise accounts).

### Gotchas

- **Classic compute cost is incomplete on Databricks alone** — the EC2/VM bill lives on the cloud provider; Databricks only bills DBUs. Full cost = DBU_cost + underlying_VM_cost. Costly's AWS connector covers the EC2 side only if the customer connects both.
- **Serverless compute is complete on Databricks** — Databricks owns the VM, so `usage_quantity × list_price` is all-in.
- **`sku_name` encodes SKU + tier + region + cloud** — e.g. `PREMIUM_ALL_PURPOSE_COMPUTE_US_EAST_N_VIRGINIA`. Prefix match is fragile; use `billing_origin_product` for grouping.
- **Photon**: own SKU slug (`*_PHOTON`), not a flag on the base SKU. Missing Photon SKUs ⇒ undercount.
- **DLT tiers** (Core / Pro / Advanced) have different DBU multipliers; `billing_origin_product = 'DLT'` is coarse.
- **Serverless SQL + SQL Pro are separate**: SQL Pro uses classic compute with a premium DBU rate; SQL Serverless is fully managed. Separate SKUs.
- **Model Serving**: scale-to-zero is free but minimum cluster-up DBUs apply when scaled up; Provisioned Throughput has per-hour SKU.
- **Foundation Model APIs (Databricks-hosted Llama / DBRX / Mixtral)**: billed per-token via a different `billing_origin_product = 'FOUNDATION_MODEL'`.
- **Record-type handling**: `RESTATEMENT` and `RETRACTION` rows correct prior days; must dedupe by `(usage_date, sku_name, workspace_id, usage_metadata)` taking latest `ingestion_date`.
- **Custom tags propagation**: compute tags attach to DBU lines only for clusters created with `custom_tags`; SQL warehouse tags don't propagate to serverless queries until 2025-Q4 fix.
- **Multi-workspace accounts**: `workspace_id` partitions; accounts can have 100+ workspaces, each with its own admin model.
- **Regional SKUs**: AWS us-east-1 priced different from eu-west-1; sku_name embeds region.
- **Legacy usage-download CSV** — some columns renamed, and the CSV format changed twice in 2024. Workspace name disappeared for Unity-Catalog-enabled accounts.
- **Metastore system schemas**: must be explicitly enabled per-account; default is off on legacy accounts.
- **Service principal auth**: token must come from account-level OAuth (M2M); per-workspace tokens don't reach `system.billing`.
- **List price ≠ billed price**: system tables give list price; customer-specific discounts/commits only visible via Account Console's invoice view. Cloud Billing export (AWS/Azure/GCP) shows effective billed price.

## Schema / Fields Available

### `system.billing.usage`

| Column | Type | Notes |
|--------|------|-------|
| `account_id` | STRING | Databricks account |
| `workspace_id` | STRING | |
| `record_id` | STRING | Unique line-item id |
| `sku_name` | STRING | Full SKU slug |
| `cloud` | STRING | AWS / AZURE / GCP |
| `usage_start_time`, `usage_end_time` | TIMESTAMP | |
| `usage_date` | DATE | Partition key |
| `usage_unit` | STRING | DBU / STORAGE_MB / TOKEN |
| `usage_quantity` | DECIMAL | Raw quantity |
| `custom_tags` | MAP<string,string> | |
| `usage_metadata` | STRUCT | cluster_id / job_id / warehouse_id / notebook_id / endpoint_id / instance_pool_id / job_run_id / source_dashboard_id / node_type / run_name / endpoint_name |
| `identity_metadata` | STRUCT | run_as (user/SP email) |
| `record_type` | STRING | ORIGINAL / RETRACTION / RESTATEMENT |
| `ingestion_date` | DATE | |
| `billing_origin_product` | STRING | JOBS / ALL_PURPOSE / SQL / DLT / MODEL_SERVING / SERVERLESS_REAL_TIME_INFERENCE / FOUNDATION_MODEL / LAKEHOUSE_MONITORING / VECTOR_SEARCH / AUTOLOADER / APPS / INGESTION / DEFAULT_STORAGE / ONLINE_TABLE |
| `product_features` | STRUCT | is_serverless BOOLEAN, is_photon BOOLEAN, serving_type STRING |
| `usage_type` | STRING | COMPUTE_TIME / STORAGE_SPACE / NETWORK_BYTES / API_CALLS / TOKEN / GPU_TIME |

### `system.billing.list_prices`

| Column | Type | Notes |
|--------|------|-------|
| `sku_name`, `cloud` | STRING | |
| `currency_code` | STRING | USD typically |
| `price_start_time`, `price_end_time` | TIMESTAMP | NULL end_time = currently effective |
| `pricing` | STRUCT | default DECIMAL, effective_list.default, promotional.default |
| `usage_unit` | STRING | |

### `system.compute.clusters` (cluster metadata, 2025-Q2 GA)

| Column | Type | Notes |
|--------|------|-------|
| `account_id`, `workspace_id`, `cluster_id` | STRING | |
| `cluster_name`, `owned_by` | STRING | |
| `create_time`, `delete_time` | TIMESTAMP | |
| `driver_node_type`, `worker_node_type` | STRING | |
| `worker_count`, `min_autoscale_workers`, `max_autoscale_workers` | INT | |
| `auto_termination_minutes` | INT | |
| `enable_elastic_disk`, `aws_attributes`, `azure_attributes`, `gcp_attributes` | STRUCT | |
| `tags` | MAP<string,string> | |
| `runtime` | STRUCT (dbr_version, is_photon, ...) | |
| `change_time`, `change_date` | TIMESTAMP | SCD2 |

### `system.compute.warehouses`, `system.compute.node_types`, `system.compute.node_timeline`, `system.compute.warehouse_events`

Complementary tables for SQL warehouse and node-level analytics.

### `system.access.audit`

All admin/user actions; 365-day retention; attribution source for who spun up a cluster / ran a query.

### `system.lakeflow.*` (GA 2025 for Jobs)

Per-job metadata: `jobs`, `job_tasks`, `job_run_timeline`, `job_task_run_timeline` — enables per-job cost rollup joining on `usage_metadata.job_id`.

### `system.marketplace.*`, `system.serverless.*`, `system.ai.*` (newer schemas)

Expanding set; April 2026 adds `system.serverless.endpoint_metrics` for Model Serving utilization.

## Grouping Dimensions

- **Workspace** (`workspace_id`) — primary environment boundary.
- **Cluster** (`usage_metadata.cluster_id`) — per-cluster DBU rollup.
- **Job** (`usage_metadata.job_id` + `system.lakeflow.jobs.name`) — job-level cost.
- **Job Run** (`usage_metadata.job_run_id`) — per-execution.
- **SQL Warehouse** (`usage_metadata.warehouse_id`).
- **Model serving endpoint** (`usage_metadata.endpoint_id`, `endpoint_name`).
- **User / Service principal** (`identity_metadata.run_as`).
- **Notebook** (`usage_metadata.notebook_id`).
- **Pipeline (DLT)** (`usage_metadata.dlt_pipeline_id`).
- **Custom tags** — user-defined key-value on compute/job; richest attribution if customer has tag hygiene.
- **Billing origin product** — JOBS / ALL_PURPOSE / SQL / DLT / MODEL_SERVING / FOUNDATION_MODEL / VECTOR_SEARCH / APPS / LAKEHOUSE_MONITORING / DEFAULT_STORAGE.
- **SKU** (`sku_name`) — exact rate line.
- **Cloud** (AWS / AZURE / GCP) — multi-cloud orgs.
- **Region** — from sku_name suffix.
- **Serverless flag** (`product_features.is_serverless`) — classic vs serverless.
- **Photon flag** (`product_features.is_photon`) — with / without Photon.
- **Node type** — instance SKU (i3.2xlarge, Standard_DS3_v2, ...).
- **Record type** — filter RETRACTION / RESTATEMENT.

## Open-Source Tools Tracking This Platform

| Project | URL | Stars | License | Data source | What it does |
|---------|-----|-------|---------|-------------|--------------|
| **databricks-solutions / cost-optimization** | https://github.com/databricks-industry-solutions/cost-optimization | — | Apache 2.0 | system.billing + audit | Databricks' official cost-optimization accelerator (Delta Live Tables + dashboards). Use cases: untagged clusters, idle clusters, DBU anomalies. |
| **databricks-system-tables-cost-dashboard** | https://github.com/databricks/databricks-solutions-samples (various repos) | — | Apache 2.0 | system.billing | Official Lakeview dashboards — the reference UI for cost visibility. |
| **dbx / dbutils-utilities** | https://github.com/databrickslabs/dbx | ~470 | Apache 2.0 | — | CLI / DevOps; older, being replaced by `databricks-cli`. |
| **databricks-sdk-py** | https://github.com/databricks/databricks-sdk-py | ~480 | Apache 2.0 | REST APIs | Python SDK — wraps billing endpoints + system-table queries. |
| **databricks-sdk-go** | https://github.com/databricks/databricks-sdk-go | ~300 | Apache 2.0 | REST APIs | Go SDK. |
| **terraform-provider-databricks** | https://github.com/databricks/terraform-provider-databricks | ~500 | Apache 2.0 | — | Terraform provider. Useful for policy-as-code on cost guardrails. |
| **databricks-cost-monitor** (community) | https://github.com/datayoga-io/databricks-cost-monitor | ~80 | MIT | system.billing | Small SQL-based dashboard; good blueprint. |
| **Brickflow cost tags** | https://github.com/stikkireddy/brickflow | ~140 | Apache 2.0 | — | Opinionated Databricks workflow framework that auto-tags jobs. |
| **dbt-databricks** | https://github.com/databricks/dbt-databricks | ~290 | Apache 2.0 | — | dbt adapter; use for running cost-attribution models. |
| **databricks-labs / UCX** | https://github.com/databrickslabs/ucx | ~430 | Apache 2.0 | — | Unity Catalog migration assistant; surfaces cost-adjacent audit info. |
| **databricks-labs / ai-bi-helper** | https://github.com/databrickslabs/ai-bi-helper | — | Apache 2.0 | system.billing | AI/BI cost helper for Lakeview dashboards. |
| **Lakehouse Monitoring Bronze Silver Gold Cost Dashboard** (community) | multiple repos | — | — | system.billing + system.lakeflow | Canonical cost model examples. |
| **databricks-community / slashml Slack bot** | https://github.com/databricks-community (various) | — | — | system tables | Sends daily spend digests. |
| **Rudderstack Databricks cost notebook** | https://github.com/rudderlabs/rudder-databricks-cost-utils | — | MIT | system.billing | Small utilities. |
| **mlops-stacks cost templates** | https://github.com/databricks/mlops-stacks | ~230 | Apache 2.0 | — | MLOps tagging patterns. |

## How Competitors Handle This Platform

### Databricks native Cost Management + AI/BI Dashboards (https://docs.databricks.com/en/admin/account-settings/usage-detail-tags.html)

- Built-in UI: Account Console > Usage. Splits by workspace, SKU, tag. Lakeview dashboard templates (official samples in `databricks-industry-solutions/cost-optimization`) cover untagged clusters, job-level spend, cluster-efficiency, DLT pipeline trends.
- **Budgets** (GA 2024): per-account or per-workspace USD threshold with email alerts.
- **Cost Observability Dashboard** (Databricks Apps product, 2026 GA): an out-of-the-box app customers install with one click.

### Unravel (https://unravel.io)

- Deep DBX coverage: per-job cost, cluster right-sizing, Spark stage-level profiling (JVM / executor utilization). Recommends node-type changes and smaller autoscaling bounds.
- Pulls `system.billing.usage` + Spark event log.

### Revefi

- Unified SF/DBX/BQ; for DBX runs anomaly detection at job level and opens GitHub PRs against customer dbt/DBX repos with fix recommendations.

### Chaos Genius

- OSS; DBX support added 2024, covers system tables + anomaly detection.

### Keebo

- Added DBX beta 2025 — autoscaling SQL warehouse tuning analogous to their Snowflake product.

### Flexera / Finout / CloudZero / Vantage

- Generic FinOps; DBX tile ingests either the billable-usage CSV or the Azure/AWS cost export. Weak on per-job attribution vs. Unravel / Revefi.

### Grafana Cloud + Prometheus exporters

- Community exporters for `system.compute.*`; popular for ops teams.

### Sync Computing (https://synccomputing.com)

- Aspirational "autonomous cluster optimizer" that shapes Spark jobs for cost/performance via Gradient (proprietary). DBX-focused.

### Ambit / Bigeye / Monte Carlo

- Data-observability players who show DBX cost alongside data quality.

### Azure Cost Management + AWS Cost Explorer + GCP Billing

- Covers cloud VM portion of classic compute; blind to DBU-side attribution.

## Books / Published Material / FinOps Literature

- **"The Data Lakehouse: A Guide to the Modern Data Stack"** (O'Reilly, 2024) — Bill Inmon, Ranjeet Srivastava, and others.
- **"Delta Lake: The Definitive Guide"** (O'Reilly, 2024) — Denny Lee, Tristen Wentling, Prashanth Babu, Scott Haines.
- **"Databricks Certified Data Engineer Professional"** study guides — cover cost-aware architectural patterns.
- **Databricks Cost Management Whitepaper** — https://www.databricks.com/resources/ebook/cost-management (2024 edition).
- **Databricks Cost Observability Best Practices** — https://docs.databricks.com/en/admin/account-settings/usage-detail-tags.html.
- **Databricks Blog cost-optimization series**: https://www.databricks.com/blog/topics/cost-optimization — ~30 posts 2023-2026 covering serverless, Photon, autoscaling, tags.
- **Lakehouse Monitoring & Observability** — https://docs.databricks.com/en/lakehouse-monitoring/.
- **Miles Adkins / Bilal Aslam / Vini Jaiswal** (Databricks ex-employees) — blogs on DBX cost patterns.
- **Data + AI Summit (annual, June)** — extensive cost-optimization sessions; 2024 and 2025 recordings on Databricks YouTube: search "Cost Optimization with System Tables".
- **Cloud FinOps** (2nd ed, O'Reilly, 2023) — Ch. 13 covers DBX briefly.
- **FinOps Foundation** — Databricks-specific playbook (https://www.finops.org/wg/databricks) in progress.
- **Spark: The Definitive Guide** (O'Reilly, 2018) — still relevant for cluster sizing intuition.

## Vendor Documentation Crawl

- **Pricing**: https://www.databricks.com/product/pricing
- **AWS DBU rates**: https://www.databricks.com/product/aws-pricing
- **Azure DBU rates**: https://azure.microsoft.com/en-us/pricing/details/databricks/
- **GCP DBU rates**: https://www.databricks.com/product/gcp-pricing
- **Instance types + DBU multipliers**: https://www.databricks.com/product/pricing/product-pricing/instance-types
- **System tables (billing)**: https://docs.databricks.com/en/admin/system-tables/billing.html
- **System tables reference index**: https://docs.databricks.com/en/admin/system-tables/index.html
- **Enable system tables**: https://docs.databricks.com/en/admin/system-tables/index.html#enable-system-tables
- **Billable Usage REST API (legacy)**: https://docs.databricks.com/api/account/billableusage/download
- **Usage detail tags**: https://docs.databricks.com/en/admin/account-settings/usage-detail-tags.html
- **Budgets**: https://docs.databricks.com/en/admin/account-settings/budgets.html
- **Cost dashboards (Lakeview)**: https://www.databricks.com/blog/2024/05/13/monitor-and-manage-costs-databricks-lakehouse
- **Serverless compute pricing**: https://www.databricks.com/product/pricing/serverless-workflows
- **Foundation Model APIs pricing**: https://www.databricks.com/product/pricing/foundation-model-serving
- **Model Serving pricing**: https://www.databricks.com/product/pricing/model-serving
- **Vector Search pricing**: https://docs.databricks.com/en/generative-ai/vector-search.html#pricing
- **Cost optimization best practices**: https://docs.databricks.com/en/optimizations/cost.html
- **Release notes (2025)**: https://docs.databricks.com/en/release-notes/product/2025/index.html
- **Release notes (2026)**: https://docs.databricks.com/en/release-notes/product/2026/index.html
- **databricks-sdk-py docs**: https://databricks-sdk-py.readthedocs.io

Notable 2025-2026 changes:
- **Oct 2024**: `system.billing.usage` and `system.billing.list_prices` GA on AWS.
- **Q1 2025**: same on Azure + GCP.
- **Q2 2025**: `system.compute.clusters`, `warehouses`, `node_timeline` GA.
- **Jul 2025**: `system.lakeflow.jobs` GA — per-job metadata with runtime+task graph.
- **Nov 2025**: Serverless Jobs compute GA (new SKU `JOBS_SERVERLESS`).
- **Dec 2025**: Foundation Model APIs pay-per-token billing line GA in system.billing.
- **Feb 2026**: Lakehouse Monitoring moves from preview to GA pricing; bills under compute SKU of attached workspace.
- **Mar 2026**: Genie / Databricks AI/BI unified billing line (`APPS` origin product).
- **Apr 2026**: `system.serverless.endpoint_metrics` GA for Model Serving utilization.
- Deprecations: `/api/2.0/accounts/{id}/usage/download` marked legacy since 2024-Q4; new accounts cannot use it.

## Best Practices (synthesized)

1. **Pivot to `system.billing.usage` + `system.billing.list_prices`**. The REST CSV is legacy; system tables are the supported API.
2. **Dedupe by `record_id`** and prefer the latest `ingestion_date` per record; handle `RETRACTION` / `RESTATEMENT`.
3. **Tag everything**: cluster `custom_tags`, job `tags`, warehouse tags. Enforce via cluster policies + workspace policy.
4. **Split classic vs serverless** in reports — classic has underlying VM cost invisible to Databricks.
5. **Right-size clusters**: use `system.compute.node_timeline` + Spark event log utilization; shrink workers when p95 utilization < 50% for 14 days.
6. **Tune auto-termination**: 15-30 min default is typically too long for Jobs Compute; 5-10 min is safe. All-purpose needs judgement.
7. **Use Photon** where it accelerates >2× (Photon multiplier is ~2-2.9×; cost-neutral when speedup matches). Skip Photon on small point queries.
8. **Serverless for SQL BI** when customer has >10 concurrent users; classic warehouse is cheaper for single-user dev.
9. **Job orchestration over all-purpose**: running ELT on all-purpose compute costs ~2× Jobs Compute. Move every scheduled workload to Jobs Compute.
10. **DLT selectively**: Advanced tier is 1.8× Core. Use Core for simple ingestion, Advanced only when you need change data capture + data quality constraints.
11. **Model Serving scale-to-zero**: set `scale_to_zero_enabled=true` for non-prod endpoints.
12. **Foundation Models**: use Pay-per-Token for bursty; Provisioned Throughput only when p95 TPS > reservation break-even.
13. **Vector Search**: use storage-optimized for cold data, delta-sync for updated datasets.
14. **Budgets + alerts**: set workspace-level budgets in Account Console.
15. **Enable system tables on every account** — some customers haven't and rely on CSV download.
16. **Unity Catalog everywhere**: lineage table attribution is critical for cost-by-consumer reports.
17. **Shut off stale spark clusters**: the #1 root cause of DBX overspend is long-running all-purpose clusters never terminated.
18. **Audit `system.access.audit`** for who created the worst clusters.

## Costly's Current Connector Status

Source: `backend/app/services/connectors/databricks_connector.py` (~240 lines, thinnest of the three warehouses).

**Implemented:**
- `test_connection()` via account-level `/usage/download` + workspace `/clusters/list` fallback.
- `fetch_costs()` primary path: downloads account `/usage/download` CSV for the current + prior month, parses into daily records grouped by `(date, workspace, sku)`.
- Rough DBU → USD table (`DBU_PRICING` dict) covering ALL_PURPOSE, JOBS, SQL, DLT, MODEL_SERVING, INTERACTIVE, SERVERLESS_SQL, SERVERLESS_COMPUTE, FOUNDATION_MODEL. Rates are 2023 approximations.
- Category mapping: SQL → compute, DLT → transformation, MODEL_SERVING/FOUNDATION_MODEL → ml_serving; default compute.
- Fallback: workspace `/clusters/list` + heuristic `last_activity_time → uptime → DBU estimate`.

**Not implemented:**
- **System tables** — entire `system.billing.*` schema is unused.
- Photon SKUs (`*_PHOTON`) missing from the pricing dict.
- Per-edition tier differentiation (Standard / Premium / Enterprise).
- Per-region SKU detection.
- Per-cloud detection (AWS vs Azure vs GCP) — DBU prices assumed uniform.
- `usage_metadata` attribution: job_id, job_run_id, warehouse_id, endpoint_id, cluster_id, notebook_id, run_as user/SP.
- `custom_tags` attribution.
- Record-type dedup (RESTATEMENT handling).
- Cluster metadata (`system.compute.clusters`) for right-sizing.
- Job metadata (`system.lakeflow.jobs`) for per-job cost.
- Model Serving endpoint-level cost + utilization.
- Foundation Model per-model / per-token split.
- Vector Search, Databricks Apps, Lakehouse Monitoring, Autoloader, Online Tables coverage.
- Budgets API read.
- Serverless endpoint metrics.
- Audit log attribution (who created each cluster).
- Pricing overrides from credentials (for customers on committed-use discounts or EAs).
- Multi-workspace rollup beyond raw iteration (no workspace naming / grouping logic).

**Grade: C-.** Uses the deprecated CSV endpoint, misses every GA'd system table, and hard-codes DBU prices that are 1-2 years stale. Produces a rough order-of-magnitude number, not a DBA-grade breakdown.

## Gaps Relative to Best Practice

1. **Deprecated data source** — `/usage/download` is legacy; new customers may not have access, and the CSV format has shifted twice.
2. **No system.billing.usage × list_prices join** — the canonical supported path.
3. **No Photon** — Photon SKUs invisible, undercount spend.
4. **No serverless Jobs SKU** (GA Nov 2025) — new customers not covered.
5. **No per-edition rates** — Standard/Premium/Enterprise flat-mapped.
6. **No cloud/region SKU logic** — AWS assumed, EU/APAC priced wrong.
7. **No `custom_tags` attribution** — cannot show cost by team/env/project unless tags propagate on the legacy CSV (which is inconsistent).
8. **No per-job / per-endpoint / per-warehouse rollup.**
9. **No Foundation Model per-token split.**
10. **No Lakehouse Monitoring / Apps / Vector Search / Online Tables.**
11. **No record-type dedup** — RESTATEMENT rows double count.
12. **Hard-coded DBU prices** — stale; we need to read list_prices.
13. **No service-principal OAuth** — uses PAT (`access_token`); SP with M2M OAuth is the 2026 best practice.
14. **No workspace discovery** — single workspace URL; multi-workspace accounts only partially observed via the account-level CSV.
15. **No combined DBU + VM cost view** — leave it to the AWS connector, with no join.
16. **Synchronous `httpx` in async context** — blocks the event loop.
17. **No rate-limit handling / retries / pagination.**
18. **No data freshness** badge (CSV has ~24 h lag).
19. **No budgets API read.**
20. **No audit log / cluster-metadata attribution** to flag untagged or ownerless clusters.

## Roadmap

### Near-term (next 2 weeks)

- Pivot primary path to `system.billing.usage` × `system.billing.list_prices` via SQL Warehouse Statement Execution API. Keep CSV as fallback.
- Add Photon SKUs to the pricing dict and `billing_origin_product`-based category mapping.
- Add per-edition / per-region / per-cloud tier inference from `sku_name` patterns.
- Add `custom_tags` attribution.
- Add record-type dedup.
- Add workspace name resolution.

### Medium-term (next 4-6 weeks)

- Per-job rollup via `system.lakeflow.jobs` + `usage_metadata.job_id` join.
- Per-cluster rollup via `system.compute.clusters`.
- Per-endpoint Model Serving rollup + scale-to-zero detection.
- Foundation Model per-token split.
- Vector Search + Lakehouse Monitoring + Apps coverage.
- Multi-workspace account iteration.
- Service-principal OAuth auth (M2M).
- Budgets read-only integration.
- Async `httpx.AsyncClient` migration.

### Long-term (2-3 months)

- Right-sizing recommendations from `system.compute.node_timeline` (utilization-based).
- Auto-termination tuning recommender.
- Photon ROI analysis: which jobs actually run >2× faster?
- Write-back actions (behind approval): update cluster policies, set auto-termination, change DLT tier, enable scale-to-zero on model endpoints.
- DBU + underlying VM consolidated view by joining Databricks `system.billing.usage` with AWS Cost Explorer data on `cluster_id` / `instance_id`.
- "Databricks Expert" agent (per `costly-expert-agents.md`).
- Anomaly detection + Slack/email alerts specifically for DBX.
- Integration with cluster-policy templates to enforce tagging / sizing.
- Lakeview dashboard templates ingested into Costly for a "DBX Cost Console" section.

## Change Log

- 2026-04-24: Initial knowledge-base created by overnight research run.
