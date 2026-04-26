import math
import random
import uuid
from datetime import datetime, timedelta

from app.utils.helpers import days_ago
from app.utils.constants import CREDITS_MAP


def generate_demo_dashboard(days=30):
    rng = random.Random(42)
    cost_trend = []
    raw_costs = []

    for i in range(days):
        date = days_ago(days - 1 - i)
        if i == 7:
            compute, cloud_svc = 445.0, 35.0
        elif i == 18:
            compute, cloud_svc = 310.0, 30.0
        else:
            compute = round(rng.uniform(120, 160), 2)
            cloud_svc = round(rng.uniform(10, 25), 2)
        cost = round(compute + cloud_svc, 2)
        raw_costs.append(cost)
        cost_trend.append({
            "date": date,
            "cost": cost,
            "compute_cost": compute,
            "cloud_services_cost": cloud_svc,
            "credits": round(cost / 3.0, 2),
        })

    anomalies = []
    for i in range(len(cost_trend)):
        window = raw_costs[max(0, i - 14):i] if i > 0 else raw_costs[:1]
        rolling_avg = sum(window) / len(window) if window else raw_costs[i]
        ratio = raw_costs[i] / rolling_avg if rolling_avg > 0 else 1.0
        cost_trend[i]["rolling_avg"] = round(rolling_avg, 2)
        if ratio >= 1.8 and i > 3:
            label = ("ETL warehouse left running overnight" if i == 7
                     else "Monday analytics refresh storm")
            anomalies.append({
                "date": cost_trend[i]["date"],
                "cost": cost_trend[i]["cost"],
                "avg": round(rolling_avg, 2),
                "ratio": round(ratio, 2),
                "label": label,
            })

    top_warehouses = [
        {"name": "COMPUTE_WH", "credits": 210.5, "cost": 631.5},
        {"name": "ANALYTICS_WH", "credits": 178.4, "cost": 535.2},
        {"name": "ETL_WH", "credits": 82.6, "cost": 247.8},
        {"name": "REPORTING_WH", "credits": 22.1, "cost": 66.3},
    ]
    top_users = [
        {"user": "NITIN", "cost": 520.0, "queries": 420},
        {"user": "ANALYTICS_SVC", "cost": 435.0, "queries": 1850},
        {"user": "ETL_PIPELINE", "cost": 340.0, "queries": 3200},
        {"user": "ALICE", "cost": 180.0, "queries": 210},
        {"user": "BOB", "cost": 95.0, "queries": 95},
    ]
    return {
        "total_cost": round(sum(d["cost"] for d in cost_trend), 2),
        "total_credits": round(sum(d["credits"] for d in cost_trend), 2),
        "active_warehouses": 4,
        "expensive_queries": 28,
        "query_count": 8547,
        "failed_queries": 125,
        "storage_gb": 1147.2,
        "cost_trend": cost_trend,
        "top_warehouses": top_warehouses,
        "top_users": top_users,
        "credit_price": 3.0,
        "days": days,
        "anomalies": anomalies,
    }


def generate_demo_costs(days=30):
    rng = random.Random(43)
    warehouses = ["COMPUTE_WH", "ANALYTICS_WH", "ETL_WH", "REPORTING_WH"]
    wh_baseline = {
        "COMPUTE_WH": (38, 52),
        "ANALYTICS_WH": (50, 70),
        "ETL_WH": (18, 28),
        "REPORTING_WH": (8, 14),
    }
    daily = []
    for i in range(days):
        date = days_ago(days - 1 - i)
        for wh in warehouses:
            lo, hi = wh_baseline[wh]
            if i == 7 and wh == "ETL_WH":
                cost = round(rng.uniform(160, 190), 2)
            elif i == 18 and wh in ("ANALYTICS_WH", "COMPUTE_WH"):
                cost = round(rng.uniform(hi * 1.8, hi * 2.2), 2)
            else:
                cost = round(rng.uniform(lo, hi), 2)
            daily.append({"date": date, "warehouse": wh, "cost": cost, "credits": round(cost / 3, 2)})
    by_user = [
        {"user": "NITIN", "cost": 1850.0, "queries": 420},
        {"user": "ANALYTICS_SVC", "cost": 1380.0, "queries": 1850},
        {"user": "ETL_PIPELINE", "cost": 990.0, "queries": 3200},
        {"user": "ALICE", "cost": 540.0, "queries": 210},
        {"user": "BOB", "cost": 320.0, "queries": 95},
    ]
    return {"daily": daily, "by_user": by_user, "days": days}


