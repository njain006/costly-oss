# Snowflake Billing & Cost Expert Knowledge Base

## Credit-Based Pricing Model

Snowflake bills on **credits**, not compute hours. Everything maps back to credits.

### Credit Prices by Edition (per credit)
| Edition | On-Demand | Typical Capacity Contract |
|---------|-----------|--------------------------|
| Standard | $2.00 | $1.40–1.70 |
| Enterprise | $3.00 | $1.90–2.50 |
| Business Critical | $4.00 | $2.80–3.50 |
| VPS (Virtual Private) | $5.00+ | $3.50–4.50 |

**Key insight:** Most mid-market customers pay $2.00–2.80/credit on Enterprise capacity contracts. The on-demand rate is a ceiling — almost nobody pays it at scale. Always ask what the customer's actual credit price is.

### How to Find Your Actual Credit Price
```sql
-- Option 1: RATE_SHEET_DAILY (Organization-level, requires ORGADMIN)
SELECT DATE, SERVICE_TYPE, EFFECTIVE_RATE, CURRENCY
FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY
WHERE SERVICE_TYPE = 'COMPUTE'
ORDER BY DATE DESC LIMIT 30;

-- Option 2: Check contract details in Snowflake UI
-- Account > Billing & Terms > Usage Rates
```

## Compute Costs (The Big One — Usually 60-80% of Bill)

### Warehouse Sizing
| Size | Credits/Hour | Nodes | Typical Use |
|------|-------------|-------|-------------|
| X-Small | 1 | 1 | Dev, ad-hoc |
| Small | 2 | 2 | Light ETL |
| Medium | 4 | 4 | Standard workloads |
| Large | 8 | 8 | Heavy ETL, BI |
| X-Large | 16 | 16 | Large transforms |
| 2XL | 32 | 32 | Very heavy |
| 3XL | 64 | 64 | Rare |
| 4XL | 128 | 128 | Very rare |

### Billing Rules (Critical Gotchas)
1. **Per-second billing with 60-second minimum**: If a query takes 5 seconds, you pay for 60 seconds. If it takes 61 seconds, you pay for 61 seconds. This means many short queries on a suspended warehouse pay the 60s minimum each time it resumes.

2. **Auto-suspend timing**: When a warehouse suspends, you're still billed for the remaining seconds of that minute. Setting auto-suspend to 60 seconds is NOT 1 minute of idle — it's 1 minute after the last query completes, then billing stops.

3. **Resume cost**: When a warehouse resumes from suspended state, there's the 60-second minimum. If you have auto-suspend=60s and queries arrive every 2 minutes, you're paying the resume cost every time.

4. **Multi-cluster warehouses**: Each cluster runs at the full warehouse size. A Medium multi-cluster with max_clusters=3 can burn 12 credits/hour (4 × 3). The scaling policy (STANDARD vs ECONOMY) dramatically affects cost:
   - STANDARD: Starts new cluster if ANY query is queued
   - ECONOMY: Starts new cluster only if system estimates 6+ minutes of work

### Auto-Suspend Optimization
```
Ideal auto-suspend = P90 inter-query arrival time

If queries come every 30 seconds: auto_suspend = 60 (minimum)
If queries come every 5 minutes: auto_suspend = 300
If queries are batch (hourly): auto_suspend = 60

Common mistake: Default 600s (10 min) auto-suspend wastes 40%+ on dev/staging warehouses
```

**Analysis query:**
```sql
-- Find avg time between queries per warehouse
WITH query_gaps AS (
    SELECT WAREHOUSE_NAME,
           DATEDIFF('second', LAG(END_TIME) OVER (PARTITION BY WAREHOUSE_NAME ORDER BY END_TIME), START_TIME) AS gap_seconds
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
      AND EXECUTION_STATUS = 'SUCCESS'
)
SELECT WAREHOUSE_NAME,
       APPROX_PERCENTILE(gap_seconds, 0.5) AS median_gap,
       APPROX_PERCENTILE(gap_seconds, 0.9) AS p90_gap,
       COUNT(*) AS query_count
FROM query_gaps
WHERE gap_seconds > 0
GROUP BY 1
ORDER BY query_count DESC;
```

## Cloud Services Costs (The Hidden Trap)

### What Uses Cloud Services Credits
- Query compilation and optimization (every query incurs compilation cost)
- Metadata operations (DDL commands, zero-copy cloning, SHOW, DESCRIBE, INFORMATION_SCHEMA)
- Authentication and access control (LOGIN events)
- Query result caching management
- File listing operations (COPY commands scanning object storage)
- Table maintenance (automatic reclustering under certain conditions)
- Snowpipe file notifications

### The 10% Adjustment (Not a "Free Tier")
Cloud services credits are adjusted daily: you only pay if consumption exceeds 10% of daily warehouse compute. The adjustment = lesser of (10% of warehouse credits) or (actual cloud services credits).

