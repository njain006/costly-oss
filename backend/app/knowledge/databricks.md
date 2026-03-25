# Databricks Billing & Cost Expert Knowledge Base

## Pricing Model

Databricks bills on **Databricks Units (DBUs)** — a normalized measure of compute capacity. Total cost = DBU consumption × DBU rate + cloud infrastructure cost.

### DBU Rates by SKU (Default Contract Prices)
| SKU | Description | Default Rate ($/DBU) |
|-----|------------|---------------------|
| Interactive (All-Purpose) | Notebooks, interactive queries | $0.55 |
| Automated (Jobs) | Scheduled jobs, production pipelines | $0.15 |
| Jobs Light | Apache Spark-only jobs (no Databricks Runtime) | $0.10 |
| SQL Compute (Serverless) | SQL Warehouses | $0.22 |
| SQL Pro | SQL Warehouses (Pro tier) | $0.55 |
| Delta Live Tables (Core) | DLT pipelines | $0.20 |
| Delta Live Tables (Pro) | DLT with advanced features | $0.25 |
| Delta Live Tables (Advanced) | DLT with expectations, enhanced autoscaling | $0.36 |
| Model Serving | Real-time ML inference | $0.07 |

**Key insight:** Interactive workloads cost 3.7x more than automated jobs per DBU. Moving notebooks to scheduled jobs saves 73%.

### How SKU is Determined (from Overwatch)
```
if automated AND spark_version starts with "apache_spark_": SKU = "jobsLight" ($0.10)
elif automated: SKU = "automated" ($0.15)
elif cluster_type == "SQL Analytics": SKU = "sqlCompute" ($0.22)
elif cluster_type == "High-Concurrency" OR not automated: SKU = "interactive" ($0.55)
```

## Cost Calculation Formula (from Overwatch)

### Total Cluster Cost
```
total_cost = driver_cost + worker_cost

driver_cost = (driver_compute_cost + driver_dbu_cost)
worker_cost = (worker_compute_cost + worker_dbu_cost)

driver_dbu_cost = driver_hourly_DBUs × uptime_hours × photon_multiplier × dbu_rate
worker_dbu_cost = worker_hourly_DBUs × num_workers × uptime_hours × photon_multiplier × dbu_rate

driver_compute_cost = driver_cloud_hourly_price × uptime_hours (if cloud billable)
worker_compute_cost = worker_cloud_hourly_price × num_workers × uptime_hours (if cloud billable)
```

### Photon Multiplier (Critical Cost Factor)
| Condition | Multiplier |
|-----------|-----------|
| Photon enabled + Automated jobs | 2.9x |
| Photon enabled + Interactive | 2.0x |
| Photon disabled or SQL Warehouse | 1.0x |

**Gotcha:** Enabling Photon on automated jobs nearly TRIPLES the DBU consumption. The performance gains must outweigh 2.9x cost increase. Benchmark before enabling.

### Single Node Clusters
When `num_workers = 0` (Single Node mode), the driver handles all compute. Worker cost = $0. DBUs = driver DBUs only.

## Cloud Infrastructure Costs (Often Forgotten)

Databricks DBU cost is only HALF the picture. The underlying cloud VMs are billed separately by AWS/Azure/GCP.

### AWS Instance Pricing (Common Databricks Instances)
| Instance | vCPU | Memory | On-Demand $/hr | Typical Use |
|----------|------|--------|----------------|-------------|
| i3.xlarge | 4 | 30.5 GB | $0.312 | Standard workers |
| i3.2xlarge | 8 | 61 GB | $0.624 | Heavy shuffle |
| i3.8xlarge | 32 | 244 GB | $2.499 | Large clusters |
| i3.16xlarge | 64 | 488 GB | $4.992 | Very large |
| m5.xlarge | 4 | 16 GB | $0.192 | General purpose |
| r5.xlarge | 4 | 32 GB | $0.252 | Memory-intensive |

### DBU to Instance Mapping (from Overwatch)
| Cloud | Size | Instance Type | Workers | Total DBUs/hr |
|-------|------|--------------|---------|--------------|
| AWS | 2X-Small | i3.2xlarge | 1 | 4 |
| AWS | X-Small | i3.4xlarge | 2 | 8 |
| AWS | Small | i3.4xlarge | 4 | 16 |
| AWS | Medium | i3.8xlarge | 8 | 24 |
| AWS | Large | i3.8xlarge | 16 | 48 |
| AWS | X-Large | i3.16xlarge | 32 | 96 |
| AWS | 2X-Large | i3.16xlarge | 64 | 192 |
| AWS | 4X-Large | i3.16xlarge | 256 | 528 |