def generate_demo_queries():
    rng = random.Random(44)
    users = ["NITIN", "ALICE", "BOB", "ANALYTICS_SVC", "ETL_PIPELINE"]
    warehouses = ["COMPUTE_WH", "ANALYTICS_WH", "ETL_WH"]
    wh_sizes = {"COMPUTE_WH": "MEDIUM", "ANALYTICS_WH": "LARGE", "ETL_WH": "SMALL"}
    wh_credits_hr = {"COMPUTE_WH": 4, "ANALYTICS_WH": 8, "ETL_WH": 2}
    templates = [
        ("SELECT customer_id, SUM(order_total) as revenue FROM orders WHERE order_date >= '2025-01-01' GROUP BY 1 ORDER BY 2 DESC", "SELECT"),
        ("CREATE TABLE temp_results AS SELECT u.user_id, COUNT(e.event_id) as events FROM users u JOIN events e ON u.user_id = e.user_id GROUP BY 1", "CREATE TABLE AS"),
        ("UPDATE inventory SET quantity = quantity - s.sold FROM inventory i JOIN daily_sales s ON i.product_id = s.product_id", "UPDATE"),
        ("SELECT DATE_TRUNC('week', created_at) as week, warehouse, SUM(credits) FROM usage_history GROUP BY 1, 2 ORDER BY 1", "SELECT"),
        ("WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY ts) as rn FROM page_views) SELECT * FROM ranked WHERE rn = 1", "SELECT"),
        ("SELECT p.product_name, c.category, SUM(oi.quantity * oi.price) FROM order_items oi JOIN products p ON oi.product_id = p.id JOIN categories c ON p.cat_id = c.id GROUP BY 1, 2", "SELECT"),
        ("SELECT * FROM large_events_table WHERE event_date BETWEEN '2024-01-01' AND '2025-01-01'", "SELECT"),
        ("INSERT INTO analytics.daily_summary SELECT DATE(created_at), COUNT(*), SUM(revenue) FROM raw_events GROUP BY 1", "INSERT"),
    ]
    queries = []

    queries.append({
        "query_id": "QOUTLIER001",
        "start_time": (datetime.now() - timedelta(hours=rng.randint(2, 48))).isoformat(),
        "user": "ANALYTICS_SVC",
        "warehouse": "ANALYTICS_WH",
        "warehouse_size": "LARGE",
        "duration_ms": 480_000,
        "bytes_scanned": 40_000_000_000,
        "rows_produced": 12_500_000,
        "query_text": "SELECT * FROM large_events_table WHERE event_date BETWEEN '2024-01-01' AND '2025-01-01'",
        "credits": round(480_000 / 3_600_000 * 8, 4),
        "cost_usd": 1.20,
        "execution_ms": int(480_000 * 0.76),
        "compilation_ms": int(480_000 * 0.04),
        "queue_overload_ms": int(480_000 * 0.16),
        "queue_provision_ms": int(480_000 * 0.02),
        "blocked_ms": int(480_000 * 0.02),
        "spill_local_gb": 18.4,
        "spill_remote_gb": 3.2,
        "partitions_scanned": 48200,
        "partitions_total": 48200,
        "cache_hit_pct": 0.0,
        "query_type": "SELECT",
        "execution_status": "SUCCESS",
        "role": "ANALYST_ROLE",
    })

    failure_cases = [
        {
            "query_id": "QFAIL001",
            "query_text": "SELECT * FROM orders JOIN customers ON orders.cust_id = customer.id WHERE region = 'APAC'",
            "error_message": "Object 'CUSTOMER' does not exist or not authorized.",
            "duration_ms": 412,
            "warehouse": "ANALYTICS_WH",
            "user": "ALICE",
        },
        {
            "query_id": "QFAIL002",
            "query_text": "UPDATE prod_orders SET status = 'CLOSED' WHERE created_at < '2020-01-01'",
            "error_message": "Insufficient privileges to operate on table 'PROD_ORDERS'.",
            "duration_ms": 185,
            "warehouse": "COMPUTE_WH",
            "user": "BOB",
        },
        {
            "query_id": "QFAIL003",
            "query_text": "SELECT a.*, b.*, c.* FROM events a JOIN sessions b ON a.session_id = b.id JOIN users c ON b.user_id = c.id LEFT JOIN products d ON a.product_id = d.id",
            "error_message": "Query exceeded memory limit. Spill to remote storage failed: insufficient disk quota.",
            "duration_ms": 245_000,
            "warehouse": "ETL_WH",
            "user": "ETL_PIPELINE",
        },
        {
            "query_id": "QFAIL004",
            "query_text": "COPY INTO raw_data.events FROM @my_stage/events/ FILE_FORMAT = (TYPE = 'JSON')",
            "error_message": "Error parsing JSON: unexpected character ',' at position 14823.",
            "duration_ms": 8200,
            "warehouse": "ETL_WH",
            "user": "ETL_PIPELINE",
        },
    ]
    for fc in failure_cases:
        queries.append({
            "query_id": fc["query_id"],
            "start_time": (datetime.now() - timedelta(hours=rng.randint(2, 120))).isoformat(),
            "user": fc["user"],
            "warehouse": fc["warehouse"],
            "warehouse_size": wh_sizes.get(fc["warehouse"], "SMALL"),
            "duration_ms": fc["duration_ms"],
            "bytes_scanned": rng.randint(0, 500_000_000),
            "rows_produced": 0,
            "query_text": fc["query_text"],
            "credits": 0.0,
            "cost_usd": 0.0,
            "execution_ms": 0,
            "compilation_ms": fc["duration_ms"],
            "queue_overload_ms": 0,
            "queue_provision_ms": 0,
            "blocked_ms": 0,
            "spill_local_gb": 0.0,
            "spill_remote_gb": 0.0,
            "partitions_scanned": 0,
            "partitions_total": 0,
            "cache_hit_pct": 0.0,
            "query_type": "SELECT",
            "execution_status": "FAIL",
            "error_message": fc["error_message"],
            "role": rng.choice(["ACCOUNTADMIN", "ANALYST_ROLE", "ETL_ROLE"]),
        })

    for _ in range(45):
        start_dt = datetime.now() - timedelta(hours=rng.randint(1, 168))
        duration_ms = int(rng.uniform(8000, 280000))
        wh = rng.choice(warehouses)
        cr_hr = wh_credits_hr[wh]
        cost_credits = (duration_ms / 3_600_000) * cr_hr
        exec_pct = rng.uniform(0.60, 0.80)
        compile_pct = rng.uniform(0.05, 0.15)
        queue_overload_pct = rng.uniform(0.0, 0.15)
        queue_provision_pct = rng.uniform(0.0, 0.05)
        blocked_pct = max(0.0, 1.0 - exec_pct - compile_pct - queue_overload_pct - queue_provision_pct)
        parts_total = rng.randint(500, 50000)
        tmpl, qtype = rng.choice(templates)
        queries.append({
            "query_id": f"Q{uuid.uuid4().hex[:8].upper()}",
            "start_time": start_dt.isoformat(),
            "user": rng.choice(users),
            "warehouse": wh,
            "warehouse_size": wh_sizes[wh],
            "duration_ms": duration_ms,
            "bytes_scanned": rng.randint(100_000_000, 40_000_000_000),
            "rows_produced": rng.randint(1000, 5_000_000),
            "query_text": tmpl,
            "credits": round(cost_credits, 4),
            "cost_usd": round(cost_credits * 3.0, 4),
            "execution_ms": int(duration_ms * exec_pct),
            "compilation_ms": int(duration_ms * compile_pct),
            "queue_overload_ms": int(duration_ms * queue_overload_pct),
            "queue_provision_ms": int(duration_ms * queue_provision_pct),
            "blocked_ms": int(duration_ms * blocked_pct),
            "spill_local_gb": round(rng.uniform(0, 2) if rng.random() > 0.7 else 0, 2),
            "spill_remote_gb": round(rng.uniform(0, 0.5) if rng.random() > 0.9 else 0, 2),
            "partitions_scanned": int(parts_total * rng.uniform(0.1, 1.0)),
            "partitions_total": parts_total,
            "cache_hit_pct": round(rng.uniform(0, 100), 1),
            "query_type": qtype,
            "execution_status": "SUCCESS",
            "role": rng.choice(["ACCOUNTADMIN", "ANALYST_ROLE", "ETL_ROLE", "ANALYST_ROLE"]),
        })
    return sorted(queries, key=lambda x: x["duration_ms"], reverse=True)


def generate_demo_queries_paginated(page=1, limit=50):
    all_q = generate_demo_queries()
    total = len(all_q)
    start = (page - 1) * limit
    return {
        "data": all_q[start:start + limit],
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / limit)),
        "limit": limit,
        "days": 7,
    }


def generate_demo_storage():
    rng = random.Random(45)
    databases = ["PROD_DB", "ANALYTICS_DB", "RAW_DATA", "STAGING"]
    tables = []

    stale_configs = [
        ("RAW_DATA", "PUBLIC", "EVENTS_ARCHIVE_2023", 48.2, 210),
        ("STAGING", "PUBLIC", "ORDERS_IMPORT_Q3_2023", 22.8, 185),
        ("ANALYTICS_DB", "PUBLIC", "TEMP_ANALYSIS_NOV2023", 15.4, 140),
        ("STAGING", "PUBLIC", "CUSTOMER_BACKUP_2023", 12.1, 165),
    ]
    for db_name, schema, tbl, active_gb, age_days in stale_configs:
        tt_gb = round(active_gb * 0.15, 2)
        fs_gb = round(active_gb * 0.35, 2)
        tables.append({
            "database": db_name, "schema": schema, "table": tbl,
            "size_gb": round(active_gb + tt_gb + fs_gb, 2),
            "active_gb": active_gb, "time_travel_gb": tt_gb,
            "failsafe_gb": fs_gb, "clone_gb": 0.0,
            "last_accessed": days_ago(age_days),
            "stale": True,
        })

    for db_name in databases:
        for j in range(rng.randint(4, 7)):
            active_gb = round(rng.uniform(5, 280), 2)
            tt_gb = round(active_gb * rng.uniform(0.05, 0.18), 2)
            fs_gb = round(active_gb * rng.uniform(0.05, 0.12), 2)
            clone_gb = round(rng.uniform(0, active_gb * 0.08), 2)
            age_days = rng.randint(0, 40)
            tables.append({
                "database": db_name, "schema": "PUBLIC",
                "table": f"TABLE_{db_name[:3]}_{j + 1}",
                "size_gb": round(active_gb + tt_gb + fs_gb, 2),
                "active_gb": active_gb, "time_travel_gb": tt_gb,
                "failsafe_gb": fs_gb, "clone_gb": clone_gb,
                "last_accessed": days_ago(age_days),
                "stale": False,
            })

    table_base = 820.0
    stage_base = 95.0
    fs_base = 35.0
    trend = []
    for i in range(30):
        table_base += rng.uniform(1.8, 3.4)
        stage_base += rng.uniform(0.2, 0.9)
        fs_base += rng.uniform(0.3, 0.7)
        trend.append({
            "date": days_ago(29 - i),
            "table_gb": round(table_base, 1),
            "stage_gb": round(stage_base, 1),
            "failsafe_gb": round(fs_base, 1),
            "total_gb": round(table_base + stage_base + fs_base, 1),
        })

    total_gb = round(sum(t["size_gb"] for t in tables), 2)
    by_database = [
        {"database": "PROD_DB", "avg_db_gb": 450.2, "avg_failsafe_gb": 45.0, "avg_hybrid_gb": 0.0, "max_db_gb": 460.5, "total_gb": 495.2},
        {"database": "ANALYTICS_DB", "avg_db_gb": 310.8, "avg_failsafe_gb": 31.1, "avg_hybrid_gb": 12.5, "max_db_gb": 315.2, "total_gb": 354.4},
        {"database": "RAW_DATA", "avg_db_gb": 180.4, "avg_failsafe_gb": 68.5, "avg_hybrid_gb": 0.0, "max_db_gb": 185.1, "total_gb": 248.9},
        {"database": "STAGING", "avg_db_gb": 42.1, "avg_failsafe_gb": 12.1, "avg_hybrid_gb": 0.0, "max_db_gb": 45.0, "total_gb": 54.2},
    ]
    return {
        "tables": sorted(tables, key=lambda x: x["size_gb"], reverse=True),
        "total_gb": total_gb,
        "storage_cost_monthly": round(total_gb * 0.023, 2),
        "trend": trend,
        "by_database": by_database,
    }


