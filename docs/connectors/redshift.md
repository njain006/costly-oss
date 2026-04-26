# Redshift — Connector Knowledge Base

_Last updated: 2026-04-23 (lane/redshift initial implementation)_

## TL;DR

Amazon Redshift was previously rolled up inside Costly's AWS Cost Explorer umbrella as a single `Amazon Redshift` service line — no cluster attribution, no Serverless RPU split, no Spectrum/Concurrency-Scaling breakout. This new dedicated connector pulls from Redshift's own system tables via the Data API and adds the control-plane calls (`describe_clusters`) needed to resolve node type/count pricing. Grade today: **B (covers the four main compute surfaces + managed storage, provisioned + serverless, with pricing overrides and test coverage).** Top gaps: Reserved-node amortisation is not modelled (we use on-demand list price), query-level Spectrum attribution still requires joining `SYS_EXTERNAL_QUERY_DETAIL` to `SYS_QUERY_HISTORY`, and RA3 managed storage is currently only pulled for Serverless workgroups (provisioned RA3 storage coming next).

## Pricing Model (from vendor)

Redshift in 2026 has four parallel billing lines. Prices below are **us-east-1 on-demand list** unless marked.

### Provisioned (RA3 / DC2)

Per-node-hour price × nodes × hours the cluster is unpaused. Paused clusters cost $0 for compute but customers on **Reserved Node** plans still pay the prepaid rate.

| Family | Node type | vCPU | Memory | Managed storage | $/node/hour | 1-yr RI (no upfront) | 3-yr RI (all upfront) |
|--------|-----------|------|--------|-----------------|-------------|----------------------|------------------------|
| RA3 | ra3.large | 2 | 16 GB | up to 32 TB/node | $0.543 | ~$0.38 (30% off) | ~$0.22 (60% off) |
| RA3 | ra3.xlplus | 4 | 32 GB | up to 32 TB/node | $1.086 | ~$0.76 | ~$0.44 |
| RA3 | ra3.4xlarge | 12 | 96 GB | up to 128 TB/node | $3.26 | ~$2.28 | ~$1.30 |
| RA3 | ra3.16xlarge | 48 | 384 GB | up to 128 TB/node | $13.04 | ~$9.13 | ~$5.22 |
| DC2 (legacy) | dc2.large | 2 | 15 GB | 160 GB SSD | $0.25 | ~$0.18 | ~$0.10 |
| DC2 (legacy) | dc2.8xlarge | 32 | 244 GB | 2.56 TB SSD | $4.80 | ~$3.36 | ~$1.92 |
| DS2 (deprecated) | ds2.xlarge | 4 | 31 GB | 2 TB HDD | $0.85 | ~$0.60 | ~$0.34 |
| DS2 (deprecated) | ds2.8xlarge | 36 | 244 GB | 16 TB HDD | $6.80 | ~$4.76 | ~$2.72 |

- **RA3** is the modern default — decouples compute from managed storage ($0.024/GB-month). Nodes only hold "hot" data; cold data lives in Redshift Managed Storage (RMS).
- **DC2** is dense-compute SSD; still sold but deprecated for new workloads.
- **DS2** is dense-storage HDD; no longer sold, legacy accounts only.
- **Reserved Nodes**: 1-year (~30% off) and 3-year (~60% off) terms. Billing is flat; underutilisation does not refund.
- **Regional deltas**: us-east-1 baseline; us-west-2 same; eu-west-1 ~+5%; ap-southeast-2 ~+15%.

### Serverless

- **$0.375 per RPU-hour** base (us-east-1). 1 RPU ≈ 1 vCPU + memory of a reference RA3 node.
- **60-second minimum** charged per activation (avoids pennies for single-query workloads).
- **Base capacity**: configurable between 8 and 512 RPU. Billing scales linearly.
- **Max capacity** cap: sets a ceiling on concurrency-triggered scale-out.
- **Managed storage**: same $0.024/GB-month as RA3.
- **Free trial**: $300 credit for 90 days on new accounts.

### Spectrum