### True Total Cost Example
A Medium automated cluster running 8 hours/day, 20 days/month:
```
DBU cost = 24 DBUs/hr × 8 hrs × 20 days × $0.15/DBU = $576/month
Cloud cost = (1 driver + 8 workers) × $2.499/hr × 8 hrs × 20 days = $3,599/month
Total = $4,175/month
```
**Cloud infra is 86% of total cost.** Optimizing instance types matters more than DBU rates.

## Job Run Cost Attribution (from Overwatch)

Overwatch allocates cluster costs to individual job runs proportionally:
1. Calculate total cluster cost for time window
2. Window function: `sum(total_DBU_cost) OVER (partition by cluster_id, time_window)`
3. Each job run gets: `job_run_duration / total_active_duration * total_cost`

This enables per-job and per-notebook cost tracking.

## Common Cost Problems

### 1. "Interactive clusters running 24/7"
- Developers leave notebooks with auto-termination disabled
- Fix: Enforce auto-termination (120 min max) via cluster policies
- Savings: 60-80% on interactive compute

### 2. "Wrong SKU for workload"
- Running production pipelines on interactive clusters ($0.55 vs $0.15/DBU)
- Fix: Move to Jobs clusters for scheduled workloads
- Savings: 73% on DBU costs

### 3. "Photon enabled everywhere"
- Photon multiplier (2.0-2.9x) applied without performance benchmarking
- Not all workloads benefit from Photon (especially Python UDFs, ML training)
- Fix: Benchmark with and without Photon. Only enable when query speed improvement > cost increase

### 4. "Oversized clusters"
- Default cluster configs use larger instances than needed
- Fix: Right-size based on actual utilization. Use Spark UI to check shuffle spill and memory pressure

### 5. "Idle Serverless SQL Warehouses"
- SQL Warehouses can have high idle costs even with auto-stop
- T-shirt sizing affects minimum cost
- Fix: Set auto-stop to minimum (10 min), use smallest size that meets latency requirements

### 6. "Unity Catalog overhead"
- Unity Catalog governance features (lineage, audit logs) consume additional compute
- Generally small but can accumulate in large deployments

## Optimization Checklist (Ranked by Typical Savings)

1. **Move interactive → automated jobs** (73% DBU savings)
2. **Enable auto-termination on all clusters** (60-80% waste reduction)
3. **Right-size clusters** (20-40% savings) — check Spark UI for utilization
4. **Use Spot instances for workers** (60-90% on cloud infra cost)
5. **Benchmark Photon** — disable if performance gain < cost increase
6. **Cluster policies** — enforce max size, auto-termination, instance types
7. **Instance pools** — reduce cluster start time, enable faster auto-scaling
8. **Serverless SQL** — evaluate vs classic for SQL workloads (pay-per-query economics)
9. **Delta table optimization** — OPTIMIZE + ZORDER reduces scan costs
10. **Job scheduling** — batch small jobs, avoid cluster-per-job overhead

## System Tables for Cost Monitoring (Replaces Overwatch)

As of 2024, Databricks System Tables are the recommended way to monitor costs:

```sql
-- Daily DBU consumption by SKU
SELECT usage_date, sku_name,
       SUM(usage_quantity) AS total_dbus,
       SUM(usage_quantity * list_price) AS estimated_cost
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -30, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY estimated_cost DESC;

-- Cost by workspace
SELECT workspace_id,
       SUM(usage_quantity * list_price) AS total_cost
FROM system.billing.usage
WHERE usage_date >= DATEADD(DAY, -30, CURRENT_DATE())
GROUP BY 1
ORDER BY total_cost DESC;

-- Top expensive jobs
SELECT usage_metadata.job_id,
       SUM(usage_quantity) AS total_dbus,
       SUM(usage_quantity * list_price) AS estimated_cost
FROM system.billing.usage
WHERE sku_name LIKE '%JOBS%'
  AND usage_date >= DATEADD(DAY, -30, CURRENT_DATE())
GROUP BY 1
ORDER BY estimated_cost DESC
LIMIT 20;
```