def generate_demo_warehouses():
    warehouses = [
        {"name": "ANALYTICS_WH", "size": "LARGE", "state": "RUNNING", "auto_suspend": 600, "min_cluster": 1, "max_cluster": 5},
        {"name": "COMPUTE_WH", "size": "MEDIUM", "state": "RUNNING", "auto_suspend": 300, "min_cluster": 1, "max_cluster": 3},
        {"name": "ETL_WH", "size": "SMALL", "state": "SUSPENDED", "auto_suspend": 60, "min_cluster": 1, "max_cluster": 1},
        {"name": "REPORTING_WH", "size": "XSMALL", "state": "SUSPENDED", "auto_suspend": 120, "min_cluster": 1, "max_cluster": 2},
    ]
    for wh in warehouses:
        wh["credits_per_hour"] = CREDITS_MAP.get(wh["size"], 1)

    rng = random.Random(46)
    wh_stats = [
        {"name": "ANALYTICS_WH", "query_count": 1842, "failed_count": 38, "avg_cache_hit_pct": 28.4, "avg_spill_local_gb": 0.08, "avg_spill_remote_gb": 0.01, "avg_duration_s": 42.3},
        {"name": "COMPUTE_WH", "query_count": 3240, "failed_count": 62, "avg_cache_hit_pct": 45.8, "avg_spill_local_gb": 0.21, "avg_spill_remote_gb": 0.02, "avg_duration_s": 18.5},
        {"name": "ETL_WH", "query_count": 980, "failed_count": 22, "avg_cache_hit_pct": 12.1, "avg_spill_local_gb": 2.84, "avg_spill_remote_gb": 0.62, "avg_duration_s": 28.7},
        {"name": "REPORTING_WH", "query_count": 84, "failed_count": 3, "avg_cache_hit_pct": 71.2, "avg_spill_local_gb": 0.00, "avg_spill_remote_gb": 0.00, "avg_duration_s": 4.2},
    ]

    activity = []
    load_history = []
    for wh in warehouses:
        for i in range(7):
            activity.append({
                "date": days_ago(6 - i),
                "warehouse": wh["name"],
                "credits": round(rng.uniform(2, 35), 2),
            })
            load_history.append({
                "date": days_ago(6 - i),
                "warehouse": wh["name"],
                "avg_running": round(rng.uniform(0.1, 3.5), 2),
                "avg_queued": round(rng.uniform(0, 0.8), 3),
                "avg_provisioning": round(rng.uniform(0, 0.2), 3),
            })
    return {"warehouses": warehouses, "activity": activity, "load_history": load_history, "wh_stats": wh_stats}


def generate_demo_recommendations():
    """Return a mix of high / medium / low impact recommendations.

    Each item matches the shape of the real `/api/recommendations` endpoint
    and additionally exposes the ``ddl_command`` and ``pr_preview`` fields
    consumed by the "Apply via GitHub PR" flow on the recommendations page.
    """
    return [
        {
            "id": "rec_001",
            "title": "Right-size ANALYTICS_WH from LARGE to MEDIUM",
            "description": (
                "ANALYTICS_WH avg parallelism is 1.2 (well under LARGE capacity) and "
                "there is no remote spillage. Downsizing cuts credit spend ~50% with "
                "minimal latency impact on the 6 dashboards that use it."
            ),
            "category": "warehouse",
            "potential_savings": 580,
            "effort": "low",
            "priority": "high",
            "ddl_command": "ALTER WAREHOUSE ANALYTICS_WH SET WAREHOUSE_SIZE = 'Medium';",
            "pr_preview": {
                "title": "infra(snowflake): right-size ANALYTICS_WH LARGE → MEDIUM",
                "body": (
                    "## Why\n"
                    "ANALYTICS_WH has averaged **18% utilization** over the past 30 days "
                    "(`WAREHOUSE_LOAD_HISTORY`), with no remote spillage on 1,842 queries. "
                    "Downsizing releases ~50% of the LARGE → MEDIUM credit delta.\n\n"
                    "## Change\n"
                    "```sql\nALTER WAREHOUSE ANALYTICS_WH SET WAREHOUSE_SIZE = 'Medium';\n```\n\n"
                    "## Expected savings\n"
                    "**$580 / month** at $3.00 / credit.\n\n"
                    "## Rollback\n"
                    "```sql\nALTER WAREHOUSE ANALYTICS_WH SET WAREHOUSE_SIZE = 'Large';\n```\n"
                ),
                "files_changed": ["infra/snowflake/warehouses.sql"],
                "diff_lines": 2,
            },
        },
        {
            "id": "rec_002",
            "title": "Reduce ANALYTICS_WH auto-suspend 600s → 120s",
            "description": (
                "Auto-suspend is set to 600s but the 75th-percentile idle gap between "
                "queries is only 95s. Dropping to 120s cuts ~48 idle credits per month."
            ),
            "category": "warehouse",
            "potential_savings": 145,
            "effort": "low",
            "priority": "high",
            "ddl_command": "ALTER WAREHOUSE ANALYTICS_WH SET AUTO_SUSPEND = 120;",
            "pr_preview": {
                "title": "infra(snowflake): tighten ANALYTICS_WH auto-suspend 600s → 120s",
                "body": (
                    "## Why\n"
                    "`WAREHOUSE_EVENTS_HISTORY` shows 340 resumes/month with the p75 "
                    "idle gap at **95s** — 120s is the safe minimum without thrashing.\n\n"
                    "## Change\n"
                    "```sql\nALTER WAREHOUSE ANALYTICS_WH SET AUTO_SUSPEND = 120;\n```\n\n"
                    "## Expected savings\n"
                    "**$145 / month** (48.5 idle credits reclaimed).\n"
                ),
                "files_changed": ["infra/snowflake/warehouses.sql"],
                "diff_lines": 1,
            },
        },
        {
            "id": "rec_003",
            "title": "Add clustering key to ORDERS on (order_date, customer_id)",
            "description": (
                "5 slow queries on PROD_DB.SALES.ORDERS are doing full-table scans "
                "(40GB+). A clustering key on (order_date, customer_id) reduces scan "
                "by ~75% based on historical predicate patterns."
            ),
            "category": "query",
            "potential_savings": 180,
            "effort": "medium",
            "priority": "high",
            "ddl_command": "ALTER TABLE PROD_DB.SALES.ORDERS CLUSTER BY (order_date, customer_id);",
            "pr_preview": {
                "title": "perf(snowflake): cluster ORDERS by (order_date, customer_id)",
                "body": (
                    "## Why\n"
                    "Top 5 slow queries on `PROD_DB.SALES.ORDERS` (hash `p_002`) scan "
                    "**92% of partitions** while filtering on `order_date`. Clustering "
                    "pushes pruning to the micro-partition layer.\n\n"
                    "## Change\n"
                    "```sql\nALTER TABLE PROD_DB.SALES.ORDERS\n  CLUSTER BY (order_date, customer_id);\n```\n\n"
                    "## Expected savings\n"
                    "**$180 / month** (plus ~40% p95 latency improvement).\n\n"
                    "## Notes\n"
                    "Reclustering credits ~$15 one-time. Monitor "
                    "`AUTOMATIC_CLUSTERING_HISTORY` for 2 weeks post-merge.\n"
                ),
                "files_changed": ["infra/snowflake/tables/orders.sql"],
                "diff_lines": 1,
            },
        },
        {
            "id": "rec_004",
            "title": "Enable USE_CACHED_RESULT on REPORTING_WH session params",
            "description": (
                "35% of REPORTING_WH queries are identical repeated requests from "
                "dashboards. Session-level result caching eliminates redundant compute."
            ),
            "category": "query",
            "potential_savings": 95,
            "effort": "low",
            "priority": "medium",
            "ddl_command": "ALTER WAREHOUSE REPORTING_WH SET USE_CACHED_RESULT = TRUE;",
            "pr_preview": {
                "title": "perf(snowflake): enable USE_CACHED_RESULT on REPORTING_WH",
                "body": (
                    "## Why\n"
                    "Dashboard `p_001` fires 487× / month with identical bind params. "
                    "Result caching turns those into free cache hits.\n\n"
                    "## Change\n"
                    "```sql\nALTER WAREHOUSE REPORTING_WH SET USE_CACHED_RESULT = TRUE;\n```\n\n"
                    "## Expected savings\n"
                    "**$95 / month**, no latency impact.\n"
                ),
                "files_changed": ["infra/snowflake/warehouses.sql"],
                "diff_lines": 1,
            },
        },
        {
            "id": "rec_005",
            "title": "Archive 12 stale tables in STAGING & RAW_DATA",
            "description": (
                "12 tables in STAGING and RAW_DATA haven't been accessed in 60+ days "
                "and occupy 85 GB. Dropping or archiving them frees storage and "
                "eliminates fail-safe overhead."
            ),
            "category": "storage",
            "potential_savings": 58,
            "effort": "low",
            "priority": "medium",
            "ddl_command": (
                "DROP TABLE IF EXISTS RAW_DATA.PUBLIC.EVENTS_ARCHIVE_2023; "
                "DROP TABLE IF EXISTS STAGING.PUBLIC.ORDERS_IMPORT_Q3_2023;"
            ),
            "pr_preview": {
                "title": "chore(storage): drop 12 stale tables in STAGING/RAW_DATA",
                "body": (
                    "## Why\n"
                    "`ACCESS_HISTORY` shows these tables have not been queried in "
                    "140-210 days. Total footprint: **85 GB** (active + time-travel + "
                    "fail-safe).\n\n"
                    "## Change\n"
                    "Drop 12 stale tables. See linked table inventory for the full list.\n\n"
                    "## Expected savings\n"
                    "**$58 / month** ongoing.\n\n"
                    "## Rollback\n"
                    "All tables have 7d time-travel; `UNDROP TABLE <name>` within a week.\n"
                ),
                "files_changed": ["infra/snowflake/cleanup-2026-04.sql"],
                "diff_lines": 24,
            },
        },
        {
            "id": "rec_006",
            "title": "Disable unused Fail-safe on dev databases",
            "description": (
                "Transient dev tables are consuming ~12 GB of fail-safe storage. "
                "Making these tables TRANSIENT removes the 7-day fail-safe overhead."
            ),
            "category": "storage",
            "potential_savings": 18,
            "effort": "low",
            "priority": "low",
            "ddl_command": None,  # Requires table-by-table review
            "pr_preview": None,
        },
        {
            "id": "rec_007",
            "title": "Investigate Monday-morning analytics refresh storm",
            "description": (
                "Every Monday at 07:00, ANALYTICS_WH spikes 3× baseline for ~45 "
                "minutes. Likely 6 overlapping dashboard refreshes. Stagger them "
                "by 5-10 minutes each or move to scheduled materializations."
            ),
            "category": "query",
            "potential_savings": 42,
            "effort": "medium",
            "priority": "low",
            "ddl_command": None,  # Requires dashboard config change, not DDL
            "pr_preview": None,
        },
    ]


