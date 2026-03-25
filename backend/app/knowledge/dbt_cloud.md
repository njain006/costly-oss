# dbt Cloud Billing & Cost Expert Knowledge Base

## Pricing Model

dbt Cloud bills based on **plan tier + successful model builds**.

### Plans
| Plan | Price | Includes |
|------|-------|----------|
| Developer | Free | 1 project, 1 user, manual runs only |
| Team | $100/seat/month | Unlimited projects, CI, scheduling |
| Enterprise | Custom | SSO, RBAC, audit logs, SLA |

### Model Build Pricing (Team+ plans)
- Models built = successful model executions
- Included models vary by plan
- Overage: ~$0.01-0.03 per model build (varies)

## The Real Cost: Warehouse Compute

dbt Cloud's own bill is usually small. The **warehouse compute it triggers** is the real cost:
- Each `dbt run` spins up warehouse compute (Snowflake credits, BigQuery slots, etc.)
- A full-refresh of 200 models on a Large Snowflake warehouse = 200 × model_runtime × 8 credits/hr
- **The dbt bill is the tip of the iceberg — the warehouse bill is the iceberg**

## Cost Optimization Strategies

1. **Incremental models** — 5-20x cheaper than full-refresh for large tables
   - `materialized='incremental'` with `unique_key` and proper `is_incremental()` logic
   - Full-refresh only when schema changes or data quality requires it

2. **Model selection in CI** — Don't run all models on every PR
   - `dbt build --select state:modified+` — only changed models + downstream
   - Slim CI saves 80%+ on CI warehouse costs

3. **Warehouse per job type** — Don't use one big warehouse for everything
   - Hourly incremental: Small warehouse
   - Daily full-refresh: Medium warehouse
   - Monthly rebuild: Large warehouse (short burst)

4. **Defer to production** — CI jobs reference prod models instead of rebuilding everything

5. **Reduce model count** — Excessive intermediate models increase build time
   - Ephemeral models compile to CTEs (no warehouse cost)
   - Consolidate staging models where possible

## Common Cost Problems

### 1. "dbt jobs are our biggest Snowflake cost"
- Full-refresh on tables that should be incremental
- Running all 500 models on every schedule instead of only changed
- Fix: Incremental materialization + model selection

### 2. "CI is burning credits"
- Every PR runs the full project
- Fix: `dbt build --select state:modified+` with `--defer`

### 3. "Development is expensive"
- Developers running `dbt run` on Large warehouses
- Fix: Dev profiles use X-Small warehouse, limit to subset of models

## dbt Cloud Build Metrics (from dbt_artifacts)

### Cost-Per-Model Attribution
The key to understanding dbt costs is tracking warehouse compute per model:
```
model_cost = (model_execution_seconds / 3600) * warehouse_credits_per_hour * credit_price
```

Use query tagging (`dbt-snowflake-query-tags` package) to attribute Snowflake costs back to specific dbt models.

### DAG Anti-Patterns That Waste Compute (from dbt-project-evaluator)
1. **Rejoining to sources** — downstream models querying raw sources instead of using upstream models. Forces redundant scans.
2. **Excessive staging models** — each model materializes as a table/view with overhead. Consolidate where possible.
3. **Fan-out without fan-in** — wide DAGs with many branches but no aggregation point. Each branch runs in parallel consuming warehouse credits.
4. **Missing incremental candidates** — large tables rebuilt daily that only need new/changed rows.

### Environment-Based Cost Optimization
| Environment | Strategy | Estimated Savings |
|-------------|---------|------------------|
| Development | Limit data with `target.name == 'dev'` macro, use X-Small warehouse | 80-90% |
| CI/PR | `dbt build --select state:modified+`, defer to prod | 70-90% |
| Staging | Full run but on smaller warehouse, less frequent | 30-50% |
| Production | Optimized warehouse sizing, incremental where possible | Baseline |

### Scheduling Optimization
- Stagger job schedules to avoid warehouse contention
- Group related models in a single job (one warehouse resume vs multiple)
- Use `dbt source freshness` as a trigger instead of time-based schedules
- Avoid running hourly if daily is sufficient — 24x cost difference

### dbt Cloud API for Cost Monitoring
```
GET /api/v2/accounts/{account_id}/runs/
GET /api/v2/accounts/{account_id}/runs/{run_id}/
```
Key fields: `run_duration_humanized`, `models_generated`, `status`, `created_at`
Use these to track model build counts (which drive dbt Cloud billing) and correlate with warehouse costs.
