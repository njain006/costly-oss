import math
import snowflake.connector
from contextlib import contextmanager
from datetime import datetime

from app.services.encryption import decrypt_value
from app.services.cache import cache
from app.utils.constants import CREDITS_MAP, CACHE_TTL
from app.utils.helpers import run_in_thread


def build_sf_connection(conn_doc: dict):
    params = {
        "account": conn_doc["account"],
        "user": conn_doc["username"],
        "warehouse": conn_doc["warehouse"],
        "database": conn_doc["database"],
        "schema": conn_doc["schema_name"],
        "role": conn_doc["role"],
        "login_timeout": 15,
        "network_timeout": 30,
    }
    if conn_doc["auth_type"] == "password":
        params["password"] = decrypt_value(conn_doc["password_encrypted"])
    elif conn_doc["auth_type"] == "keypair":
        from cryptography.hazmat.primitives.serialization import (
            load_pem_private_key, Encoding, PrivateFormat, NoEncryption
        )
        from cryptography.hazmat.backends import default_backend
        key_str = decrypt_value(conn_doc["private_key_encrypted"])
        passphrase = None
        if conn_doc.get("private_key_passphrase_encrypted"):
            passphrase = decrypt_value(conn_doc["private_key_passphrase_encrypted"]).encode()
        pk = load_pem_private_key(key_str.encode(), password=passphrase, backend=default_backend())
        params["private_key"] = pk.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    return snowflake.connector.connect(**params)


@contextmanager
def sf_connection(conn_doc: dict):
    """Context manager that ensures Snowflake connections are always closed."""
    conn = build_sf_connection(conn_doc)
    try:
        yield conn
    finally:
        conn.close()


def conn_to_response(doc: dict) -> dict:
    return {
        "connection_id": doc["connection_id"],
        "connection_name": doc["connection_name"],
        "account": doc["account"],
        "username": doc["username"],
        "auth_type": doc["auth_type"],
        "warehouse": doc["warehouse"],
        "database": doc["database"],
        "schema_name": doc["schema_name"],
        "role": doc["role"],
        "is_active": doc["is_active"],
        "test_status": doc.get("test_status"),
        "last_tested_at": doc.get("last_tested_at"),
        "created_at": doc["created_at"],
    }


def _sync_get_credit_price(conn_doc: dict) -> float:
    try:
        with sf_connection(conn_doc) as sf:
            cur = sf.cursor()
            cur.execute("""
                SELECT EFFECTIVE_RATE
                FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY
                WHERE SERVICE_TYPE = 'COMPUTE'
                ORDER BY DATE DESC LIMIT 1
            """)
            row = cur.fetchone()
            return float(row[0]) if row else 3.0
    except Exception:
        return 3.0


async def get_credit_price(conn_doc: dict) -> float:
    key = f"credit_price:{conn_doc['connection_id']}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    price = await run_in_thread(_sync_get_credit_price, conn_doc)
    cache.set(key, price, CACHE_TTL["credit_price"])
    return price


def sync_dashboard(conn_doc: dict, days: int, credit_price: float) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        cur.execute(f"""
            SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
                   SUM(CREDITS_USED_COMPUTE * {credit_price}) AS compute_cost,
                   SUM(CREDITS_USED_CLOUD_SERVICES * {credit_price}) AS cloud_services_cost,
                   SUM((CREDITS_USED_COMPUTE + CREDITS_USED_CLOUD_SERVICES) * {credit_price}) AS cost,
                   SUM(CREDITS_USED_COMPUTE) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 1
        """)
        cost_trend = [
            {
                "date": str(r[0]),
                "compute_cost": round(float(r[1] or 0), 2),
                "cloud_services_cost": round(float(r[2] or 0), 2),
                "cost": round(float(r[3] or 0), 2),
                "credits": round(float(r[4] or 0), 2),
            }
            for r in cur.fetchall()
        ]
        cur.execute(f"""
            SELECT WAREHOUSE_NAME,
                   SUM(CREDITS_USED_COMPUTE) AS credits,
                   SUM(CREDITS_USED_COMPUTE * {credit_price}) AS cost
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """)
        top_warehouses = [
            {"name": r[0], "credits": round(float(r[1] or 0), 2), "cost": round(float(r[2] or 0), 2)}
            for r in cur.fetchall()
        ]
        cur.execute(f"""
            SELECT
                COUNT(*) AS total_queries,
                COUNT_IF(TOTAL_ELAPSED_TIME > 60000) AS expensive_queries,
                COUNT_IF(EXECUTION_STATUS != 'SUCCESS') AS failed_queries
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        """)
        row = cur.fetchone()
        total_queries = int(row[0] or 0)
        expensive_queries = int(row[1] or 0)
        failed_queries = int(row[2] or 0)
        cur.execute(f"""
            SELECT USER_NAME,
                   SUM(CREDITS_USED_CLOUD_SERVICES * {credit_price}) AS cost,
                   COUNT(*) AS queries
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND IS_CLIENT_GENERATED_STATEMENT = FALSE
            GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """)
        top_users = [
            {"user": r[0], "cost": round(float(r[1] or 0), 2), "queries": int(r[2] or 0)}
            for r in cur.fetchall()
        ]
        cur.execute("""
            SELECT (STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES) / 1073741824.0
            FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
            ORDER BY USAGE_DATE DESC LIMIT 1
        """)
        row = cur.fetchone()
        storage_gb = round(float(row[0] or 0), 1) if row else 0.0

    raw_costs = [d["cost"] for d in cost_trend]
    anomalies = []
    for i in range(len(cost_trend)):
        window = raw_costs[max(0, i - 14):i] if i > 0 else raw_costs[:1]
        rolling_avg = sum(window) / len(window) if window else raw_costs[i]
        ratio = raw_costs[i] / rolling_avg if rolling_avg > 0 else 1.0
        cost_trend[i]["rolling_avg"] = round(rolling_avg, 2)
        if ratio >= 1.8 and i > 3:
            anomalies.append({
                "date": cost_trend[i]["date"],
                "cost": cost_trend[i]["cost"],
                "avg": round(rolling_avg, 2),
                "ratio": round(ratio, 2),
                "label": f"Cost spike: {cost_trend[i]['cost']:.0f} vs avg {rolling_avg:.0f}",
            })

    return {
        "total_cost": round(sum(d["cost"] for d in cost_trend), 2),
        "total_credits": round(sum(d["credits"] for d in cost_trend), 2),
        "active_warehouses": len(top_warehouses),
        "expensive_queries": expensive_queries,
        "query_count": total_queries,
        "failed_queries": failed_queries,
        "storage_gb": storage_gb,
        "cost_trend": cost_trend,
        "top_warehouses": top_warehouses,
        "top_users": top_users,
        "credit_price": credit_price,
        "days": days,
        "anomalies": anomalies,
    }