def generate_demo_anomalies(days: int = 30) -> dict:
    """Return anomalies tied to the existing demo narratives.

    Shape matches the real ``GET /api/anomalies`` endpoint:
    ``{anomalies: list[dict], count: int, unacknowledged: int}``. Each
    anomaly entry follows the schema in ``anomaly_detector.py``.

    Stories surfaced:
      * ETL warehouse left running overnight (day -7 in dashboard trend)
      * Monday analytics-refresh storm (day -18)
      * Claude Code prompt-caching regression (days 19-23)
      * A resource-level Redshift nightly spike
    """
    rng = random.Random(2027)
    detected_at = datetime.utcnow().isoformat()

    anomalies: list[dict] = []

    # 1) ETL warehouse left running overnight — mirrors demo_dashboard day 7.
    anomalies.append({
        "_id": f"anom_{uuid.uuid4().hex[:12]}",
        "user_id": "demo",
        "date": days_ago(min(days, 30) - 8),  # ~ day -7 in the 30-day window
        "type": "zscore_spike",
        "severity": "high",
        "scope": "platform",
        "platform": "snowflake",
        "resource": "ETL_WH",
        "cost": 480.00,
        "baseline_mean": 168.40,
        "baseline_stddev": 32.10,
        "baseline": 168.40,
        "zscore": 4.12,
        "change_pct": 185.0,
        "message": (
            "ETL_WH spend of $480 is 185% above its 30-day average of $168 "
            "(z-score: 4.1). Warehouse ran 11 hours past the nightly window — "
            "check pipeline `ingest_events` for a stuck task."
        ),
        "detected_at": detected_at,
        "acknowledged": False,
    })

    # 2) Monday analytics-refresh storm — mirrors demo_dashboard day 18.
    anomalies.append({
        "_id": f"anom_{uuid.uuid4().hex[:12]}",
        "user_id": "demo",
        "date": days_ago(min(days, 30) - 19),
        "type": "day_over_day_spike",
        "severity": "medium",
        "scope": "total",
        "platform": "",
        "resource": "",
        "cost": 340.00,
        "previous_cost": 168.00,
        "baseline": 168.00,
        "pct_change": 102.4,
        "change_pct": 102.4,
        "message": (
            "Total spend spiked 102% day-over-day: $340 vs $168 previous day. "
            "Correlated with 6 dashboards firing on ANALYTICS_WH at 07:00 local."
        ),
        "detected_at": detected_at,
        "acknowledged": False,
    })

    # 3) Claude Code prompt-caching regression — days 19-23 of ai_costs story.
    anomalies.append({
        "_id": f"anom_{uuid.uuid4().hex[:12]}",
        "user_id": "demo",
        "date": days_ago(min(days, 30) - 21),
        "type": "zscore_spike",
        "severity": "high",
        "scope": "platform",
        "platform": "claude_code",
        "resource": "claude-opus-4-7",
        "cost": 415.00,
        "baseline_mean": 180.00,
        "baseline_stddev": 28.00,
        "baseline": 180.00,
        "zscore": 8.39,
        "change_pct": 130.5,
        "message": (
            "Claude Code spend jumped 130% — cache_read tokens dropped from 78% "
            "→ 22% of total tokens after last Tuesday's agent deploy. Likely a "
            "system-prompt regression broke prompt caching."
        ),
        "detected_at": detected_at,
        "acknowledged": False,
    })

    # 4) Resource-level: AWS Redshift nightly burst.
    anomalies.append({
        "_id": f"anom_{uuid.uuid4().hex[:12]}",
        "user_id": "demo",
        "date": days_ago(min(days, 30) - 4),
        "type": "zscore_spike",
        "severity": "medium",
        "scope": "resource",
        "platform": "aws",
        "resource": "aws_redshift",
        "cost": 88.40,
        "baseline_mean": 45.20,
        "baseline_stddev": 6.80,
        "baseline": 45.20,
        "zscore": 6.35,
        "change_pct": 95.5,
        "message": (
            "aws_redshift cost of $88 is 96% above its $45 average (z-score: 6.4). "
            "Concurrency scaling fired 3× during the 23:00 UTC load window."
        ),
        "detected_at": detected_at,
        "acknowledged": False,
    })

    # 5) Week-over-week creep on OpenAI gpt-5 (already acknowledged — shows
    #    the "resolved" state alongside live anomalies).
    anomalies.append({
        "_id": f"anom_{uuid.uuid4().hex[:12]}",
        "user_id": "demo",
        "date": days_ago(min(days, 30) - 12),
        "type": "week_over_week_spike",
        "severity": "medium",
        "scope": "resource",
        "platform": "openai",
        "resource": "gpt-5",
        "cost": 142.30,
        "previous_cost": 96.00,
        "baseline": 96.00,
        "pct_change": 48.2,
        "change_pct": 48.2,
        "message": (
            "gpt-5 spend up 48% week-over-week: $142 vs $96 same day last week. "
            "Traffic from a new summarization feature. Consider gpt-5-mini."
        ),
        "detected_at": detected_at,
        "acknowledged": True,
        "acknowledged_at": detected_at,
    })

    # Sort newest first to match real API ordering.
    anomalies.sort(key=lambda a: a["date"], reverse=True)

    return {
        "anomalies": anomalies,
        "count": len(anomalies),
        "unacknowledged": sum(1 for a in anomalies if not a.get("acknowledged")),
    }