**Example 1 (under threshold):** 100 warehouse credits + 8 cloud services credits = 0 billable cloud services (8 < 10)
**Example 2 (over threshold):** 100 warehouse credits + 20 cloud services credits = 10 billable cloud services (20 - 10 = 10)

**IMPORTANT:** Serverless features (Snowpipe, Clustering, MVs) bill separately — NOT subject to the 10% adjustment.

### When This Becomes a Problem
- Many small queries (each query has compilation overhead)
- Heavy use of INFORMATION_SCHEMA queries
- Many SHOW/DESCRIBE commands (common with BI tools like Looker/Tableau)
- Lots of login events (many concurrent users/service accounts)
- COPY commands listing thousands of files in object storage
- Complex queries with excessive joins or large IN clauses (heavy compilation)
- Single-row inserts (Snowflake is not OLTP — each insert has cloud services overhead)

### Monitoring Queries (from Select.dev)

**Daily cloud services billing with adjustment:**
```sql
SELECT usage_date,
       credits_used_cloud_services,
       credits_adjustment_cloud_services,
       credits_used_cloud_services + credits_adjustment_cloud_services AS billed_cloud_services,
       credits_used_compute,
       ROUND(credits_used_cloud_services / NULLIF(credits_used_compute, 0) * 100, 2) AS cs_pct_of_compute
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD(month, -1, CURRENT_TIMESTAMP())
  AND credits_used_cloud_services > 0
ORDER BY billed_cloud_services DESC;
```

**By query type (find which operations drive cloud services):**
```sql
SELECT query_type,
       SUM(credits_used_cloud_services) AS total_cs_credits,
       COUNT(1) AS num_queries,
       AVG(credits_used_cloud_services) AS avg_cs_per_query
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND credits_used_cloud_services > 0
GROUP BY query_type ORDER BY total_cs_credits DESC;
```

**High-cost individual queries:**
```sql
SELECT query_id, user_name, warehouse_name, query_type,
       credits_used_cloud_services,
       SUBSTRING(query_text, 1, 100) AS query_snippet
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND credits_used_cloud_services > 0.001
ORDER BY credits_used_cloud_services DESC LIMIT 100;
```

### Cloud Services Optimization
1. **Batch operations** — Combine DDL, DML, and data loads instead of running one at a time
2. **Fix COPY commands** — Use specific date-prefixed paths, not broad scans:
   - Bad: `COPY INTO target FROM @stage/raw_data/`
   - Good: `COPY INTO target FROM @stage/raw_data/2025/10/24/`
3. **Reduce BI metadata traffic** — Looker/Tableau generate hundreds of SHOW/DESCRIBE per dashboard load
4. **Simplify complex queries** — Replace large IN lists with temp tables and JOINs; reduce excessive joins
5. **Use ACCOUNT_USAGE over INFORMATION_SCHEMA** — Lower overhead (but has latency)

## Serverless Features Costs

Each serverless feature bills at its own credit rate:

| Feature | Credit Rate | Billing Unit |
|---------|------------|--------------|
| Snowpipe | 0.06 credits/file-second | Per file processed |
| Snowpipe Streaming | ~0.05 credits | Per second of compute |
| Tasks | 1.0 credits/hour (serverless) | Per compute-second |
| Automatic Clustering | 1.0 credits/hour | Per compute-second |
| Materialized Views | 1.0 credits/hour | Per maintenance compute |
| Search Optimization | 1.0 credits/hour | Per maintenance compute |
| Query Acceleration | 1.0 credits/hour | Per scale factor-second |
| Replication | 1.0 credits/hour | Per compute-second |

**Key insight:** Automatic clustering can silently consume massive credits. A table with heavy DML and a clustering key can recuster continuously.

**Check serverless costs:**
```sql
-- Automatic clustering costs
SELECT TABLE_NAME, DATABASE_NAME, SCHEMA_NAME,
       SUM(CREDITS_USED) AS clustering_credits,
       SUM(NUM_BYTES_RECLUSTERED) / 1e9 AS gb_reclustered
FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY
WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3
ORDER BY clustering_credits DESC LIMIT 20;

-- Snowpipe costs
SELECT PIPE_NAME, SUM(CREDITS_USED) AS pipe_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY
WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY 2 DESC;

-- Task costs (serverless)
SELECT NAME, DATABASE_NAME, SCHEMA_NAME,
       SUM(CREDITS_USED) AS task_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY
WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```

## Storage Costs

### Rates
- **On-demand:** $40/TB/month
- **Capacity contract:** $23/TB/month (most common)

