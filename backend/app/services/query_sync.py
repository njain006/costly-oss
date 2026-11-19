from datetime import datetime, timedelta

from pymongo import UpdateOne, ASCENDING, DESCENDING

from app.database import db
from app.services.snowflake import build_sf_connection, get_credit_price
from app.utils.constants import CREDITS_MAP
from app.utils.helpers import run_in_thread


def _pull_query_history_from_sf(conn_doc: dict, since_iso: str, limit: int = 10000, credit_price: float = 3.0) -> list:
    sf = build_sf_connection(conn_doc)
    cur = sf.cursor()
    cur.execute(f"""
        SELECT
            QUERY_ID, START_TIME, END_TIME,
            USER_NAME, ROLE_NAME,
            WAREHOUSE_NAME, WAREHOUSE_SIZE, WAREHOUSE_TYPE, CLUSTER_NUMBER,
            QUERY_TYPE, QUERY_TEXT, DATABASE_NAME, SCHEMA_NAME, QUERY_TAG,
            EXECUTION_STATUS, ERROR_CODE, ERROR_MESSAGE,
            TOTAL_ELAPSED_TIME, COMPILATION_TIME, EXECUTION_TIME,
            QUEUED_OVERLOAD_TIME, QUEUED_PROVISIONING_TIME, TRANSACTION_BLOCKED_TIME,
            BYTES_SCANNED,
            BYTES_SPILLED_TO_LOCAL_STORAGE, BYTES_SPILLED_TO_REMOTE_STORAGE,
            BYTES_WRITTEN, ROWS_PRODUCED, ROWS_INSERTED, ROWS_UPDATED, ROWS_DELETED,
            PARTITIONS_SCANNED, PARTITIONS_TOTAL,
            PERCENTAGE_SCANNED_FROM_CACHE,
            CREDITS_USED_CLOUD_SERVICES,
            QUERY_PARAMETERIZED_HASH
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE END_TIME > '{since_iso}'
          AND IS_CLIENT_GENERATED_STATEMENT = FALSE
        ORDER BY END_TIME
        LIMIT {limit}
    """)
    cols = [d[0].lower() for d in cur.description]
    rows = []
    for r in cur.fetchall():
        rd = dict(zip(cols, r))
        elapsed_ms = int(rd.get("total_elapsed_time") or 0)
        wh_size = rd.get("warehouse_size") or ""
        credits_hr = CREDITS_MAP.get(wh_size, 0)
        cost_credits = (elapsed_ms / 3_600_000) * credits_hr
        cloud_svc = float(rd.get("credits_used_cloud_services") or 0)
        rd["cost_credits"] = round(cost_credits, 6)
        rd["cost_usd"] = round((cost_credits + cloud_svc) * credit_price, 6)
        rows.append(rd)
    sf.close()
    return rows


async def sync_query_history_to_mongo(user_id: str, conn_doc: dict, days: int = 3) -> int:
    connection_id = str(conn_doc.get("connection_id") or conn_doc.get("_id", ""))
    latest = await db.query_history.find_one(
        {"user_id": user_id, "connection_id": connection_id},
        sort=[("end_time", DESCENDING)],
    )
    if latest and latest.get("end_time"):
        since_dt = latest["end_time"] - timedelta(days=2)
    else:
        since_dt = datetime.utcnow() - timedelta(days=days)
    since_iso = since_dt.strftime("%Y-%m-%d %H:%M:%S")

    credit_price = await get_credit_price(conn_doc)
    rows = await run_in_thread(_pull_query_history_from_sf, conn_doc, since_iso, 10000, credit_price)
    if not rows:
        return 0

    now = datetime.utcnow()
    docs = []
    for rd in rows:
        docs.append({
            "user_id": user_id,
            "connection_id": connection_id,
            "query_id": rd.get("query_id"),
            "start_time": rd.get("start_time"),
            "end_time": rd.get("end_time"),
            "user_name": rd.get("user_name"),
            "role_name": rd.get("role_name"),
            "warehouse_name": rd.get("warehouse_name"),
            "warehouse_size": rd.get("warehouse_size"),
            "warehouse_type": rd.get("warehouse_type"),
            "cluster_number": int(rd.get("cluster_number") or 0),
            "query_type": rd.get("query_type"),
            "query_text": (rd.get("query_text") or "")[:1000],
            "database_name": rd.get("database_name"),
            "schema_name": rd.get("schema_name"),
            "query_tag": rd.get("query_tag"),
            "execution_status": rd.get("execution_status"),
            "error_code": rd.get("error_code"),
            "error_message": (rd.get("error_message") or "")[:500],
            "total_elapsed_ms": int(rd.get("total_elapsed_time") or 0),
            "compilation_ms": int(rd.get("compilation_time") or 0),
            "execution_ms": int(rd.get("execution_time") or 0),
            "queued_overload_ms": int(rd.get("queued_overload_time") or 0),
            "queued_prov_ms": int(rd.get("queued_provisioning_time") or 0),
            "blocked_ms": int(rd.get("transaction_blocked_time") or 0),
            "bytes_scanned": int(rd.get("bytes_scanned") or 0),
            "bytes_spill_local": int(rd.get("bytes_spilled_to_local_storage") or 0),
            "bytes_spill_remote": int(rd.get("bytes_spilled_to_remote_storage") or 0),
            "bytes_written": int(rd.get("bytes_written") or 0),
            "rows_produced": int(rd.get("rows_produced") or 0),
            "rows_inserted": int(rd.get("rows_inserted") or 0),
            "rows_updated": int(rd.get("rows_updated") or 0),
            "rows_deleted": int(rd.get("rows_deleted") or 0),
            "partitions_scanned": int(rd.get("partitions_scanned") or 0),
            "partitions_total": int(rd.get("partitions_total") or 0),
            "cache_hit_pct": round(float(rd.get("percentage_scanned_from_cache") or 0), 1),
            "credits_cloud_svc": round(float(rd.get("credits_used_cloud_services") or 0), 8),
            "cost_credits": rd.get("cost_credits", 0.0),
            "cost_usd": rd.get("cost_usd", 0.0),
            "param_hash": rd.get("query_parameterized_hash"),
            "synced_at": now,
        })

    ops = [
        UpdateOne(
            {"user_id": user_id, "query_id": doc["query_id"]},
            {"$set": doc},
            upsert=True,
        )
        for doc in docs
    ]
    result = await db.query_history.bulk_write(ops, ordered=False)
    return result.upserted_count + result.modified_count


async def sync_all_users_query_history():
    print(f"[QH SYNC] Starting incremental sync at {datetime.utcnow().isoformat()}")
    try:
        from app.deps import all_snowflake_sources
        for conn_doc in await all_snowflake_sources():
            user_id = conn_doc["user_id"]
            try:
                count = await sync_query_history_to_mongo(user_id, conn_doc, days=2)
                print(f"[QH SYNC] user={user_id} saved/updated {count} rows")
            except Exception as e:
                print(f"[QH SYNC] user={user_id} failed: {e}")
    except Exception as e:
        print(f"[QH SYNC] Error: {e}")