def generate_demo_chat_sample() -> dict:
    """Seed a realistic saved chat conversation for first-time demo visitors.

    Returns a payload with a list of messages + inline chart artifacts that
    the chat UI can render before the visitor types anything. Demonstrates
    what the agent does without requiring the visitor to ask a question.
    """
    return {
        "conversation_id": "demo_conv_001",
        "title": "Costly walkthrough",
        "created_at": datetime.utcnow().isoformat(),
        "messages": [
            {
                "role": "user",
                "content": "What drove last week's spend spike on Snowflake?",
            },
            {
                "role": "assistant",
                "expert": "snowflake",
                "expert_name": "Snowflake Expert",
                "content": (
                    "Last week's spend was **$1,847**, about **+72% vs the prior 4-week "
                    "median of $1,074**. Two events account for nearly all of the delta:\n\n"
                    "1. **ETL_WH overnight run on Mar 30** — the `ingest_events` task "
                    "failed to release its warehouse and burned **$312** between "
                    "23:00 and 10:00 the next morning (180 credits at $3.00/credit). "
                    "Remote spillage peaked at 3.2 GB.\n"
                    "2. **Monday refresh storm on Apr 1** — six dashboards fired "
                    "simultaneously at 07:00, spiking ANALYTICS_WH to queue-depth 4 "
                    "for 42 minutes. Net incremental cost: **$172**.\n\n"
                    "Everything else is within 1σ of baseline."
                ),
                "artifacts": [
                    {
                        "type": "chart",
                        "chart_type": "area",
                        "title": "Daily Snowflake spend — last 30 days",
                        "data": [
                            {"date": days_ago(29 - i), "cost": v}
                            for i, v in enumerate([
                                155, 162, 148, 159, 171, 95, 88, 480, 155, 162,
                                149, 158, 167, 92, 91, 159, 163, 152, 310, 161,
                                147, 94, 92, 156, 165, 153, 162, 168, 150, 160,
                            ])
                        ],
                    },
                    {
                        "type": "table",
                        "title": "Top 5 contributors (last 7 days)",
                        "columns": ["resource", "cost_usd", "delta_pct"],
                        "rows": [
                            {"resource": "ETL_WH", "cost_usd": 412.00, "delta_pct": 185.0},
                            {"resource": "ANALYTICS_WH", "cost_usd": 535.20, "delta_pct": 42.0},
                            {"resource": "COMPUTE_WH", "cost_usd": 631.50, "delta_pct": 5.1},
                            {"resource": "aws_redshift", "cost_usd": 88.40, "delta_pct": 95.5},
                            {"resource": "REPORTING_WH", "cost_usd": 66.30, "delta_pct": -3.2},
                        ],
                    },
                ],
            },
            {
                "role": "user",
                "content": "How do we stop the ETL warehouse from running overnight again?",
            },
            {
                "role": "assistant",
                "expert": "snowflake",
                "expert_name": "Snowflake Expert",
                "content": (
                    "Two durable fixes, both low-effort:\n\n"
                    "**1. Tighten auto-suspend on ETL_WH.** Currently 60s — that's fine, "
                    "but the root cause was a stuck Airflow task, not idle waste. "
                    "A hard ceiling helps catch recurrences:\n\n"
                    "```sql\n"
                    "ALTER WAREHOUSE ETL_WH SET\n"
                    "  AUTO_SUSPEND = 60,\n"
                    "  STATEMENT_TIMEOUT_IN_SECONDS = 3600;  -- kill any task > 1h\n"
                    "```\n\n"
                    "**2. Add a cost alert.** Let me set one up:\n\n"
                    "> Alert: ETL_WH daily cost > $200 → Slack #data-alerts\n\n"
                    "Click **Apply via GitHub PR** on the Recommendations tab for option 1, "
                    "or say *\"create the alert\"* here and I'll post it."
                ),
            },
        ],
    }


def generate_demo_workloads(days=30):
    workloads = [
        {"workload_id": "wl_001", "sample_query": "SELECT DATE_TRUNC('month', o_orderdate) AS month, SUM(o_totalprice) AS revenue, COUNT(*) AS orders, COUNT(DISTINCT o_custkey) AS customers FROM COSTLY_DEMO.SALES.ORDERS GROUP BY 1 ORDER BY 1", "execution_count": 487, "avg_seconds": 12.4, "p95_seconds": 28.1, "total_seconds": 6038.8, "total_credits": 0.42, "total_gb_scanned": 142.3, "last_seen": days_ago(0), "sample_user": "REPORTING_ROLE", "sample_warehouse": "REPORTING_WH"},
        {"workload_id": "wl_002", "sample_query": "SELECT event_type, COUNT(*), SUM(revenue) FROM COSTLY_DEMO.MARKETING.WEBSITE_EVENTS GROUP BY 1", "execution_count": 312, "avg_seconds": 8.7, "p95_seconds": 18.3, "total_seconds": 2714.4, "total_credits": 0.19, "total_gb_scanned": 89.6, "last_seen": days_ago(0), "sample_user": "ANALYST_ROLE", "sample_warehouse": "ANALYTICS_WH"},
        {"workload_id": "wl_003", "sample_query": "SELECT o_orderstatus, COUNT(*) AS cnt, SUM(o_totalprice) AS total FROM COSTLY_DEMO.SALES.ORDERS WHERE o_orderdate >= '1995-01-01' GROUP BY 1 ORDER BY 3 DESC", "execution_count": 148, "avg_seconds": 22.1, "p95_seconds": 45.8, "total_seconds": 3270.8, "total_credits": 0.31, "total_gb_scanned": 201.4, "last_seen": days_ago(1), "sample_user": "ANALYST_ROLE", "sample_warehouse": "ANALYTICS_WH"},
        {"workload_id": "wl_004", "sample_query": "SELECT c.c_name, c.c_nationkey, SUM(o.o_totalprice) AS total_spend FROM COSTLY_DEMO.SALES.CUSTOMERS c JOIN COSTLY_DEMO.SALES.ORDERS o ON c.c_custkey = o.o_custkey GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 100", "execution_count": 89, "avg_seconds": 31.5, "p95_seconds": 67.2, "total_seconds": 2803.5, "total_credits": 0.27, "total_gb_scanned": 315.8, "last_seen": days_ago(0), "sample_user": "REPORTING_ROLE", "sample_warehouse": "REPORTING_WH"},
        {"workload_id": "wl_005", "sample_query": "SELECT * FROM COSTLY_DEMO.SALES.LINEITEMS LIMIT 10000", "execution_count": 34, "avg_seconds": 58.3, "p95_seconds": 112.4, "total_seconds": 1982.2, "total_credits": 0.18, "total_gb_scanned": 478.2, "last_seen": days_ago(2), "sample_user": "ANALYST_ROLE", "sample_warehouse": "DEV_WH"},
        {"workload_id": "wl_006", "sample_query": "SELECT COUNT(*) FROM COSTLY_DEMO.SALES.ORDERS", "execution_count": 5, "avg_seconds": 3.2, "p95_seconds": 4.1, "total_seconds": 16.0, "total_credits": 0.001, "total_gb_scanned": 12.4, "last_seen": days_ago(1), "sample_user": "ANALYST_ROLE", "sample_warehouse": "ANALYTICS_WH"},
        {"workload_id": "wl_007", "sample_query": "INSERT INTO COSTLY_DEMO.RAW.ORDERS_STAGING SELECT *, CURRENT_TIMESTAMP() AS loaded_at FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.ORDERS LIMIT 10000", "execution_count": 3, "avg_seconds": 15.7, "p95_seconds": 18.2, "total_seconds": 47.1, "total_credits": 0.008, "total_gb_scanned": 24.6, "last_seen": days_ago(0), "sample_user": "ETL_ROLE", "sample_warehouse": "ETL_WH"},
    ]
    return {
        "workloads": workloads,
        "total_workloads": len(workloads),
        "total_executions": sum(w["execution_count"] for w in workloads),
        "days": days,
    }