### What Counts as Storage
1. **Active storage** — Current data in tables
2. **Time Travel** — Historical data for the retention period (default 1 day, up to 90 days on Enterprise)
3. **Fail-safe** — 7-day recovery window (Enterprise+), NOT configurable, charged automatically
4. **Internal stages** — Files in @ stages

**The Time Travel trap:** Setting `DATA_RETENTION_TIME_IN_DAYS = 90` on a heavily-updated table means you're storing 90 days of every change. A 100GB table with daily full-refresh keeps ~9TB in time travel.

**Check storage breakdown:**
```sql
SELECT TABLE_CATALOG AS database_name,
       TABLE_SCHEMA AS schema_name,
       TABLE_NAME,
       ROUND(ACTIVE_BYTES / 1e9, 2) AS active_gb,
       ROUND(TIME_TRAVEL_BYTES / 1e9, 2) AS time_travel_gb,
       ROUND(FAILSAFE_BYTES / 1e9, 2) AS failsafe_gb,
       ROUND((ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) / 1e9, 2) AS total_gb
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
WHERE ACTIVE_BYTES > 0
ORDER BY total_gb DESC LIMIT 50;
```

## Data Transfer Costs

Often overlooked but can be significant:
- **Same region, same cloud:** Free
- **Cross-region, same cloud:** $20-140/TB ($0.02–0.14/GB) — US regions cheapest, APAC most expensive
- **Cross-cloud or internet:** $90-155/TB ($0.09-0.155/GB)
- **Regular query results:** NO egress fees, even cross-region/cloud
- **Your cloud provider** may also charge egress fees when uploading TO Snowflake

### Egress Cost Optimizer (ECO) — New April 2025
Caches data after initial transfer, enabling replication to additional regions at zero extra cost.
- Rate: $16.896/TB-month (charged only when savings apply)
- Potential savings: up to 96% vs traditional replication

**Check data transfer:**
```sql
SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
       SOURCE_CLOUD, SOURCE_REGION,
       TARGET_CLOUD, TARGET_REGION,
       SUM(BYTES_TRANSFERRED) / 1e9 AS gb_transferred
FROM SNOWFLAKE.ACCOUNT_USAGE.DATA_TRANSFER_HISTORY
WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3, 4, 5
ORDER BY gb_transferred DESC;
```

## Common Cost Problems (From Community/Forums)

### 1. "My bill doubled overnight"
**Usual causes:**
- Someone changed a warehouse from X-Small to X-Large and forgot
- Multi-cluster warehouse scaled up due to concurrent queries
- Automatic clustering kicked in on a large table
- A dbt full-refresh ran on a huge table instead of incremental

### 2. "Cloud services are 30% of my bill"
- Too many small queries (metadata overhead per query)
- Looker/Tableau generating hundreds of SHOW/DESCRIBE commands
- Many LOGIN events from service accounts
- Fix: Batch small queries, reduce BI tool metadata calls

### 3. "Dev warehouses cost as much as production"
- Auto-suspend set to 10 minutes (default) instead of 60 seconds
- Developers leaving warehouses running
- Fix: Set dev warehouse auto_suspend = 60, enforce with RESOURCE MONITOR

### 4. "Storage costs keep growing even though we delete data"
- Time Travel retaining historical data
- Fail-safe adding 7 more days on top
- Transient tables don't have fail-safe — use for staging/temp
- Fix: Use `DATA_RETENTION_TIME_IN_DAYS = 0` for staging tables

### 5. "Credit consumption is unpredictable"
- No resource monitors set
- No warehouse size limits
- Users can resize warehouses
- Fix: Set RESOURCE MONITOR per warehouse with credit quotas:
```sql
CREATE RESOURCE MONITOR prod_monitor
  WITH CREDIT_QUOTA = 1000
  FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS
    ON 75 PERCENT DO NOTIFY
    ON 90 PERCENT DO NOTIFY
    ON 100 PERCENT DO SUSPEND;
ALTER WAREHOUSE PROD_WH SET RESOURCE_MONITOR = prod_monitor;
```

## Optimization Checklist (Ranked by Typical Savings)

1. **Right-size warehouses** (10-40% savings) — Most warehouses are oversized
2. **Tune auto-suspend** (5-30% savings) — Default 10min is too long for most
3. **Switch full-refresh to incremental** (20-60% on dbt models)
4. **Reduce Time Travel on staging** (5-15% storage savings)
5. **Set resource monitors** (prevents runaway costs)
6. **Use transient tables for temp data** (eliminates fail-safe storage)
7. **Optimize clustering keys** (reduce clustering credit burn)
8. **Cache repeated queries** (use result caching, materialized views)
9. **Right-size multi-cluster settings** (switch STANDARD → ECONOMY scaling)
10. **Review Snowpipe batch sizes** (larger files = fewer credits)

## Snowflake AI/ML Feature Costs (Cortex)