def sync_costs(conn_doc: dict, days: int, credit_price: float) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        cur.execute(f"""
            SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
                   WAREHOUSE_NAME,
                   SUM(CREDITS_USED_COMPUTE * {credit_price}) AS cost,
                   SUM(CREDITS_USED_COMPUTE) AS credits
            FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1, 2 ORDER BY 1
        """)
        daily = [
            {"date": str(r[0]), "warehouse": r[1], "cost": round(float(r[2] or 0), 2), "credits": round(float(r[3] or 0), 2)}
            for r in cur.fetchall()
        ]
        cur.execute(f"""
            SELECT USER_NAME,
                   SUM(CREDITS_USED_CLOUD_SERVICES * {credit_price}) AS cost,
                   COUNT(*) AS queries
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """)
        by_user = [{"user": r[0], "cost": round(float(r[1] or 0), 2), "queries": r[2]} for r in cur.fetchall()]
    return {"daily": daily, "by_user": by_user, "days": days}


def sync_queries(conn_doc: dict, days: int, page: int, limit: int) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        offset = (page - 1) * limit
        cur.execute(f"""
            SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            AND EXECUTION_STATUS = 'SUCCESS'
        """)
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT QUERY_ID, START_TIME, USER_NAME, WAREHOUSE_NAME,
                   TOTAL_ELAPSED_TIME, BYTES_SCANNED, ROWS_PRODUCED,
                   QUERY_TEXT, CREDITS_USED_CLOUD_SERVICES,
                   COMPILATION_TIME, EXECUTION_TIME,
                   QUEUED_PROVISIONING_TIME, QUEUED_OVERLOAD_TIME, QUEUED_REPAIR_TIME,
                   TRANSACTION_BLOCKED_TIME,
                   BYTES_SPILLED_TO_LOCAL_STORAGE, BYTES_SPILLED_TO_REMOTE_STORAGE,
                   PARTITIONS_SCANNED, PARTITIONS_TOTAL,
                   PERCENTAGE_SCANNED_FROM_CACHE,
                   QUERY_TYPE, ROLE_NAME
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
            AND EXECUTION_STATUS = 'SUCCESS'
            AND IS_CLIENT_GENERATED_STATEMENT = FALSE
            ORDER BY TOTAL_ELAPSED_TIME DESC
            LIMIT {limit} OFFSET {offset}
        """)
        data = [
            {
                "query_id": r[0],
                "start_time": str(r[1]),
                "user": r[2],
                "warehouse": r[3],
                "duration_ms": int(r[4] or 0),
                "bytes_scanned": int(r[5] or 0),
                "rows_produced": int(r[6] or 0),
                "query_text": (r[7] or "")[:200],
                "credits": round(float(r[8] or 0), 6),
                "compilation_ms": int(r[9] or 0),
                "execution_ms": int(r[10] or 0),
                "queue_provision_ms": int(r[11] or 0),
                "queue_overload_ms": int(r[12] or 0),
                "queue_repair_ms": int(r[13] or 0),
                "blocked_ms": int(r[14] or 0),
                "spill_local_gb": round(float(r[15] or 0) / 1073741824, 2),
                "spill_remote_gb": round(float(r[16] or 0) / 1073741824, 2),
                "partitions_scanned": int(r[17] or 0),
                "partitions_total": int(r[18] or 0),
                "cache_hit_pct": round(float(r[19] or 0), 1),
                "query_type": r[20] or "SELECT",
                "role": r[21] or "",
            }
            for r in cur.fetchall()
        ]
    return {
        "data": data,
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / limit)),
        "limit": limit,
        "days": days,
    }


def sync_storage(conn_doc: dict, days: int) -> dict:
    with sf_connection(conn_doc) as sf:
        cur = sf.cursor()
        cur.execute("""
            SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
               ACTIVE_BYTES / 1073741824.0             AS active_gb,
               TIME_TRAVEL_BYTES / 1073741824.0        AS time_travel_gb,
               FAILSAFE_BYTES / 1073741824.0           AS failsafe_gb,
               RETAINED_FOR_CLONE_BYTES / 1073741824.0 AS clone_gb,
               TABLE_CREATED
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
        WHERE DELETED = FALSE
        ORDER BY (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) DESC NULLS LAST
        LIMIT 100
    """)
    tables = []
    now = datetime.now()
    for r in cur.fetchall():
        active_gb = round(float(r[3] or 0), 2)
        tt_gb = round(float(r[4] or 0), 2)
        fs_gb = round(float(r[5] or 0), 2)
        clone_gb = round(float(r[6] or 0), 2)
        last_modified_raw = r[7]
        try:
            if hasattr(last_modified_raw, 'date'):
                last_modified = str(last_modified_raw.date())
            else:
                last_modified = str(last_modified_raw)[:10] if last_modified_raw else "unknown"
            age_days = (now - datetime.strptime(last_modified[:10], "%Y-%m-%d")).days
            stale = age_days > 90 and active_gb < 0.1
        except Exception:
            last_modified = str(last_modified_raw)[:10] if last_modified_raw else "unknown"
            stale = False
        tables.append({
            "database": r[0], "schema": r[1], "table": r[2],
            "size_gb": round(active_gb + tt_gb + fs_gb, 2),
            "active_gb": active_gb,
            "time_travel_gb": tt_gb,
            "failsafe_gb": fs_gb,
            "clone_gb": clone_gb,
            "last_altered": last_modified,
            "stale": stale,
        })
    cur.execute(f"""
        SELECT USAGE_DATE,
               STORAGE_BYTES  / 1073741824.0 AS table_gb,
               STAGE_BYTES    / 1073741824.0 AS stage_gb,
               FAILSAFE_BYTES / 1073741824.0 AS failsafe_gb,
               (STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES) / 1073741824.0 AS total_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
        WHERE USAGE_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        ORDER BY USAGE_DATE
    """)
    trend = [
        {
            "date": str(r[0]),
            "table_gb": round(float(r[1] or 0), 1),
            "stage_gb": round(float(r[2] or 0), 1),
            "failsafe_gb": round(float(r[3] or 0), 1),
            "total_gb": round(float(r[4] or 0), 1),
        }
        for r in cur.fetchall()
    ]
    cur.execute(f"""
        SELECT DATABASE_NAME,
               ROUND(AVG(AVERAGE_DATABASE_BYTES)              / 1073741824.0, 2) AS avg_db_gb,
               ROUND(AVG(AVERAGE_FAILSAFE_BYTES)              / 1073741824.0, 2) AS avg_failsafe_gb,
               ROUND(AVG(AVERAGE_HYBRID_TABLE_STORAGE_BYTES)  / 1073741824.0, 2) AS avg_hybrid_gb,
               ROUND(MAX(AVERAGE_DATABASE_BYTES)              / 1073741824.0, 2) AS max_db_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
        WHERE USAGE_DATE >= DATEADD('day', -{days}, CURRENT_DATE())
        GROUP BY 1
        ORDER BY 4 DESC
        LIMIT 20
    """)
    by_database = [
        {
            "database": r[0],
            "avg_db_gb": float(r[1] or 0),
            "avg_failsafe_gb": float(r[2] or 0),
            "avg_hybrid_gb": float(r[3] or 0),
            "max_db_gb": float(r[4] or 0),
            "total_gb": round(float(r[1] or 0) + float(r[2] or 0) + float(r[3] or 0), 2),
        }
        for r in cur.fetchall()
    ]
    sf.close()
    total_gb = round(sum(t["size_gb"] for t in tables), 2)
    return {
        "tables": tables,
        "total_gb": total_gb,
        "storage_cost_monthly": round(total_gb * 0.023, 2),
        "trend": trend,
        "by_database": by_database,
        "days": days,
    }


def sync_warehouses(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    cur.execute("SHOW WAREHOUSES")
    cols = [d[0].lower() for d in cur.description]
    warehouses = []
    for row in cur.fetchall():
        rd = dict(zip(cols, row))
        size = rd.get("size", "")
        warehouses.append({
            "name": rd.get("name", ""),
            "size": size,
            "state": rd.get("state", ""),
            "auto_suspend": int(rd.get("auto_suspend", 0) or 0),
            "min_cluster": int(rd.get("min_cluster_count", 1) or 1),
            "max_cluster": int(rd.get("max_cluster_count", 1) or 1),
            "credits_per_hour": CREDITS_MAP.get(size, CREDITS_MAP.get(size.title(), 1)),
        })
    cur.execute(f"""
        SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
               WAREHOUSE_NAME,
               SUM(CREDITS_USED_COMPUTE) AS credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1, 2 ORDER BY 1
    """)
    activity = [
        {"date": str(r[0]), "warehouse": r[1], "credits": round(float(r[2] or 0), 2)}
        for r in cur.fetchall()
    ]
    cur.execute(f"""
        SELECT DATE_TRUNC('day', START_TIME)::DATE AS day,
               WAREHOUSE_NAME,
               ROUND(AVG(AVG_RUNNING), 2)            AS avg_running,
               ROUND(AVG(AVG_QUEUED_LOAD), 3)        AS avg_queued,
               ROUND(AVG(AVG_QUEUED_PROVISIONING), 3) AS avg_provisioning
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1, 2 ORDER BY 1
    """)
    load_history = [
        {"date": str(r[0]), "warehouse": r[1], "avg_running": float(r[2] or 0),
         "avg_queued": float(r[3] or 0), "avg_provisioning": float(r[4] or 0)}
        for r in cur.fetchall()
    ]
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               COUNT(*)                                                            AS query_count,
               COUNT_IF(EXECUTION_STATUS != 'SUCCESS')                            AS failed_count,
               ROUND(AVG(PERCENTAGE_SCANNED_FROM_CACHE), 1)                       AS avg_cache_hit_pct,
               ROUND(AVG(BYTES_SPILLED_TO_LOCAL_STORAGE)  / 1073741824.0, 4)      AS avg_spill_local_gb,
               ROUND(AVG(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 4)      AS avg_spill_remote_gb,
               ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 1)                         AS avg_duration_s
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    wh_stats = [
        {
            "name": r[0],
            "query_count": int(r[1] or 0),
            "failed_count": int(r[2] or 0),
            "avg_cache_hit_pct": round(float(r[3] or 0), 1),
            "avg_spill_local_gb": round(float(r[4] or 0), 4),
            "avg_spill_remote_gb": round(float(r[5] or 0), 4),
            "avg_duration_s": round(float(r[6] or 0), 1),
        }
        for r in cur.fetchall()
    ]
    sf.close()
    return {"warehouses": warehouses, "activity": activity, "load_history": load_history, "wh_stats": wh_stats, "days": days}


def sync_workloads(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    cur.execute(f"""
        SELECT
            COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT)) AS workload_id,
            ANY_VALUE(QUERY_TEXT) AS sample_query,
            COUNT(*) AS execution_count,
            ROUND(SUM(TOTAL_ELAPSED_TIME) / 1000.0, 1) AS total_seconds,
            ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 1) AS avg_seconds,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) / 1000.0, 1) AS p95_seconds,
            SUM(CREDITS_USED_CLOUD_SERVICES) AS total_credits,
            SUM(BYTES_SCANNED) / 1073741824.0 AS total_gb_scanned,
            MIN(START_TIME) AS first_seen,
            MAX(START_TIME) AS last_seen,
            ANY_VALUE(USER_NAME) AS sample_user,
            ANY_VALUE(WAREHOUSE_NAME) AS sample_warehouse
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        HAVING COUNT(*) >= 2
        ORDER BY SUM(TOTAL_ELAPSED_TIME) DESC
        LIMIT 100
    """)
    workloads = []
    for r in cur.fetchall():
        workloads.append({
            "workload_id": str(r[0] or "")[:16],
            "sample_query": (str(r[1] or ""))[:200],
            "execution_count": int(r[2] or 0),
            "total_seconds": round(float(r[3] or 0), 1),
            "avg_seconds": round(float(r[4] or 0), 1),
            "p95_seconds": round(float(r[5] or 0), 1),
            "total_credits": round(float(r[6] or 0), 6),
            "total_gb_scanned": round(float(r[7] or 0), 2),
            "first_seen": str(r[8]),
            "last_seen": str(r[9]),
            "sample_user": str(r[10] or ""),
            "sample_warehouse": str(r[11] or ""),
        })
    sf.close()
    return {
        "workloads": workloads,
        "total_workloads": len(workloads),
        "total_executions": sum(w["execution_count"] for w in workloads),
        "days": days,
    }


def sync_recommendations(conn_doc: dict, credit_price: float) -> list:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    recs = []
    size_credits_per_hour = {
        "X-SMALL": 1, "XSMALL": 1, "SMALL": 2, "MEDIUM": 4,
        "LARGE": 8, "X-LARGE": 16, "XLARGE": 16,
        "2X-LARGE": 32, "3X-LARGE": 64, "4X-LARGE": 128,
    }

    # 1. Auto-suspend waste
    cur.execute("SHOW WAREHOUSES")
    cols = [d[0].lower() for d in cur.description]
    for row in cur.fetchall():
        rd = dict(zip(cols, row))
        name = rd.get("name", "")
        size = rd.get("size", "SMALL").upper().replace("-", "")
        suspend = int(rd.get("auto_suspend", 0) or 0)
        if suspend > 300:
            cph = size_credits_per_hour.get(size, 2)
            wasted_hours_per_month = (suspend - 120) / 3600 * 30 * 8
            savings = round(wasted_hours_per_month * cph * credit_price)
            recs.append({
                "id": f"rec_suspend_{name}",
                "title": f"Reduce {name} auto-suspend from {suspend}s to 120s",
                "description": (
                    f"{name} idles for {suspend} seconds after each query before suspending. "
                    f"At {size} size ({cph} credits/hr), each unnecessary idle minute costs ~${round(cph * credit_price / 60, 2)}. "
                    f"Setting AUTO_SUSPEND = 120 could save ~${savings}/month with no impact on query performance."
                ),
                "category": "warehouse",
                "potential_savings": savings,
                "effort": "low",
                "priority": "high" if suspend >= 600 else "medium",
                "ddl_command": f"ALTER WAREHOUSE {name} SET AUTO_SUSPEND = 120;",
            })

    # 2. Repeated queries
    cur.execute("""
        SELECT
            ANY_VALUE(WAREHOUSE_NAME) AS warehouse,
            COUNT(*) AS run_count,
            SUM(TOTAL_ELAPSED_TIME) / 1000.0 AS total_seconds,
            ANY_VALUE(QUERY_TEXT) AS sample_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
          AND QUERY_TYPE = 'SELECT'
        GROUP BY COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT))
        HAVING COUNT(*) >= 10
        ORDER BY COUNT(*) DESC
        LIMIT 5
    """)
    repeated = cur.fetchall()
    if repeated:
        total_runs = sum(int(r[1]) for r in repeated)
        top = repeated[0]
        recs.append({
            "id": "rec_repeated_queries",
            "title": f"{total_runs} repeated SELECT queries detected - enable result caching",
            "description": (
                f"Top repeated query ran {int(top[1])}x in the last 7 days on {top[2]} "
                f"({round(float(top[2] or 0), 0):.0f}s total compute). "
                f"Sample: \"{(str(top[3]) or '')[:120]}...\". "
                f"Run ALTER WAREHOUSE {top[0]} SET USE_CACHED_RESULT = TRUE to serve identical queries from cache at zero compute cost."
            ),
            "category": "query",
            "potential_savings": None,
            "effort": "low",
            "priority": "high" if total_runs >= 50 else "medium",
        })

    # 3. Full table scans
    cur.execute("""
        SELECT
            WAREHOUSE_NAME,
            COUNT(*) AS cnt,
            ROUND(AVG(BYTES_SCANNED) / 1073741824.0, 1) AS avg_gb,
            ANY_VALUE(QUERY_TEXT) AS sample_query
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND PARTITIONS_SCANNED > 0
          AND PARTITIONS_TOTAL > 0
          AND PARTITIONS_SCANNED::FLOAT / PARTITIONS_TOTAL > 0.8
          AND BYTES_SCANNED > 1073741824
          AND QUERY_TYPE = 'SELECT'
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 3
    """)
    full_scans = cur.fetchall()
    if full_scans:
        top = full_scans[0]
        total_scans = sum(int(r[1]) for r in full_scans)
        recs.append({
            "id": "rec_full_scans",
            "title": f"{total_scans} queries scanning >80% of partitions - add clustering keys",
            "description": (
                f"{int(top[1])} queries on {top[0]} are scanning >80% of table partitions "
                f"with avg {float(top[2] or 0):.1f} GB per query. "
                f"Adding clustering keys on frequently-filtered date or ID columns can reduce partition scans by 50-90%, "
                f"cutting both query time and compute cost."
            ),
            "category": "query",
            "potential_savings": None,
            "effort": "medium",
            "priority": "high" if total_scans > 30 else "medium",
        })

    # 4. Stale tables
    cur.execute("""
        SELECT
            TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
            ROUND((ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) / 1073741824.0, 2) AS size_gb,
            TABLE_CREATED
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
        WHERE DELETED = FALSE
          AND TABLE_CREATED < DATEADD('day', -90, CURRENT_DATE())
          AND (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) > 104857600
        ORDER BY (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) DESC
        LIMIT 20
    """)
    stale = cur.fetchall()
    if stale:
        total_gb = round(sum(float(r[3] or 0) for r in stale), 1)
        savings = round(total_gb * 23)
        names = ", ".join(f"{r[1]}.{r[2]}" for r in stale[:3])
        recs.append({
            "id": "rec_stale_tables",
            "title": f"Review {len(stale)} tables untouched for 90+ days ({total_gb} GB)",
            "description": (
                f"Found {len(stale)} tables created 90+ days ago with no schema changes, "
                f"occupying {total_gb} GB total. Examples: {names}{'...' if len(stale) > 3 else ''}. "
                f"Dropping or archiving unused tables could save ~${savings}/month in storage costs."
            ),
            "category": "storage",
            "potential_savings": savings if savings > 0 else None,
            "effort": "low",
            "priority": "medium" if total_gb > 50 else "low",
        })

    # 5. Slow queries
    cur.execute("""
        SELECT COUNT(*) AS cnt, ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 0) AS avg_sec
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND TOTAL_ELAPSED_TIME > 300000
    """)
    row = cur.fetchone()
    slow_count = int(row[0] or 0) if row else 0
    avg_slow_sec = float(row[1] or 0) if row else 0
    if slow_count >= 5:
        recs.append({
            "id": "rec_slow_queries",
            "title": f"{slow_count} queries taking >5 minutes (avg {avg_slow_sec:.0f}s)",
            "description": (
                f"{slow_count} queries in the last 7 days ran longer than 5 minutes with an average of "
                f"{avg_slow_sec:.0f} seconds. Review the Query Performance page to identify patterns - "
                f"common causes include missing filters, Cartesian joins, or large result sets without LIMIT."
            ),
            "category": "query",
            "potential_savings": None,
            "effort": "medium",
            "priority": "medium" if slow_count >= 20 else "low",
        })

    sf.close()

    if not recs:
        recs.append({
            "id": "rec_all_good",
            "title": "No critical optimizations found",
            "description": "Your Snowflake usage looks efficient based on the last 7 days of data. Check back as more query history accumulates.",
            "category": "info",
            "potential_savings": None,
            "effort": "none",
            "priority": "low",
        })

    return recs


def sync_fetch_metric(conn_doc: dict, metric: str) -> float:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    try:
        if metric == "daily_cost":
            cur.execute("""
                SELECT SUM(CREDITS_USED_COMPUTE)
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME >= CURRENT_DATE()
            """)
            row = cur.fetchone()
            credits = float(row[0] or 0) if row else 0.0
            return round(credits * 3.0, 2)
        elif metric == "hourly_credits":
            cur.execute("""
                SELECT SUM(CREDITS_USED_COMPUTE)
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                WHERE START_TIME >= DATEADD('hour', -1, CURRENT_TIMESTAMP())
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        elif metric == "expensive_query_count":
            cur.execute("""
                SELECT COUNT(*)
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD('hour', -1, CURRENT_TIMESTAMP())
                  AND TOTAL_ELAPSED_TIME > 300000
                  AND EXECUTION_STATUS = 'SUCCESS'
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        elif metric == "failed_query_count":
            cur.execute("""
                SELECT COUNT(*)
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD('hour', -1, CURRENT_TIMESTAMP())
                  AND EXECUTION_STATUS = 'FAIL'
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        elif metric == "storage_gb":
            cur.execute("""
                SELECT (STORAGE_BYTES + STAGE_BYTES + FAILSAFE_BYTES) / 1073741824.0
                FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE
                ORDER BY USAGE_DATE DESC LIMIT 1
            """)
            row = cur.fetchone()
            return float(row[0] or 0) if row else 0.0
        return 0.0
    finally:
        sf.close()


def sync_workload_runs(conn_doc: dict, workload_id: str, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    cur.execute(f"""
        SELECT
            QUERY_ID, START_TIME, TOTAL_ELAPSED_TIME,
            USER_NAME, WAREHOUSE_NAME,
            BYTES_SCANNED, ROWS_PRODUCED,
            PERCENTAGE_SCANNED_FROM_CACHE
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT)) = '{workload_id}'
        ORDER BY START_TIME DESC
        LIMIT 100
    """)
    rows = []
    for r in cur.fetchall():
        rows.append({
            "query_id": str(r[0]),
            "start_time": str(r[1]),
            "duration_ms": int(r[2] or 0),
            "user": str(r[3] or ""),
            "warehouse": str(r[4] or ""),
            "bytes_scanned": int(r[5] or 0),
            "rows_produced": int(r[6] or 0),
            "cache_hit_pct": round(float(r[7] or 0), 1),
        })
    sf.close()
    return {"runs": rows, "workload_id": workload_id}


def sync_debug_permissions(conn_doc: dict) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    results = {}
    checks = [
        ("QUERY_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE START_TIME >= DATEADD('hour',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("WAREHOUSE_METERING_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY WHERE START_TIME >= DATEADD('day',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("WAREHOUSE_LOAD_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY WHERE START_TIME >= DATEADD('day',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("TABLE_STORAGE_METRICS", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS WHERE DELETED=FALSE LIMIT 1"),
        ("STORAGE_USAGE", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.STORAGE_USAGE WHERE USAGE_DATE >= DATEADD('day',-7,CURRENT_DATE()) LIMIT 1"),
        ("DATABASE_STORAGE_USAGE_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY WHERE USAGE_DATE >= DATEADD('day',-7,CURRENT_DATE()) LIMIT 1"),
        ("METERING_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY WHERE START_TIME >= DATEADD('day',-1,CURRENT_TIMESTAMP()) LIMIT 1"),
        ("METERING_DAILY_HISTORY", "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY WHERE SERVICE_TYPE='WAREHOUSE_METERING' LIMIT 1"),
        ("SHOW WAREHOUSES", "SHOW WAREHOUSES"),
    ]
    for name, sql in checks:
        try:
            cur.execute(sql)
            row = cur.fetchone()
            count = int(row[0]) if row and isinstance(row[0], (int, float)) else "ok"
            results[name] = {"status": "ok", "rows": count}
        except Exception as e:
            results[name] = {"status": "error", "error": str(e)[:200]}
    sf.close()
    return results


def sync_warehouse_sizing(conn_doc: dict, days: int, credit_price: float) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    # Get current warehouse configs
    cur.execute("SHOW WAREHOUSES")
    cols = [d[0].lower() for d in cur.description]
    wh_configs = {}
    for row in cur.fetchall():
        rd = dict(zip(cols, row))
        wh_configs[rd.get("name", "")] = rd.get("size", "SMALL").upper()

    # Get utilization per warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               AVG(AVG_RUNNING) AS avg_utilization
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    """)
    utilization = {r[0]: round(float(r[1] or 0), 3) for r in cur.fetchall()}

    # Get spillage per warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               ROUND(SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) / 1073741824.0, 2) AS spill_local_gb,
               ROUND(SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 2) AS spill_remote_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
        GROUP BY 1
    """)
    spillage = {r[0]: {"local": float(r[1] or 0), "remote": float(r[2] or 0)} for r in cur.fetchall()}

    # Get credits per warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               SUM(CREDITS_USED_COMPUTE) AS total_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    """)
    credits = {r[0]: float(r[1] or 0) for r in cur.fetchall()}
    sf.close()

    size_order = ["XSMALL", "SMALL", "MEDIUM", "LARGE", "XLARGE", "2XLARGE", "3XLARGE", "4XLARGE"]
    size_credits = {"XSMALL": 1, "SMALL": 2, "MEDIUM": 4, "LARGE": 8, "XLARGE": 16, "2XLARGE": 32, "3XLARGE": 64, "4XLARGE": 128}

    def normalize_size(s):
        return s.replace("X-", "X").replace("-", "").upper()

    recommendations = []
    total_savings = 0.0

    for wh_name, current_size_raw in wh_configs.items():
        current_size = normalize_size(current_size_raw)
        util = utilization.get(wh_name, 0.5)
        spill = spillage.get(wh_name, {"local": 0, "remote": 0})
        wh_credits = credits.get(wh_name, 0)

        current_idx = size_order.index(current_size) if current_size in size_order else -1
        if current_idx < 0:
            continue

        recommended_size = current_size
        reason = "Current sizing appears appropriate"
        needs_change = False

        if util < 0.2 and spill["remote"] == 0 and current_idx > 0:
            recommended_size = size_order[current_idx - 1]
            reason = f"Average utilization is {util:.0%} with no remote spillage — warehouse is over-provisioned"
            needs_change = True
        elif spill["remote"] > 1.0 and current_idx < len(size_order) - 1:
            recommended_size = size_order[current_idx + 1]
            reason = f"Remote spillage of {spill['remote']:.1f} GB detected — warehouse is undersized for workload"
            needs_change = True

        current_cph = size_credits.get(current_size, 1)
        recommended_cph = size_credits.get(recommended_size, 1)
        monthly_credits = wh_credits * (30 / max(days, 1))
        ratio = recommended_cph / current_cph if current_cph > 0 else 1
        monthly_savings = round((1 - ratio) * monthly_credits * credit_price, 2) if needs_change else 0.0
        total_savings += max(monthly_savings, 0)

        display_size_map = {"XSMALL": "X-Small", "SMALL": "Small", "MEDIUM": "Medium", "LARGE": "Large", "XLARGE": "X-Large", "2XLARGE": "2X-Large", "3XLARGE": "3X-Large", "4XLARGE": "4X-Large"}

        recommendations.append({
            "warehouse": wh_name,
            "current_size": display_size_map.get(current_size, current_size_raw),
            "recommended_size": display_size_map.get(recommended_size, recommended_size),
            "avg_utilization": util,
            "spill_local_gb": spill["local"],
            "spill_remote_gb": spill["remote"],
            "monthly_savings": max(monthly_savings, 0),
            "ddl_command": f"ALTER WAREHOUSE {wh_name} SET WAREHOUSE_SIZE = '{display_size_map.get(recommended_size, recommended_size)}';" if needs_change else None,
            "reason": reason,
            "needs_change": needs_change,
        })

    return {"recommendations": recommendations, "total_monthly_savings": round(total_savings, 2), "days": days}


def sync_autosuspend_analysis(conn_doc: dict, days: int, credit_price: float) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    # Get current configs
    cur.execute("SHOW WAREHOUSES")
    cols = [d[0].lower() for d in cur.description]
    wh_configs = {}
    for row in cur.fetchall():
        rd = dict(zip(cols, row))
        name = rd.get("name", "")
        size = rd.get("size", "SMALL").upper().replace("X-", "X").replace("-", "")
        wh_configs[name] = {
            "suspend": int(rd.get("auto_suspend", 0) or 0),
            "size": size,
        }

    # Get suspend/resume event pairs to calculate inter-query gaps
    cur.execute(f"""
        SELECT WAREHOUSE_NAME, resume_count, avg_gap_s
        FROM (
            SELECT WAREHOUSE_NAME,
                   COUNT(*) AS resume_count,
                   AVG(gap_s) AS avg_gap_s
            FROM (
                SELECT WAREHOUSE_NAME, EVENT_NAME,
                       DATEDIFF('second', TIMESTAMP,
                           LEAD(TIMESTAMP) OVER (PARTITION BY WAREHOUSE_NAME ORDER BY TIMESTAMP)) AS gap_s
                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
                WHERE TIMESTAMP >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
                  AND EVENT_NAME IN ('RESUME_WAREHOUSE', 'SUSPEND_WAREHOUSE')
            ) sub
            WHERE EVENT_NAME = 'RESUME_WAREHOUSE'
            GROUP BY 1
        )
    """)
    event_stats = {}
    for r in cur.fetchall():
        event_stats[r[0]] = {
            "resume_count": int(r[1] or 0),
            "avg_gap_s": float(r[2] or 120),
        }

    # Get P50/P75 of gap times using query history inter-arrival times
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY gap_s) AS p50_gap,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY gap_s) AS p75_gap
        FROM (
            SELECT WAREHOUSE_NAME,
                   DATEDIFF('second', LAG(END_TIME) OVER (PARTITION BY WAREHOUSE_NAME ORDER BY END_TIME), START_TIME) AS gap_s
            FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
            WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
              AND WAREHOUSE_NAME IS NOT NULL
              AND EXECUTION_STATUS = 'SUCCESS'
        ) gaps
        WHERE gap_s > 0 AND gap_s < 3600
        GROUP BY 1
    """)
    gap_stats = {}
    for r in cur.fetchall():
        gap_stats[r[0]] = {
            "p50": round(float(r[1] or 60), 0),
            "p75": round(float(r[2] or 120), 0),
        }
    sf.close()

    size_credits = {"XSMALL": 1, "SMALL": 2, "MEDIUM": 4, "LARGE": 8, "XLARGE": 16, "2XLARGE": 32, "3XLARGE": 64, "4XLARGE": 128}
    recommendations = []
    total_savings = 0.0

    for wh_name, config in wh_configs.items():
        current_suspend = config["suspend"]
        size = config["size"]
        cph = size_credits.get(size, 2)

        gaps = gap_stats.get(wh_name, {"p50": 60, "p75": 120})
        events = event_stats.get(wh_name, {"resume_count": 0, "avg_gap_s": 120})

        recommended_suspend = max(60, min(int(gaps["p75"]), 300))

        # Calculate idle waste
        if current_suspend > recommended_suspend and events["resume_count"] > 0:
            excess_seconds = (current_suspend - recommended_suspend)
            idle_waste_credits = round(excess_seconds / 3600 * cph * events["resume_count"] * (30 / max(days, 1)), 2)
            monthly_savings = round(idle_waste_credits * credit_price, 2)
        else:
            idle_waste_credits = 0.0
            monthly_savings = 0.0

        needs_change = current_suspend > recommended_suspend + 30
        total_savings += monthly_savings

        recommendations.append({
            "warehouse": wh_name,
            "current_suspend_s": current_suspend,
            "recommended_suspend_s": recommended_suspend,
            "resume_count": events["resume_count"],
            "idle_waste_credits": idle_waste_credits,
            "monthly_savings": monthly_savings,
            "ddl_command": f"ALTER WAREHOUSE {wh_name} SET AUTO_SUSPEND = {recommended_suspend};" if needs_change else None,
            "gap_p50_s": gaps["p50"],
            "gap_p75_s": gaps["p75"],
            "needs_change": needs_change,
        })

    return {"recommendations": recommendations, "total_monthly_savings": round(total_savings, 2), "days": days}


def sync_spillage(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               COUNT(*) AS query_count,
               ROUND(SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) / 1073741824.0, 2) AS spill_local_gb,
               ROUND(SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 2) AS spill_remote_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND (BYTES_SPILLED_TO_LOCAL_STORAGE > 0 OR BYTES_SPILLED_TO_REMOTE_STORAGE > 0)
          AND WAREHOUSE_NAME IS NOT NULL
        GROUP BY 1
        ORDER BY 3 DESC
    """)
    by_warehouse = [
        {"warehouse": r[0], "query_count": int(r[1] or 0), "spill_local_gb": float(r[2] or 0), "spill_remote_gb": float(r[3] or 0)}
        for r in cur.fetchall()
    ]

    cur.execute(f"""
        SELECT USER_NAME,
               COUNT(*) AS query_count,
               ROUND(SUM(BYTES_SPILLED_TO_LOCAL_STORAGE) / 1073741824.0, 2) AS spill_local_gb,
               ROUND(SUM(BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 2) AS spill_remote_gb
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND (BYTES_SPILLED_TO_LOCAL_STORAGE > 0 OR BYTES_SPILLED_TO_REMOTE_STORAGE > 0)
        GROUP BY 1
        ORDER BY 3 DESC
    """)
    by_user = [
        {"user": r[0], "query_count": int(r[1] or 0), "spill_local_gb": float(r[2] or 0), "spill_remote_gb": float(r[3] or 0)}
        for r in cur.fetchall()
    ]

    cur.execute(f"""
        SELECT QUERY_ID, WAREHOUSE_NAME, USER_NAME, WAREHOUSE_SIZE,
               ROUND(BYTES_SPILLED_TO_LOCAL_STORAGE / 1073741824.0, 2) AS spill_local_gb,
               ROUND(BYTES_SPILLED_TO_REMOTE_STORAGE / 1073741824.0, 2) AS spill_remote_gb,
               TOTAL_ELAPSED_TIME / 1000.0 AS duration_s,
               QUERY_TEXT
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND (BYTES_SPILLED_TO_LOCAL_STORAGE > 0 OR BYTES_SPILLED_TO_REMOTE_STORAGE > 0)
        ORDER BY (BYTES_SPILLED_TO_LOCAL_STORAGE + BYTES_SPILLED_TO_REMOTE_STORAGE) DESC
        LIMIT 20
    """)
    top_queries = [
        {
            "query_id": r[0], "warehouse": r[1], "user": r[2], "warehouse_size": r[3],
            "spill_local_gb": float(r[4] or 0), "spill_remote_gb": float(r[5] or 0),
            "duration_s": round(float(r[6] or 0), 1), "query_text": (r[7] or "")[:200],
        }
        for r in cur.fetchall()
    ]
    sf.close()

    total_spill = round(sum(w["spill_local_gb"] + w["spill_remote_gb"] for w in by_warehouse), 2)
    affected_queries = sum(w["query_count"] for w in by_warehouse)

    return {
        "by_warehouse": by_warehouse,
        "by_user": by_user,
        "top_queries": top_queries,
        "summary": {
            "total_spill_gb": total_spill,
            "affected_queries": affected_queries,
            "affected_warehouses": len(by_warehouse),
        },
        "days": days,
    }


def sync_query_patterns(conn_doc: dict, days: int, credit_price: float) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    cur.execute(f"""
        SELECT
            COALESCE(QUERY_PARAMETERIZED_HASH, MD5(QUERY_TEXT)) AS pattern_hash,
            ANY_VALUE(QUERY_TEXT) AS example_query,
            COUNT(*) AS execution_count,
            SUM(CREDITS_USED_CLOUD_SERVICES) * {credit_price} AS total_cost_usd,
            ROUND(AVG(TOTAL_ELAPSED_TIME) / 1000.0, 1) AS avg_duration_s,
            ROUND(AVG(CASE WHEN PARTITIONS_TOTAL > 0 THEN PARTITIONS_SCANNED::FLOAT / PARTITIONS_TOTAL ELSE 0 END), 3) AS avg_scan_ratio,
            ROUND(AVG(BYTES_SPILLED_TO_LOCAL_STORAGE + BYTES_SPILLED_TO_REMOTE_STORAGE) / 1073741824.0, 3) AS avg_spill_gb,
            ROUND(AVG(PERCENTAGE_SCANNED_FROM_CACHE), 1) AS avg_cache_pct
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        HAVING COUNT(*) >= 2
        ORDER BY total_cost_usd DESC
        LIMIT 100
    """)

    patterns = []
    total_cost = 0.0
    for r in cur.fetchall():
        cost = round(float(r[3] or 0), 2)
        total_cost += cost
        scan_ratio = float(r[5] or 0)
        avg_spill = float(r[6] or 0)
        cache_pct = float(r[7] or 0)

        flags = []
        recommendation = ""
        if cache_pct > 60:
            flags.append("cacheable")
            recommendation = "High cache hit rate — consider result caching or materialized views"
        if scan_ratio > 0.8:
            flags.append("full_scan")
            recommendation = "Scanning >80% of partitions — add clustering keys on filter columns"
        if avg_spill > 0:
            flags.append("spilling")
            if not recommendation:
                recommendation = "Query is spilling to disk — consider a larger warehouse or optimize query"
        if not recommendation:
            recommendation = "No immediate optimization needed"

        patterns.append({
            "pattern_hash": str(r[0] or "")[:16],
            "example_query": (str(r[1] or ""))[:200],
            "execution_count": int(r[2] or 0),
            "total_cost_usd": cost,
            "avg_duration_s": float(r[4] or 0),
            "avg_scan_ratio": scan_ratio,
            "avg_spill_gb": avg_spill,
            "avg_cache_pct": cache_pct,
            "flags": flags,
            "recommendation": recommendation,
        })
    sf.close()

    return {
        "patterns": patterns,
        "total_patterns": len(patterns),
        "total_cost_usd": round(total_cost, 2),
        "days": days,
    }


def sync_cost_attribution(conn_doc: dict, days: int, credit_price: float) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    # Proportional cost allocation by user
    cur.execute(f"""
        SELECT USER_NAME,
               SUM(TOTAL_ELAPSED_TIME) AS total_elapsed,
               COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    user_elapsed = {r[0]: {"elapsed": float(r[1] or 0), "queries": int(r[2] or 0)} for r in cur.fetchall()}

    # Total credits by warehouse
    cur.execute(f"""
        SELECT WAREHOUSE_NAME,
               SUM(CREDITS_USED_COMPUTE) AS total_credits
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY 1
    """)
    wh_credits = {r[0]: float(r[1] or 0) for r in cur.fetchall()}
    total_cost = sum(c * credit_price for c in wh_credits.values())
    total_elapsed_all = sum(v["elapsed"] for v in user_elapsed.values())

    by_user = []
    for user, data in sorted(user_elapsed.items(), key=lambda x: x[1]["elapsed"], reverse=True)[:20]:
        proportion = data["elapsed"] / total_elapsed_all if total_elapsed_all > 0 else 0
        cost = round(proportion * total_cost, 2)
        by_user.append({"user": user, "cost_usd": cost, "query_count": data["queries"], "pct": round(proportion * 100, 1)})

    # By role
    cur.execute(f"""
        SELECT ROLE_NAME,
               SUM(TOTAL_ELAPSED_TIME) AS total_elapsed,
               COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC LIMIT 20
    """)
    by_role = []
    for r in cur.fetchall():
        elapsed = float(r[1] or 0)
        proportion = elapsed / total_elapsed_all if total_elapsed_all > 0 else 0
        cost = round(proportion * total_cost, 2)
        by_role.append({"role": r[0], "cost_usd": cost, "query_count": int(r[2] or 0), "pct": round(proportion * 100, 1)})

    # By database
    cur.execute(f"""
        SELECT DATABASE_NAME,
               SUM(TOTAL_ELAPSED_TIME) AS total_elapsed,
               COUNT(*) AS query_count
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND DATABASE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        GROUP BY 1
        ORDER BY 2 DESC LIMIT 20
    """)
    by_database = []
    for r in cur.fetchall():
        elapsed = float(r[1] or 0)
        proportion = elapsed / total_elapsed_all if total_elapsed_all > 0 else 0
        cost = round(proportion * total_cost, 2)
        by_database.append({"database": r[0], "cost_usd": cost, "query_count": int(r[2] or 0), "pct": round(proportion * 100, 1)})

    # By warehouse (straightforward)
    by_warehouse = [
        {"warehouse": wh, "cost_usd": round(creds * credit_price, 2), "credits": round(creds, 2)}
        for wh, creds in sorted(wh_credits.items(), key=lambda x: x[1], reverse=True)
    ]

    # Top queries by estimated cost
    cur.execute(f"""
        SELECT QUERY_ID, USER_NAME, WAREHOUSE_NAME, ROLE_NAME,
               TOTAL_ELAPSED_TIME / 1000.0 AS duration_s,
               QUERY_TEXT,
               CREDITS_USED_CLOUD_SERVICES * {credit_price} AS est_cost
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
          AND WAREHOUSE_NAME IS NOT NULL
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        ORDER BY TOTAL_ELAPSED_TIME DESC
        LIMIT 20
    """)
    top_queries = [
        {
            "query_id": r[0], "user": r[1], "warehouse": r[2], "role": r[3],
            "duration_s": round(float(r[4] or 0), 1),
            "query_text": (r[5] or "")[:200],
            "est_cost_usd": round(float(r[6] or 0), 4),
        }
        for r in cur.fetchall()
    ]
    sf.close()

    return {
        "by_user": by_user,
        "by_role": by_role,
        "by_database": by_database,
        "by_warehouse": by_warehouse,
        "top_queries": top_queries,
        "total_cost_usd": round(total_cost, 2),
        "days": days,
    }


def sync_stale_tables(conn_doc: dict, days: int) -> dict:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()

    # Get large tables
    cur.execute("""
        SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
               (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) / 1073741824.0 AS size_gb,
               TABLE_CREATED
        FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
        WHERE DELETED = FALSE
          AND (ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) > 1048576
        ORDER BY size_gb DESC
        LIMIT 200
    """)
    tables_raw = cur.fetchall()

    # Try ACCESS_HISTORY for last-queried (Enterprise-only)
    last_queried = {}
    try:
        cur.execute(f"""
            SELECT
                bos.value:"objectName"::STRING AS full_name,
                MAX(QUERY_START_TIME) AS last_queried
            FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY,
                 LATERAL FLATTEN(BASE_OBJECTS_ACCESSED) bos
            WHERE QUERY_START_TIME >= DATEADD('day', -{max(days, 180)}, CURRENT_TIMESTAMP())
            GROUP BY 1
        """)
        for r in cur.fetchall():
            last_queried[str(r[0]).upper()] = str(r[1])
    except Exception:
        pass
    sf.close()

    now = datetime.now()
    stale_tables = []
    for r in tables_raw:
        db, schema, table = r[0], r[1], r[2]
        size_gb = round(float(r[3] or 0), 2)
        created = r[4]

        full_name = f"{db}.{schema}.{table}".upper()
        lq = last_queried.get(full_name)

        if lq:
            try:
                lq_date = datetime.strptime(str(lq)[:10], "%Y-%m-%d")
                days_since = (now - lq_date).days
            except Exception:
                days_since = None
        else:
            try:
                if hasattr(created, 'date'):
                    created_date = datetime.strptime(str(created.date()), "%Y-%m-%d")
                else:
                    created_date = datetime.strptime(str(created)[:10], "%Y-%m-%d")
                days_since = (now - created_date).days
            except Exception:
                days_since = None

        is_stale = days_since is not None and days_since > 90
        monthly_cost = round(size_gb * 23 / 1000, 2)  # $23/TB/month

        if is_stale:
            stale_tables.append({
                "database": db,
                "schema": schema,
                "table": table,
                "size_gb": size_gb,
                "last_queried": lq or "Unknown",
                "days_since_queried": days_since,
                "monthly_cost": monthly_cost,
                "recommendation": "Drop or archive" if days_since and days_since > 180 else "Review usage",
            })

    stale_tables.sort(key=lambda x: x["size_gb"], reverse=True)
    stale_total_gb = round(sum(t["size_gb"] for t in stale_tables), 2)
    stale_monthly_cost = round(sum(t["monthly_cost"] for t in stale_tables), 2)

    return {
        "stale_tables": stale_tables,
        "stale_count": len(stale_tables),
        "stale_total_gb": stale_total_gb,
        "stale_monthly_cost": stale_monthly_cost,
        "days": days,
    }


def sync_execute_resize(conn_doc: dict, warehouse_name: str, new_size: str) -> dict:
    from app.utils.constants import VALID_WAREHOUSE_SIZES
    if new_size.upper().replace(" ", "-") not in [s.upper() for s in VALID_WAREHOUSE_SIZES] and new_size.replace(" ", "-") not in VALID_WAREHOUSE_SIZES:
        return {"success": False, "error": f"Invalid warehouse size: {new_size}"}

    try:
        sf = build_sf_connection(conn_doc)
        cur = sf.cursor()
        ddl = f"ALTER WAREHOUSE {warehouse_name} SET WAREHOUSE_SIZE = '{new_size}'"
        cur.execute(ddl)
        sf.close()
        return {"success": True, "ddl": ddl, "warehouse": warehouse_name, "new_size": new_size}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}


def sync_execute_autosuspend(conn_doc: dict, warehouse_name: str, seconds: int) -> dict:
    if not (0 <= seconds <= 86400):
        return {"success": False, "error": f"Invalid auto_suspend value: {seconds}"}

    try:
        sf = build_sf_connection(conn_doc)
        cur = sf.cursor()
        ddl = f"ALTER WAREHOUSE {warehouse_name} SET AUTO_SUSPEND = {seconds}"
        cur.execute(ddl)
        sf.close()
        return {"success": True, "ddl": ddl, "warehouse": warehouse_name, "seconds": seconds}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}