def generate_demo_workload_runs(workload_id: str, days: int):
    rng = random.Random(hash(workload_id) & 0xFFFFFF)
    runs = []
    for i in range(min(20, rng.randint(3, 25))):
        dt = datetime.now() - timedelta(hours=rng.randint(1, days * 24))
        dur = rng.uniform(5000, 120000)
        runs.append({
            "query_id": f"Q{uuid.uuid4().hex[:8].upper()}",
            "start_time": dt.isoformat(),
            "duration_ms": int(dur),
            "user": rng.choice(["ANALYST_ROLE", "REPORTING_ROLE", "ETL_ROLE"]),
            "warehouse": rng.choice(["ANALYTICS_WH", "REPORTING_WH", "DEV_WH"]),
            "bytes_scanned": rng.randint(10_000_000, 5_000_000_000),
            "rows_produced": rng.randint(100, 500_000),
            "cache_hit_pct": round(rng.uniform(0, 100), 1),
        })
    runs.sort(key=lambda x: x["start_time"], reverse=True)
    return {"runs": runs, "workload_id": workload_id}


def generate_demo_warehouse_sizing():
    return {
        "recommendations": [
            {"warehouse": "ANALYTICS_WH", "current_size": "Large", "recommended_size": "Medium", "avg_utilization": 0.18, "spill_local_gb": 0.08, "spill_remote_gb": 0.0, "monthly_savings": 535.20, "ddl_command": "ALTER WAREHOUSE ANALYTICS_WH SET WAREHOUSE_SIZE = 'Medium';", "reason": "Average utilization is 18% with no remote spillage — warehouse is over-provisioned", "needs_change": True},
            {"warehouse": "COMPUTE_WH", "current_size": "Medium", "recommended_size": "Medium", "avg_utilization": 0.42, "spill_local_gb": 0.21, "spill_remote_gb": 0.0, "monthly_savings": 0.0, "ddl_command": None, "reason": "Current sizing appears appropriate", "needs_change": False},
            {"warehouse": "ETL_WH", "current_size": "Small", "recommended_size": "Medium", "avg_utilization": 0.85, "spill_local_gb": 2.84, "spill_remote_gb": 1.62, "monthly_savings": 0.0, "ddl_command": "ALTER WAREHOUSE ETL_WH SET WAREHOUSE_SIZE = 'Medium';", "reason": "Remote spillage of 1.6 GB detected — warehouse is undersized for workload", "needs_change": True},
            {"warehouse": "REPORTING_WH", "current_size": "X-Small", "recommended_size": "X-Small", "avg_utilization": 0.12, "spill_local_gb": 0.0, "spill_remote_gb": 0.0, "monthly_savings": 0.0, "ddl_command": None, "reason": "Current sizing appears appropriate", "needs_change": False},
        ],
        "total_monthly_savings": 535.20,
        "days": 30,
    }


def generate_demo_autosuspend():
    return {
        "recommendations": [
            {"warehouse": "ANALYTICS_WH", "current_suspend_s": 600, "recommended_suspend_s": 120, "resume_count": 340, "idle_waste_credits": 48.5, "monthly_savings": 145.50, "ddl_command": "ALTER WAREHOUSE ANALYTICS_WH SET AUTO_SUSPEND = 120;", "gap_p50_s": 45, "gap_p75_s": 95, "needs_change": True},
            {"warehouse": "COMPUTE_WH", "current_suspend_s": 300, "recommended_suspend_s": 180, "resume_count": 520, "idle_waste_credits": 22.4, "monthly_savings": 67.20, "ddl_command": "ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 180;", "gap_p50_s": 82, "gap_p75_s": 165, "needs_change": True},
            {"warehouse": "ETL_WH", "current_suspend_s": 60, "recommended_suspend_s": 60, "resume_count": 85, "idle_waste_credits": 0.0, "monthly_savings": 0.0, "ddl_command": None, "gap_p50_s": 1200, "gap_p75_s": 2400, "needs_change": False},
            {"warehouse": "REPORTING_WH", "current_suspend_s": 120, "recommended_suspend_s": 120, "resume_count": 42, "idle_waste_credits": 0.0, "monthly_savings": 0.0, "ddl_command": None, "gap_p50_s": 55, "gap_p75_s": 110, "needs_change": False},
        ],
        "total_monthly_savings": 212.70,
        "days": 30,
    }


def generate_demo_spillage():
    return {
        "by_warehouse": [
            {"warehouse": "ETL_WH", "query_count": 142, "spill_local_gb": 28.4, "spill_remote_gb": 6.2},
            {"warehouse": "ANALYTICS_WH", "query_count": 38, "spill_local_gb": 4.8, "spill_remote_gb": 0.4},
            {"warehouse": "COMPUTE_WH", "query_count": 12, "spill_local_gb": 1.2, "spill_remote_gb": 0.0},
        ],
        "by_user": [
            {"user": "ETL_PIPELINE", "query_count": 98, "spill_local_gb": 22.1, "spill_remote_gb": 5.8},
            {"user": "ANALYTICS_SVC", "query_count": 52, "spill_local_gb": 8.4, "spill_remote_gb": 0.6},
            {"user": "ALICE", "query_count": 18, "spill_local_gb": 2.1, "spill_remote_gb": 0.1},
        ],
        "top_queries": [
            {"query_id": "QSPILL001", "warehouse": "ETL_WH", "user": "ETL_PIPELINE", "warehouse_size": "SMALL", "spill_local_gb": 18.4, "spill_remote_gb": 3.2, "duration_s": 480.0, "query_text": "SELECT * FROM large_events_table WHERE event_date BETWEEN '2024-01-01' AND '2025-01-01'"},
            {"query_id": "QSPILL002", "warehouse": "ETL_WH", "user": "ETL_PIPELINE", "warehouse_size": "SMALL", "spill_local_gb": 8.6, "spill_remote_gb": 2.1, "duration_s": 320.5, "query_text": "INSERT INTO staging.events SELECT *, CURRENT_TIMESTAMP() FROM raw.events WHERE loaded_at >= '2025-01-01'"},
        ],
        "summary": {
            "total_spill_gb": 41.0,
            "affected_queries": 192,
            "affected_warehouses": 3,
        },
        "days": 30,
    }


def generate_demo_query_patterns():
    return {
        "patterns": [
            {"pattern_hash": "p_001", "example_query": "SELECT DATE_TRUNC('month', order_date) AS month, SUM(total) FROM orders GROUP BY 1 ORDER BY 1", "execution_count": 487, "total_cost_usd": 42.50, "avg_duration_s": 12.4, "avg_scan_ratio": 0.35, "avg_spill_gb": 0.0, "avg_cache_pct": 68.2, "flags": ["cacheable"], "recommendation": "High cache hit rate — consider result caching or materialized views"},
            {"pattern_hash": "p_002", "example_query": "SELECT * FROM events WHERE event_date >= ? AND event_date < ?", "execution_count": 312, "total_cost_usd": 38.20, "avg_duration_s": 8.7, "avg_scan_ratio": 0.92, "avg_spill_gb": 0.0, "avg_cache_pct": 12.1, "flags": ["full_scan"], "recommendation": "Scanning >80% of partitions — add clustering keys on filter columns"},
            {"pattern_hash": "p_003", "example_query": "SELECT c.name, SUM(o.total) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY 1", "execution_count": 148, "total_cost_usd": 28.90, "avg_duration_s": 22.1, "avg_scan_ratio": 0.45, "avg_spill_gb": 1.8, "avg_cache_pct": 5.2, "flags": ["spilling"], "recommendation": "Query is spilling to disk — consider a larger warehouse or optimize query"},
            {"pattern_hash": "p_004", "example_query": "INSERT INTO analytics.daily_summary SELECT DATE(ts), COUNT(*), SUM(revenue) FROM raw_events GROUP BY 1", "execution_count": 89, "total_cost_usd": 22.40, "avg_duration_s": 31.5, "avg_scan_ratio": 1.0, "avg_spill_gb": 0.5, "avg_cache_pct": 0.0, "flags": ["full_scan", "spilling"], "recommendation": "Scanning >80% of partitions — add clustering keys on filter columns"},
            {"pattern_hash": "p_005", "example_query": "SELECT COUNT(*) FROM orders WHERE status = ?", "execution_count": 1240, "total_cost_usd": 8.60, "avg_duration_s": 1.2, "avg_scan_ratio": 0.08, "avg_spill_gb": 0.0, "avg_cache_pct": 82.5, "flags": ["cacheable"], "recommendation": "High cache hit rate — consider result caching or materialized views"},
            {"pattern_hash": "p_006", "example_query": "WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY ts) FROM events) SELECT * FROM ranked WHERE rn = 1", "execution_count": 34, "total_cost_usd": 18.20, "avg_duration_s": 58.3, "avg_scan_ratio": 0.72, "avg_spill_gb": 3.2, "avg_cache_pct": 2.1, "flags": ["spilling"], "recommendation": "Query is spilling to disk — consider a larger warehouse or optimize query"},
            {"pattern_hash": "p_007", "example_query": "SELECT * FROM users LIMIT 10000", "execution_count": 5, "total_cost_usd": 1.20, "avg_duration_s": 3.2, "avg_scan_ratio": 0.02, "avg_spill_gb": 0.0, "avg_cache_pct": 45.0, "flags": [], "recommendation": "No immediate optimization needed"},
        ],
        "total_patterns": 7,
        "total_cost_usd": 160.00,
        "days": 30,
    }