- **$5 per TB scanned** against external tables (S3 + Glue Catalog). Same rate as Athena.
- 10 MB minimum per query.
- Free if running against data in Redshift Managed Storage (that's just a regular query).

### Concurrency Scaling (CS)

- **1 free hour per day per cluster**. Stored in `STL_CONCURRENCY_SCALING_USAGE.free_usage_in_seconds`.
- Beyond the free tier: billed per-second at the main cluster's on-demand rate (i.e. `node_rate × node_count × billable_seconds / 3600`).
- CS only activates when queries queue beyond main-cluster capacity; it's transparent to the client.

### Managed Storage (RA3 / Serverless)

- **$0.024 per GB-month** (us-east-1).
- Automatic tiering to S3 — no customer lever.
- Surfaced in `SYS_SERVERLESS_USAGE.storage_in_mb` for Serverless; `STV_NODE_STORAGE_CAPACITY` + `SVV_TABLE_INFO` for provisioned RA3 (not yet pulled — roadmap).

### Data Transfer

- Between Redshift and S3 in same region: free.
- Cross-region: EC2 egress rates apply (~$0.02/GB within US, $0.09/GB to internet).

### Snapshots

- Manual: $0.024/GB-month (same as managed storage).
- Automated: included with the cluster up to the configured retention period.

Sources:
- https://aws.amazon.com/redshift/pricing/
- https://aws.amazon.com/redshift/faqs/
- https://docs.aws.amazon.com/redshift/latest/mgmt/working-with-clusters.html

## Billing / Usage Data Sources

### Primary (this connector)

**`SYS_QUERY_HISTORY`** — canonical per-query record on provisioned clusters. Replaces the legacy `STL_QUERY`.

```sql
SELECT
  start_time,
  end_time,
  user_id,
  database_name,
  query_id,
  query_type,
  execution_time,        -- µs, excludes queue/compile
  elapsed_time,          -- µs, includes everything
  queue_time,
  COALESCE(compute_type, 'main') AS compute_type,  -- 'main' vs 'cs'
  query_label,           -- free-form tag set via SET query_label
  status
FROM SYS_QUERY_HISTORY
WHERE start_time >= :start_ts
  AND start_time <  :end_ts
  AND status = 'success';
```

Permissions: `SELECT` on `SYS_QUERY_HISTORY` (requires `ACCESS SYSTEM TABLE` or `SYSLOG ACCESS UNRESTRICTED` depending on Redshift version).

**`SYS_SERVERLESS_USAGE`** — per-minute Serverless billing.

```sql
SELECT
  start_time,
  end_time,
  workgroup_name,
  charged_seconds,       -- wall-clock seconds billed (60s min enforced)
  charged_rpu_seconds,   -- RPU × seconds; divide by 3600 for RPU-hours
  storage_in_mb          -- managed storage at the end of the window
FROM SYS_SERVERLESS_USAGE
WHERE start_time >= :start_ts
  AND start_time <  :end_ts;
```

**`SYS_EXTERNAL_QUERY_DETAIL`** — Spectrum scan detail, one row per query.

```sql
SELECT
  start_time, user_id, query_id,
  SUM(total_bytes_external) AS bytes_scanned
FROM SYS_EXTERNAL_QUERY_DETAIL
WHERE start_time >= :start_ts
  AND start_time <  :end_ts
GROUP BY 1, 2, 3;
```

**`STL_CONCURRENCY_SCALING_USAGE`** — CS activations with billable vs free seconds already split.

```sql
SELECT
  start_time,
  cluster_identifier,
  SUM(usage_in_seconds)       AS billable_seconds,
  SUM(free_usage_in_seconds)  AS free_seconds
FROM STL_CONCURRENCY_SCALING_USAGE
WHERE start_time >= :start_ts
  AND start_time <  :end_ts
GROUP BY 1, 2;
```

**`describe_clusters` (boto3 `redshift` client)** — control plane. Gives `NodeType`, `NumberOfNodes`, `ClusterStatus` (paused/available), `ClusterCreateTime`. We use it to resolve pricing when `node_type` is not in credentials.

**`describe_workgroups` / `get_workgroup`** — Serverless control plane. Base/max capacity, parameter groups, last-billing RPU hours.

### Secondary / Fallback

- **AWS Cost Explorer** — `Amazon Redshift` service grouping. Gives actual billed USD (retroactively reconciled) but no cluster / query attribution. This is the source still surfaced by the legacy AWS umbrella connector; Costly's new dedicated connector complements rather than replaces it.
- **CloudTrail** — operational events (pause, resume, resize, delete). Useful for detecting usage gaps.
- **CloudWatch metrics** — `CPUUtilization`, `DatabaseConnections`, `PercentageDiskSpaceUsed`, `QueryDuration`. Good for right-sizing signals; not priced.
- **Redshift Query Editor v2 history** — duplicates `SYS_QUERY_HISTORY`; no extra data.
- **AWS CUR (Cost & Usage Report)** — row-level billing; joins to `resource_id` (cluster ARN). Better than Cost Explorer for BI flexibility but delivered to S3 asynchronously.

### Gotchas

- **`SYS_QUERY_HISTORY` vs `STL_QUERY`**: `STL_QUERY` is legacy (pre-RA3) and only 7 days of retention. `SYS_QUERY_HISTORY` is 7 days by default on provisioned, longer on Serverless. Do not join across them.
- **Superuser vs regular user visibility**: non-superusers only see their own rows. The Data API DB user must be granted `SYSLOG ACCESS UNRESTRICTED` (Redshift v1.0.43931+) to see all queries.
- **Paused clusters**: `SYS_QUERY_HISTORY` still accessible via Data API on a paused cluster if the customer uses IAM auth; but compute cost for that day should be 0. We don't currently pull the `ClusterStatus` timeline and so may over-attribute on paused days.
- **Concurrency scaling attribution**: CS queries appear in `SYS_QUERY_HISTORY` with `compute_type='cs'`; their per-query execution_time should NOT be multiplied by main-cluster rate twice. Our connector surfaces CS cost from `STL_CONCURRENCY_SCALING_USAGE` (billable seconds) and leaves CS query rows in `SYS_QUERY_HISTORY` as metadata (compute_type='cs') without re-pricing.
- **Spectrum double-count**: A Spectrum query has compute time on the main cluster AND bytes_scanned on S3. Our connector emits two rows (compute + spectrum). Clients should not sum them naïvely — they already represent distinct SKUs.
- **Reserved Nodes not detected**: Our pricing applies on-demand list; customers with RIs will see inflated numbers until we pull `describe_reserved_nodes`.
- **Serverless 60-second minimum**: already enforced by Redshift in `charged_seconds`. Do not re-apply.
- **Redshift Data API result pagination**: `get_statement_result` uses `NextToken`; our client pages automatically. For very large result sets (>10K rows), we may need to add `StatementName` de-duping.
- **Multi-region**: the Data API client is region-pinned. Multi-cluster customers in different regions need one connection per region.
- **Timestamps in UTC**: Redshift system tables are always UTC; our `TO_CHAR(start_time, 'YYYY-MM-DD')` preserves that.
- **Node type changes mid-window**: if a cluster is resized (e.g. ra3.xlplus → ra3.4xlarge), the rate we apply is the current node type at fetch time. Historical attribution will be slightly off for the resize day.
- **Enhanced VPC routing** doesn't change cost directly but can push S3 data through NAT gateways (billed by the NAT, not Redshift).
- **RA3 managed storage** is cross-cluster in the same account — the storage number in `SVV_TABLE_INFO` can be attributed to the cluster that owns the table; for RMS total, query the `STV_DISK_READ_SPEEDS` + `STV_NODE_STORAGE_CAPACITY` views.

## Schema / Fields Available

### `SYS_QUERY_HISTORY` (core)

| Column | Type | Notes |
|--------|------|-------|
| `user_id` | INT | System user id; join to `PG_USER` for the name |
| `query_id` | BIGINT | Unique per cluster |
| `transaction_id` | BIGINT | Groups multi-statement transactions |
| `session_id` | INT | |
| `database_name` | VARCHAR | |
| `query_type` | VARCHAR | SELECT, INSERT, UPDATE, DELETE, COPY, UNLOAD, DDL, UTILITY |
| `status` | VARCHAR | success, failed, canceled, running |
| `start_time`, `end_time` | TIMESTAMP | UTC |
| `elapsed_time`, `execution_time`, `queue_time`, `planning_time`, `lock_wait_time` | BIGINT (µs) | |
| `returned_rows`, `returned_bytes` | BIGINT | |
| `compute_type` | VARCHAR | `main`, `cs` |
| `query_label` | VARCHAR | Free-form tag via `SET query_label` |
| `query_text` | VARCHAR(8000) | Truncated; join to `SYS_QUERY_TEXT` for full |
| `result_cache_hit` | BOOLEAN | |

### `SYS_SERVERLESS_USAGE`

| Column | Type | Notes |
|--------|------|-------|
| `workgroup_name` | VARCHAR | |
| `start_time`, `end_time` | TIMESTAMP | 1-minute windows |
| `compute_seconds` | BIGINT | Wall-clock |
| `charged_seconds` | BIGINT | After 60s minimum |
| `compute_capacity` | INT | RPU at the time |
| `charged_rpu_seconds` | BIGINT | Primary billing unit |
| `storage_in_mb` | BIGINT | Managed storage snapshot |

### `SYS_EXTERNAL_QUERY_DETAIL`

| Column | Notes |
|--------|-------|
| `query_id`, `segment`, `step` | |
| `table_name`, `schema_name`, `database_name` | External table coordinates |
| `total_bytes_external` | Primary scan-cost unit |
| `total_partitions_scanned`, `total_partitions_skipped` | |
| `total_bytes_returned` | Post-pushdown |

### `STL_CONCURRENCY_SCALING_USAGE`

| Column | Notes |
|--------|-------|
| `xid`, `query`, `start_time`, `end_time` | |
| `usage_in_seconds` | Billable seconds (beyond free tier) |
| `free_usage_in_seconds` | Seconds absorbed by the 1-hr/day free pool |

### `describe_clusters` (control plane)

| Field | Notes |
|-------|-------|
| `ClusterIdentifier`, `ClusterStatus` | status in {available, paused, modifying, …} |
| `NodeType`, `NumberOfNodes` | Primary pricing inputs |
| `ClusterCreateTime` | |
| `Encrypted`, `KmsKeyId` | |
| `AvailabilityZone`, `Endpoint.Address`, `Endpoint.Port` | |
| `ClusterSubnetGroupName`, `VpcId` | |
| `ReservedNodeExchangeStatus` | Signals reserved-node state |

## Grouping Dimensions

- **Cluster / Workgroup** — primary tenant of spend.
- **User** — `user_id` → `PG_USER.usename`. Good for human attribution, not for service accounts.
- **Database** — `database_name`. Often 1:1 with tenant on multi-tenant warehouses.
- **Query label** — `SET query_label` is the Redshift-native tag. Populated by dbt (`--query-comment`), Airflow (`extra_kwargs`), and Looker (LookML labels).
- **Query type** — SELECT vs DML vs COPY/UNLOAD for BI-vs-ETL split.
- **Compute type** — `main` / `cs` / `Serverless` / `Spectrum` — surfaces the pricing lane.
- **Node type + count** — pricing key on provisioned.
- **Workgroup base capacity** — pricing key on Serverless.
- **Reservation status** — not yet captured; would flip the rate from on-demand to RI.

## Open-Source Tools Tracking This Platform

| Project | URL | Stars | License | Data source | What it does |
|---------|-----|-------|---------|-------------|--------------|
| **amazon-redshift-utils** (AWS) | https://github.com/awslabs/amazon-redshift-utils | ~2.4K | Apache 2.0 | system tables | Official admin scripts: cluster diagnostics, slow-query finder, vacuum analyzer. |
| **redshift-diag-tools** | https://github.com/awslabs/amazon-redshift-monitoring | ~180 | Apache 2.0 | system tables | Daily diagnostic snapshot SQL pack. |
| **redset** (Amazon open-sourced trace of 200M queries) | https://github.com/amazon-science/redset | ~300 | Apache 2.0 | workload trace | Workload-level cost modelling dataset. |
| **redshift-cost-dashboards** (community) | various | — | mixed | system tables | Tableau/Quicksight/Grafana templates. |
| **dbt-redshift** | https://github.com/dbt-labs/dbt-redshift | ~200 | Apache 2.0 | — | dbt adapter; includes cost-conscious materialization configs. |
| **dbt_artifacts** | https://github.com/brooklyn-data/dbt_artifacts | ~320 | Apache 2.0 | dbt artifacts | Run history; Redshift-specific cost not surfaced but query IDs match `query_label`. |
| **aws-samples/amazon-redshift-config-monitoring** | https://github.com/aws-samples/amazon-redshift-config-monitoring | ~70 | MIT | CloudWatch + system | Config drift + resource utilization. |
| **redshift-slack-alerts** | community | — | MIT | CloudWatch | Long-running query alerts. |
| **awswrangler.redshift** | https://github.com/aws/aws-sdk-pandas | ~4K | Apache 2.0 | — | Python helper that sets query labels automatically — useful attribution upstream. |

## How Competitors Handle This Platform

### Vantage (https://vantage.sh)

- Bundles Redshift under AWS Cost Explorer. Per-cluster breakout via resource tags. No per-query attribution. On-demand vs RI surfacing is limited to the Cost Explorer aggregation.

### CloudZero (https://cloudzero.com)

- Pulls CUR + tags. Good for chargeback to business units; weak on query-level.

### AWS Cost Anomaly Detection (built-in)

- Free, native. Alerts on unusual Redshift spend deltas. No attribution.

### AWS Trusted Advisor

- Flags idle clusters; does not model cost savings for Serverless migration.

### Redshift Serverless "Cost & Usage" console tab

- Native per-workgroup view; decent for single-workgroup customers. Weak at multi-workgroup portfolios.

### Select Star / Unravel

- Query-level attribution + recommendation engine (compression, distribution keys, sort keys). Unravel is the closest to a "Redshift Expert" product.

### Keebo

- Auto-scaling / auto-shut-down for Redshift (beta, 2025). Cost-saving layer not a cost observability layer.

### Chaos Genius

- OSS Snowflake-first; Redshift support in progress.

### Revefi

- Unified SF/DBX/BQ/Redshift. For Redshift specifically, does per-query cost + workload isolation alerts.

### datafold / dbt Cloud Discovery

- Redshift cost surfaced at the dbt model level via `query_label`; no standalone Redshift view.

## Books / Published Material / FinOps Literature

- **"Cloud FinOps"** (2nd ed, O'Reilly, 2023) — Storment + Fuller. Ch. 11 covers warehouse FinOps including Redshift.
- **"Amazon Redshift: The Definitive Guide"** (O'Reilly, 2023) — Rajesh Francis, Rajiv Gupta, Milind Oke. Ch. 9 on pricing & optimization.
- **AWS Well-Architected — Cost Optimization pillar for Redshift** — https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html.
- **AWS Blog "Optimizing Amazon Redshift performance"** series (2024-2025).
- **re:Invent 2024 — ANT343 "Optimizing cost on Redshift Serverless"** — recorded session.
- **FinOps Foundation — AWS Data Warehouses playbook** (2024 community WG).
- **"Migrating from Redshift DC2 to RA3"** — official AWS whitepaper.
- **Redshift release notes**: https://docs.aws.amazon.com/redshift/latest/mgmt/cluster-versions.html.
- **Serverless workload management**: https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-workload-management.html.

## Vendor Documentation Crawl

- **Pricing overview**: https://aws.amazon.com/redshift/pricing/
- **Serverless pricing**: https://aws.amazon.com/redshift/pricing/#Amazon_Redshift_Serverless
- **Spectrum pricing**: https://aws.amazon.com/redshift/pricing/#Redshift_Spectrum_Pricing
- **Concurrency Scaling**: https://aws.amazon.com/redshift/pricing/#Concurrency_Scaling_Pricing
- **Reserved Nodes**: https://aws.amazon.com/redshift/pricing/#Reserved_Instance_pricing
- **Managed Storage**: https://aws.amazon.com/redshift/pricing/#Managed_storage_pricing
- **Data API**: https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html
- **`SYS_QUERY_HISTORY`**: https://docs.aws.amazon.com/redshift/latest/dg/sys-query-history.html
- **`SYS_SERVERLESS_USAGE`**: https://docs.aws.amazon.com/redshift/latest/dg/SYS_SERVERLESS_USAGE.html
- **`SYS_EXTERNAL_QUERY_DETAIL`**: https://docs.aws.amazon.com/redshift/latest/dg/SYS_EXTERNAL_QUERY_DETAIL.html
- **`STL_CONCURRENCY_SCALING_USAGE`**: https://docs.aws.amazon.com/redshift/latest/dg/r_STL_CONCURRENCY_SCALING_USAGE.html
- **`describe_clusters`**: https://docs.aws.amazon.com/redshift/latest/APIReference/API_DescribeClusters.html
- **`get_workgroup`**: https://docs.aws.amazon.com/redshift-serverless/latest/APIReference/API_GetWorkgroup.html
- **IAM auth for Data API**: https://docs.aws.amazon.com/redshift/latest/mgmt/data-api-access.html
- **Query labels (`SET query_label`)**: https://docs.aws.amazon.com/redshift/latest/dg/r_query_label.html

Notable 2025-2026 changes:
- **Jan 2025**: Zero-ETL from Aurora MySQL / DynamoDB GA — surfaces as `query_type='ZERO_ETL'` in SYS_QUERY_HISTORY.
- **Mar 2025**: Serverless RPU pricing reduced from $0.42 → $0.375/hr in us-east-1.
- **Sep 2025**: RA3 base price cuts across families (4xlarge from $3.48 → $3.26).
- **Nov 2025**: Spectrum auto-materialized cache rolled out (no pricing change, but `result_cache_hit` now populates on external queries).
- **Feb 2026**: Concurrency scaling free-tier doubled in preview regions (2 hrs/day); not yet in us-east-1.
- **Apr 2026**: Data API statement result pagination default page size bumped from 1000 → 5000 rows.

## Best Practices (synthesized)

1. **Always set `SET query_label`** upstream (dbt `--query-comment`, Airflow template, Looker LookML). Without it, attribution is limited to `user_id`.
2. **Prefer RA3 over DC2**. Managed storage decouples compute, and RA3 xlplus is a strictly better DC2 large.
3. **Pause dev clusters** when idle. `describe_clusters` exposes the status; schedule via EventBridge.
4. **Use Reserved Nodes for predictable baselines** — 3-yr all-upfront saves ~60%.
5. **Migrate bursty workloads to Serverless** — avoids always-on main-cluster cost.
6. **Right-size Serverless base capacity**: start at 8 RPU, observe `charged_rpu_seconds / charged_seconds` (effective RPU); raise only if consistently at the base.
7. **Enable Concurrency Scaling** but set `max_concurrency_scaling_clusters` to 1 if you can tolerate queueing — CS beyond the free hour is expensive.
8. **Use Spectrum for cold, infrequently-queried data** — cheaper than keeping on RMS if queried < weekly.
9. **Vacuum + analyze** keeps sort keys effective, reducing scanned bytes on both main compute and Spectrum.
10. **Result cache** on Serverless is enabled by default; identical queries within 24 h are free. Watch `result_cache_hit` on `SYS_QUERY_HISTORY`.
11. **Zero-ETL from Aurora** is free in ingestion; you only pay for the Redshift-side storage + query.
12. **Auto WLM** over manual queue configuration for most workloads — the autotuner allocates memory per slot type.
13. **Short-query acceleration (SQA)** is on by default; fires for queries < ~20s. Free, but `execution_time` will still show on the main path.
14. **COPY in bulk** — small COPY statements are the #1 cause of high utility-query compute on ETL clusters.
15. **UNLOAD to Parquet with `MANIFEST`** — reusable by Athena/Spectrum/EMR without re-ingesting.
16. **Monitor `PercentageDiskSpaceUsed` CloudWatch** — > 90% triggers query failures on DC2; RA3 autoscales to RMS so less critical.

## Costly's Current Connector Status

Source: `backend/app/services/connectors/redshift_connector.py`

**Implemented (lane/redshift, v0):**
- Data API execute/describe/get_statement_result pagination wrapper.
- Provisioned query-level cost via `SYS_QUERY_HISTORY` × node_rate × node_count.
- Concurrency Scaling cost via `STL_CONCURRENCY_SCALING_USAGE` (billable seconds only; free seconds surfaced in metadata).
- Serverless RPU-hour cost via `SYS_SERVERLESS_USAGE`.
- Serverless managed storage daily proration via `storage_in_mb`.
- Spectrum cost via `SYS_EXTERNAL_QUERY_DETAIL.total_bytes_external`.
- `describe_clusters` fallback when `node_type` / `node_count` not in credentials.
- `pricing_overrides` for: per-node-hour, serverless RPU-hour, spectrum per-TB, managed-storage per-GB-month, concurrency-scaling free hours, global discount_pct.
- Structured `RedshiftError` with actionable hints for AccessDenied / NotFound / ValidationException.
- Full parametrized test coverage (47 tests): instantiation, pricing overrides, provisioned, serverless, CS, Spectrum, error paths, helpers.

**Not implemented:**
- Reserved Node detection + rate flip.
- Provisioned RA3 managed storage from `SVV_TABLE_INFO` + `STV_NODE_STORAGE_CAPACITY`.
- Snapshot cost (manual vs automated).
- Cross-region data transfer.
- `SYS_QUERY_TEXT` join (full query text beyond 8000 char truncation).
- `result_cache_hit` filter — currently include cache hits at zero-execution-time (so they drop naturally).
- Zero-ETL query type split.
- Cluster status timeline (paused vs available) to avoid double-counting paused days.
- Workgroup parameter group / base capacity recommender.

**Grade: B.** Correct on the four major compute surfaces and managed storage for Serverless; pricing overrides + discount_pct work end-to-end; permission errors degrade gracefully instead of raising. Missing: RI amortisation, provisioned RMS, and a cluster-uptime timeline.

## Gaps Relative to Best Practice

1. **No Reserved Node handling** — on-demand rate applied even to RI-heavy customers (the #1 source of over-reporting for mature accounts).
2. **Provisioned RA3 managed storage not pulled** — only Serverless storage surfaced.
3. **No cluster status timeline** — paused/modifying days attributed as if available.
4. **No snapshot cost** — manual snapshots on long-retention clusters can be 10-20% of spend.
5. **No result-cache exclusion** — cache hits should be explicitly zero-valued, not silently dropped.
6. **No tag-based attribution** — we read `query_label` but don't read cluster-level AWS tags (team/env/cost-center).
7. **No Spectrum-by-external-table breakdown** — only aggregated per day.
8. **No recommendation engine** — Redshift-specific tips (RA3 migration, SQA, SQL Advisor) not surfaced.
9. **Regional pricing not applied** — us-east-1 list applied everywhere.
10. **Synchronous boto3 client** — fine at day-30 scale; may need async at day-365 reporting.

## Roadmap

### Near-term (next 2 weeks)

- Add Reserved-Node detection via `describe_reserved_nodes` + rate flip (on-demand / 1-yr / 3-yr).
- Pull provisioned RA3 managed storage (`SVV_TABLE_INFO` + `STV_NODE_STORAGE_CAPACITY`).
- Add cluster-status timeline via `describe_cluster_events` (pause/resume) to zero-out paused days.
- Filter `result_cache_hit = true` out of compute attribution.
- Pull cluster-level AWS resource tags → map to `UnifiedCost.team`.

### Medium-term (next 4-6 weeks)

- Snapshot cost (manual + automated retention).
- Per-external-table Spectrum breakdown.
- Zero-ETL usage split.
- Regional pricing table.
- Query-text join (`SYS_QUERY_TEXT`) for query-fingerprint cost roll-up.
- Cost Explorer cross-check (ground-truth USD) — flag when our estimate drifts > 10%.

### Long-term (2-3 months)

- "Redshift Expert" agent (per `costly-expert-agents.md`) — SQA hit-rate analysis, distribution-key / sort-key recommendations, RA3 migration modelling, Serverless-vs-provisioned break-even.
- Workload Management (WLM) queue-depth from `STV_WLM_QUERY_STATE` + `STV_WLM_QUERY_QUEUE_STATE`.
- Actionable auto-pause / auto-resize — write-back path through `modify_cluster` (approval required).
- Unravel-style compression / distribution-key advisor.
- Workload fingerprinting on `query_text` hash for de-duping routine-vs-ad-hoc.

## Change Log

- 2026-04-23: Initial dedicated `RedshiftConnector` — split from the AWS umbrella, added Data API wrapper, provisioned + serverless + Spectrum + CS coverage, 47-test pytest suite.

## Re-recording contract fixtures

Contract tests for this connector live at `backend/tests/contract/test_redshift.py`
and load JSON fixtures from `backend/tests/fixtures/redshift/`. The fixtures are
intentionally hand-written from the public API docs so they don't leak any
real account data — every contributor can run the suite offline.

To capture fresh fixtures against a real Redshift account when the API
schema drifts, set credentials and run pytest with `--record-mode=once`:

```bash
cd backend
# Redshift fixtures pin the boto3 redshift-data shape — capture via `aws redshift-data get-statement-result --id <Id>` \
    pytest tests/contract/test_redshift.py --record-mode=once
```

Then sanitize the captured JSON (strip account ids, emails, tokens) before
committing. See `docs/testing/contract-tests.md` for the philosophy.