### Cortex AI SQL Functions (AI_COMPLETE, AI_EXTRACT, AI_CLASSIFY, AI_SUMMARIZE)
- Token-based pricing (both input and output)
- Premium models cost 10x more than small models
- Example: 10,000 product reviews = $0.96 with GPT-4o-mini vs $9.00 with Llama 3.1 405B

### Cortex Search
- Serving compute: ongoing per-GB cost for indexed data
- Embedding tokens charged during indexing
- Warehouse compute for refresh operations
- Storage for indexes

### Cortex Analyst
- Message-based billing (one message per successful HTTP 200 query)
- Flat rate regardless of query complexity
- Additional warehouse costs for SQL execution

### Document AI
- 8 credits per compute-hour
- ~$0.05 per document (invoice processing)
- Cost varies by page count and extraction complexity

### Snowflake Intelligence
- No agent-specific charges
- Costs distributed to underlying Cortex services

### Monitoring AI Costs
```sql
-- Token-based function costs
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
WHERE SERVICE_TYPE LIKE '%CORTEX%'
  AND START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
ORDER BY CREDITS_USED DESC;

-- Cortex Analyst usage
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY
WHERE START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP());
```

## Per-Query Cost Attribution (from SELECT/dbt-snowflake-monitoring)

### How Snowflake Allocates Compute Cost to Queries

The industry-standard method (used by SELECT.dev's open-source dbt package):

1. **Time-slice queries into hourly buckets** — each query gets 1 row per hour it ran in
2. **Calculate each query's fraction of warehouse time per hour:**
   ```
   fraction = query_execution_milliseconds_in_hour / total_warehouse_execution_milliseconds_in_hour
   ```
3. **Allocate credits proportionally:**
   ```
   query_compute_credits = warehouse_hourly_credits * fraction
   query_compute_cost = query_compute_credits * daily_effective_rate
   ```

**Critical detail:** Only execution time counts — queue time, compilation time, and provisioning time are excluded. The execution_start_time is calculated by adding all overhead times to start_time.

### Cloud Services Cost per Query
```
daily_billable_cloud_services = greatest(cloud_services_credits - compute_credits * 0.1, 0)
query_cloud_services_cost = (query_cs_credits / daily_cs_credits) * daily_billable_cloud_services * effective_rate
```

### Overage Rate Handling
When prepaid capacity is exhausted (remaining_balance < 0 in ORGANIZATION_USAGE.REMAINING_BALANCE_DAILY), overage rates from RATE_SHEET_DAILY kick in automatically. The rate can jump 50-100% — monitor remaining balance proactively.

### Rate Sheet Gaps
RATE_SHEET_DAILY does NOT have a row for every day — days with zero consumption have no record. Fill gaps using previous day's rate when calculating historical costs.

### Snowpark-Optimized Warehouses
Cost 1.5x standard credits at every size:
| Size | Standard Credits/Hr | Snowpark Credits/Hr |
|------|-------------------|-------------------|
| Medium | 4 | 6 |
| Large | 8 | 12 |
| X-Large | 16 | 24 |
| 2XL | 32 | 48 |

### Storage Cost Calculation
Storage is billed monthly per TB but accrues hourly:
```
hourly_storage_cost = storage_terabytes / (days_in_month * 24) * monthly_rate_per_TB
```

**Clone storage gotcha:** Itemized database storage (from DATABASE_STORAGE_USAGE_HISTORY) does NOT sum to total storage (from STORAGE_USAGE). The delta is "Retained for Clones" — storage from deleted objects retained because cloned tables still reference them.

### Service Name Inconsistency (Watch Out)
Snowflake uses different names for the same service across views:
- `AUTO_CLUSTERING` (in METERING_HISTORY) vs `AUTOMATIC_CLUSTERING` (in AUTOMATIC_CLUSTERING_HISTORY)
- `PIPE` (in METERING_HISTORY) vs `SNOWPIPE` (in PIPE_USAGE_HISTORY)
Always normalize service names when joining across views.

### Incomplete Day Edge Case
The cloud services 10% adjustment for the current (incomplete) day may be inaccurate because the full day's compute total is unknown. Historical data is accurate; today's data is approximate.

## Optimization Rules with Dollar Estimates

### Right-Sizing Formula (from OptScale)
```
recommended_size = ceil(current_credits_per_hour / utilization_limit * observed_p99_utilization)
monthly_saving = (current_credits_per_hour - recommended_credits_per_hour) * active_hours_per_month * credit_price
```
Where utilization_limit defaults to 80% (the threshold above which the warehouse is considered appropriately sized).

### Auto-Suspend Waste Estimate
```
wasted_credits_per_day = (auto_suspend_seconds - optimal_auto_suspend_seconds) / 3600 * credits_per_hour * resumes_per_day
optimal_auto_suspend = p90_inter_query_gap_seconds (minimum 60 seconds)
```