def generate_demo_cost_attribution():
    return {
        "by_user": [
            {"user": "ETL_PIPELINE", "cost_usd": 1450.00, "query_count": 3200, "pct": 32.1},
            {"user": "ANALYTICS_SVC", "cost_usd": 1180.00, "query_count": 1850, "pct": 26.1},
            {"user": "NITIN", "cost_usd": 890.00, "query_count": 420, "pct": 19.7},
            {"user": "ALICE", "cost_usd": 620.00, "query_count": 210, "pct": 13.7},
            {"user": "BOB", "cost_usd": 380.00, "query_count": 95, "pct": 8.4},
        ],
        "by_role": [
            {"role": "ETL_ROLE", "cost_usd": 1620.00, "query_count": 3400, "pct": 35.9},
            {"role": "ANALYST_ROLE", "cost_usd": 1450.00, "query_count": 2100, "pct": 32.1},
            {"role": "ACCOUNTADMIN", "cost_usd": 980.00, "query_count": 520, "pct": 21.7},
            {"role": "REPORTING_ROLE", "cost_usd": 470.00, "query_count": 1200, "pct": 10.4},
        ],
        "by_database": [
            {"database": "PROD_DB", "cost_usd": 1840.00, "query_count": 2800, "pct": 40.7},
            {"database": "ANALYTICS_DB", "cost_usd": 1290.00, "query_count": 1950, "pct": 28.6},
            {"database": "RAW_DATA", "cost_usd": 920.00, "query_count": 1400, "pct": 20.4},
            {"database": "STAGING", "cost_usd": 470.00, "query_count": 850, "pct": 10.4},
        ],
        "by_warehouse": [
            {"warehouse": "ANALYTICS_WH", "cost_usd": 1605.60, "credits": 535.2},
            {"warehouse": "COMPUTE_WH", "cost_usd": 1894.50, "credits": 631.5},
            {"warehouse": "ETL_WH", "cost_usd": 743.40, "credits": 247.8},
            {"warehouse": "REPORTING_WH", "cost_usd": 198.90, "credits": 66.3},
        ],
        "top_queries": [
            {"query_id": "QCOST001", "user": "ETL_PIPELINE", "warehouse": "ETL_WH", "role": "ETL_ROLE", "duration_s": 480.0, "query_text": "SELECT * FROM large_events_table WHERE event_date BETWEEN '2024-01-01' AND '2025-01-01'", "est_cost_usd": 2.40},
            {"query_id": "QCOST002", "user": "ANALYTICS_SVC", "warehouse": "ANALYTICS_WH", "role": "ANALYST_ROLE", "duration_s": 245.0, "query_text": "WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY ts) FROM events) SELECT * FROM ranked", "est_cost_usd": 1.80},
        ],
        "total_cost_usd": 4520.00,
        "days": 30,
    }


def generate_demo_stale_tables():
    return {
        "stale_tables": [
            {"database": "RAW_DATA", "schema": "PUBLIC", "table": "EVENTS_ARCHIVE_2023", "size_gb": 48.2, "last_queried": "2025-06-15", "days_since_queried": 210, "monthly_cost": 1.11, "recommendation": "Drop or archive"},
            {"database": "STAGING", "schema": "PUBLIC", "table": "ORDERS_IMPORT_Q3_2023", "size_gb": 22.8, "last_queried": "2025-08-20", "days_since_queried": 185, "monthly_cost": 0.52, "recommendation": "Drop or archive"},
            {"database": "ANALYTICS_DB", "schema": "PUBLIC", "table": "TEMP_ANALYSIS_NOV2023", "size_gb": 15.4, "last_queried": "2025-10-05", "days_since_queried": 140, "monthly_cost": 0.35, "recommendation": "Review usage"},
        ],
        "stale_count": 3,
        "stale_total_gb": 86.4,
        "stale_monthly_cost": 1.98,
        "days": 30,
    }



#: Claude Code tool mix — each entry is (tool_name, share_of_claude_code_cost, avg_call_seconds).
#: Shares sum to 1.0; they roughly match the real distribution emitted by the
#: Claude Code connector (Bash and Edit dominate, WebFetch/Read trail).
_CLAUDE_CODE_TOOL_MIX = [
    ("Bash", 0.32, 3.1),
    ("Edit", 0.24, 1.6),
    ("Read", 0.18, 0.8),
    ("Write", 0.09, 1.2),
    ("Grep", 0.07, 0.9),
    ("WebFetch", 0.06, 4.5),
    ("Glob", 0.02, 0.4),
    ("TodoWrite", 0.02, 0.3),
]


def generate_demo_ai_costs(days: int = 30) -> dict:
    """Mock AI cost data across Anthropic, Claude Code, OpenAI, Gemini.

    Tells the prompt-caching story: high cache-hit baseline, a dip around
    day -10 (regression), and a recovery after a fix. Shape matches the
    /api/ai-costs endpoint response.
    """
    rng = random.Random(1337)
    providers = ["anthropic", "claude_code", "openai", "gemini"]

    # Daily per-provider spend — tells a story over the period
    daily_spend = []
    daily_tokens = []
    for i in range(days):
        date = days_ago(days - 1 - i)

        # Baseline spend per provider, with weekday/weekend variation
        wk = (datetime.now() - timedelta(days=days - 1 - i)).weekday()
        weekday_mult = 1.0 if wk < 5 else 0.55

        anthropic_api = round(rng.uniform(25, 45) * weekday_mult, 2)
        claude_code = round(rng.uniform(120, 240) * weekday_mult, 2)
        openai = round(rng.uniform(40, 90) * weekday_mult, 2)
        gemini = round(rng.uniform(8, 25) * weekday_mult, 2)

        # Prompt-caching regression: days 19-23 have a spike
        if 19 <= i <= 23:
            claude_code = round(claude_code * 1.85, 2)
            anthropic_api = round(anthropic_api * 1.55, 2)

        daily_spend.append({
            "date": date,
            "anthropic": anthropic_api,
            "claude_code": claude_code,
            "openai": openai,
            "gemini": gemini,
        })

        # Token mix per day — cache-heavy for Claude tiers, less for OpenAI/Gemini
        total_tokens = int((anthropic_api + claude_code) * 1_300_000 / 3.0 + (openai + gemini) * 250_000)
        if 19 <= i <= 23:
            # cache collapse — cache_read drops, cache_write surges
            cache_read_pct = 0.22
            cache_write_pct = 0.28
        else:
            cache_read_pct = 0.78
            cache_write_pct = 0.09
        input_pct = max(0.0, 1 - cache_read_pct - cache_write_pct - 0.03)
        output_pct = 0.03

        daily_tokens.append({
            "date": date,
            "cache_read": int(total_tokens * cache_read_pct),
            "cache_write": int(total_tokens * cache_write_pct),
            "input": int(total_tokens * input_pct),
            "output": int(total_tokens * output_pct),
            "total": total_tokens,
        })

    # Aggregate KPIs
    total_cost = round(sum(sum(d[p] for p in providers) for d in daily_spend), 2)
    total_tokens = sum(d["total"] for d in daily_tokens)
    total_cache_read = sum(d["cache_read"] for d in daily_tokens)
    total_cache_write = sum(d["cache_write"] for d in daily_tokens)
    total_uncached_input = sum(d["input"] for d in daily_tokens)
    total_output = sum(d["output"] for d in daily_tokens)

    cache_denom = total_cache_read + total_cache_write + total_uncached_input
    cache_hit_rate = round(total_cache_read / cache_denom * 100, 1) if cache_denom else 0.0
    cache_savings_usd = round((total_cache_read * 2.70) / 1_000_000, 2)
    avg_cost_per_1k = round(total_cost / total_tokens * 1000, 4) if total_tokens else 0

    # Prior period for mom_change — roughly -8% so the trend looks positive
    mom_change = -8.4

    providers_list = [
        {
            "platform": "anthropic",
            "cost": round(sum(d["anthropic"] for d in daily_spend), 2),
            "tokens": int(total_tokens * 0.12),
            "input_tokens": int(total_tokens * 0.03),
            "output_tokens": int(total_tokens * 0.006),
            "cost_per_1k": 0.072,
        },
        {
            "platform": "claude_code",
            "cost": round(sum(d["claude_code"] for d in daily_spend), 2),
            "tokens": int(total_tokens * 0.72),
            "input_tokens": int(total_tokens * 0.14),
            "output_tokens": int(total_tokens * 0.02),
            "cost_per_1k": 0.0041,
        },
        {
            "platform": "openai",
            "cost": round(sum(d["openai"] for d in daily_spend), 2),
            "tokens": int(total_tokens * 0.12),
            "input_tokens": int(total_tokens * 0.05),
            "output_tokens": int(total_tokens * 0.008),
            "cost_per_1k": 0.0185,
        },
        {
            "platform": "gemini",
            "cost": round(sum(d["gemini"] for d in daily_spend), 2),
            "tokens": int(total_tokens * 0.04),
            "input_tokens": int(total_tokens * 0.015),
            "output_tokens": int(total_tokens * 0.003),
            "cost_per_1k": 0.019,
        },
    ]

    cost_per_1k_trend = []
    for i, d in enumerate(daily_tokens):
        day_cost = sum(daily_spend[i][p] for p in providers)
        cpk = round(day_cost / d["total"] * 1000, 4) if d["total"] else 0
        cost_per_1k_trend.append({"date": d["date"], "cost_per_1k": cpk})

    model_breakdown = [
        {"model": "claude-opus-4-7", "platform": "claude_code", "cost": 2890.50, "tokens": int(total_tokens * 0.38), "input_tokens": int(total_tokens * 0.04), "output_tokens": int(total_tokens * 0.009), "cost_per_1k": 0.0056},
        {"model": "claude-sonnet-4-6", "platform": "claude_code", "cost": 1420.30, "tokens": int(total_tokens * 0.30), "input_tokens": int(total_tokens * 0.08), "output_tokens": int(total_tokens * 0.01), "cost_per_1k": 0.0038},
        {"model": "gpt-5", "platform": "openai", "cost": 1180.20, "tokens": int(total_tokens * 0.08), "input_tokens": int(total_tokens * 0.03), "output_tokens": int(total_tokens * 0.006), "cost_per_1k": 0.0198},
        {"model": "claude-opus-4-7", "platform": "anthropic", "cost": 785.40, "tokens": int(total_tokens * 0.09), "input_tokens": int(total_tokens * 0.022), "output_tokens": int(total_tokens * 0.004), "cost_per_1k": 0.065},
        {"model": "gpt-5-mini", "platform": "openai", "cost": 240.80, "tokens": int(total_tokens * 0.04), "input_tokens": int(total_tokens * 0.02), "output_tokens": int(total_tokens * 0.002), "cost_per_1k": 0.008},
        {"model": "gemini-2.5-pro", "platform": "gemini", "cost": 285.60, "tokens": int(total_tokens * 0.025), "input_tokens": int(total_tokens * 0.01), "output_tokens": int(total_tokens * 0.0018), "cost_per_1k": 0.021},
        {"model": "gemini-2.5-flash", "platform": "gemini", "cost": 112.40, "tokens": int(total_tokens * 0.015), "input_tokens": int(total_tokens * 0.005), "output_tokens": int(total_tokens * 0.0012), "cost_per_1k": 0.006},
        {"model": "claude-haiku-4-5", "platform": "anthropic", "cost": 56.20, "tokens": int(total_tokens * 0.008), "input_tokens": int(total_tokens * 0.002), "output_tokens": int(total_tokens * 0.0003), "cost_per_1k": 0.009},
    ]

    recommendations = [
        {
            "type": "token_efficiency",
            "title": "Cache-hit rate regression detected (days 19-23)",
            "description": "Cache hit rate fell from 78% to 22% on your Claude Code sales-agent workflow after last Tuesday's deploy. Restoring cache-friendly system prompts could recover ~$1,400/mo.",
            "potential_savings": 1420.00,
        },
        {
            "type": "model_migration",
            "title": "Switch claude-opus-4-7 anthropic → claude-sonnet-4-6",
            "description": "Moving claude-opus-4-7 API calls to claude-sonnet-4-6 could save ~80% while maintaining quality for most tasks.",
            "potential_savings": 628.30,
        },
        {
            "type": "model_migration",
            "title": "Switch gpt-5 → gpt-5-mini for low-complexity calls",
            "description": "An estimated 40% of gpt-5 calls are single-step classification and summary. Migrating those to gpt-5-mini saves ~$470/mo.",
            "potential_savings": 472.00,
        },
    ]

    # ── Claude Code tool-use breakdown ─────────────────────────────────────
    # Per-day cost and call count for each tool (Bash / Edit / Read / ...).
    # Mirrors what the real Claude Code connector emits under the `tool_use`
    # key of the /api/ai-costs response.
    tool_use_daily: list[dict] = []
    tool_use_rng = random.Random(7331)
    for d in daily_spend:
        cc_cost = d["claude_code"]
        row: dict = {"date": d["date"]}
        for tool_name, share, avg_seconds in _CLAUDE_CODE_TOOL_MIX:
            # Add light per-day jitter so the chart isn't flat proportional.
            jitter = tool_use_rng.uniform(0.85, 1.15)
            tool_cost = round(cc_cost * share * jitter, 2)
            # Derive call count from cost and a fake cost/call heuristic:
            # Claude Code ~ $0.013/tool-call on average, with variance by tool.
            cost_per_call = {
                "Bash": 0.015, "Edit": 0.011, "Read": 0.008, "Write": 0.012,
                "Grep": 0.009, "WebFetch": 0.021, "Glob": 0.005, "TodoWrite": 0.004,
            }.get(tool_name, 0.012)
            calls = int(tool_cost / cost_per_call) if cost_per_call else 0
            row[tool_name] = tool_cost
            row[f"{tool_name}_calls"] = calls
            row[f"{tool_name}_avg_seconds"] = avg_seconds
        tool_use_daily.append(row)

    # Aggregated totals per tool across the period.
    tool_use_totals = []
    for tool_name, share, avg_seconds in _CLAUDE_CODE_TOOL_MIX:
        tool_total_cost = round(sum(d[tool_name] for d in tool_use_daily), 2)
        tool_total_calls = sum(d[f"{tool_name}_calls"] for d in tool_use_daily)
        tool_use_totals.append({
            "tool": tool_name,
            "cost": tool_total_cost,
            "calls": tool_total_calls,
            "avg_seconds": avg_seconds,
            "pct": round(share * 100, 1),
        })
    tool_use_totals.sort(key=lambda x: -x["cost"])

    return {
        "kpis": {
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "avg_cost_per_1k": avg_cost_per_1k,
            "mom_change": mom_change,
            "model_count": len(model_breakdown),
            "provider_count": 4,
            "cache_hit_rate": cache_hit_rate,
            "cache_savings_usd": cache_savings_usd,
            "cache_read_tokens": total_cache_read,
            "cache_write_tokens": total_cache_write,
        },
        "providers": providers_list,
        "daily_spend": daily_spend,
        "daily_tokens": daily_tokens,
        "cost_per_1k_trend": cost_per_1k_trend,
        "model_breakdown": model_breakdown,
        "recommendations": recommendations,
        "tool_use": {
            "daily": tool_use_daily,
            "totals": tool_use_totals,
        },
    }
