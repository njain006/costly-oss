import io
import csv
import math
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import StreamingResponse
from pymongo import ASCENDING, DESCENDING

from app.database import db
from app.deps import get_current_user, get_data_source
from app.services.snowflake import get_credit_price
from app.services.query_sync import sync_query_history_to_mongo
from app.utils.constants import CREDITS_MAP
from pymongo import UpdateOne

router = APIRouter(tags=["history"])
limiter = Limiter(key_func=get_remote_address)


def _build_filter(user_id: str, days: int, warehouse: Optional[str], user_name: Optional[str],
                   status: Optional[str], query_type: Optional[str], min_duration_s: Optional[float],
                   max_duration_s: Optional[float], database: Optional[str], has_spill: Optional[bool],
                   query_text_search: Optional[str]) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    filt: dict = {"user_id": user_id, "end_time": {"$gte": since}}
    if warehouse:
        filt["warehouse_name"] = warehouse
    if user_name:
        filt["user_name"] = {"$regex": user_name, "$options": "i"}
    if status:
        filt["execution_status"] = status.upper()
    if query_type:
        filt["query_type"] = {"$regex": query_type, "$options": "i"}
    if database:
        filt["database_name"] = database
    if min_duration_s is not None:
        filt.setdefault("total_elapsed_ms", {})["$gte"] = int(min_duration_s * 1000)
    if max_duration_s is not None:
        filt.setdefault("total_elapsed_ms", {})["$lte"] = int(max_duration_s * 1000)
    if has_spill is True:
        filt["$or"] = [{"bytes_spill_local": {"$gt": 0}}, {"bytes_spill_remote": {"$gt": 0}}]
    elif has_spill is False:
        filt["bytes_spill_local"] = 0
        filt["bytes_spill_remote"] = 0
    if query_text_search:
        filt["query_text"] = {"$regex": query_text_search, "$options": "i"}
    return filt


@router.post("/api/sync/queries")
@limiter.limit("2/minute")
async def manual_sync_queries(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        raise HTTPException(400, "No active Snowflake connection. Add one in Settings.")
    try:
        count = await sync_query_history_to_mongo(user_id, source, days=days)
        total = await db.query_history.count_documents({"user_id": user_id})
        return {"synced": count, "total_stored": total, "days_pulled": days}
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {e}")


@router.get("/api/history/queries")
async def history_queries(
    days: int = Query(30, ge=1, le=365),
    warehouse: Optional[str] = Query(None),
    user_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    query_type: Optional[str] = Query(None),
    min_duration_s: Optional[float] = Query(None),
    max_duration_s: Optional[float] = Query(None),
    database: Optional[str] = Query(None),
    has_spill: Optional[bool] = Query(None),
    query_text_search: Optional[str] = Query(None),
    sort_by: str = Query("total_elapsed_ms"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
):
    filt = _build_filter(user_id, days, warehouse, user_name, status, query_type,
                          min_duration_s, max_duration_s, database, has_spill, query_text_search)

    sort_dir = DESCENDING
    valid_sorts = {"total_elapsed_ms", "bytes_scanned", "credits_cloud_svc", "end_time", "cost_usd"}
    sort_field = sort_by if sort_by in valid_sorts else "total_elapsed_ms"

    total = await db.query_history.count_documents(filt)
    skip = (page - 1) * limit
    cursor = db.query_history.find(filt, {"_id": 0}).sort(sort_field, sort_dir).skip(skip).limit(limit)
    rows = await cursor.to_list(limit)

    for r in rows:
        for k in ("start_time", "end_time", "synced_at"):
            if isinstance(r.get(k), datetime):
                r[k] = r[k].isoformat()

    pipeline = [
        {"$match": filt},
        {"$group": {
            "_id": None,
            "total_elapsed_sum_ms": {"$sum": "$total_elapsed_ms"},
            "avg_elapsed_ms": {"$avg": "$total_elapsed_ms"},
            "bytes_scanned_sum": {"$sum": "$bytes_scanned"},
            "credits_sum": {"$sum": "$credits_cloud_svc"},
            "cost_usd_sum": {"$sum": "$cost_usd"},
            "failed_count": {"$sum": {"$cond": [{"$eq": ["$execution_status", "FAIL"]}, 1, 0]}},
        }},
    ]
    agg = await db.query_history.aggregate(pipeline).to_list(1)
    summary = agg[0] if agg else {}
    summary.pop("_id", None)

    warehouses = await db.query_history.distinct("warehouse_name", {"user_id": user_id})
    databases = await db.query_history.distinct("database_name", {"user_id": user_id})
    users = await db.query_history.distinct("user_name", {"user_id": user_id})

    return {
        "data": rows,
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / limit)),
        "limit": limit,
        "summary": summary,
        "filter_options": {
            "warehouses": sorted([w for w in warehouses if w]),
            "databases": sorted([d for d in databases if d]),
            "users": sorted([u for u in users if u]),
        },
        "fetched_at": datetime.utcnow().isoformat(),
    }


@router.get("/api/history/stats")
async def history_stats(user_id: str = Depends(get_current_user)):
    total = await db.query_history.count_documents({"user_id": user_id})
    if total == 0:
        return {"total": 0, "oldest": None, "newest": None, "warehouses": [], "message": "No data synced yet. Use the Sync button to pull from Snowflake."}
    oldest = await db.query_history.find_one({"user_id": user_id}, sort=[("end_time", ASCENDING)])
    newest = await db.query_history.find_one({"user_id": user_id}, sort=[("end_time", DESCENDING)])
    return {
        "total": total,
        "oldest": oldest["end_time"].isoformat() if oldest else None,
        "newest": newest["end_time"].isoformat() if newest else None,
    }


@router.post("/api/sync/enrich-costs")
async def enrich_costs(user_id: str = Depends(get_current_user)):
    source = await get_data_source(user_id)
    credit_price = await get_credit_price(source) if source else 3.0

    cursor = db.query_history.find(
        {"user_id": user_id, "cost_usd": {"$exists": False}},
        {"_id": 1, "total_elapsed_ms": 1, "warehouse_size": 1, "credits_cloud_svc": 1},
    )
    ops = []
    async for doc in cursor:
        elapsed_ms = int(doc.get("total_elapsed_ms") or 0)
        wh_size = doc.get("warehouse_size") or ""
        credits_hr = CREDITS_MAP.get(wh_size, 0)
        cost_credits = (elapsed_ms / 3_600_000) * credits_hr
        cloud_svc = float(doc.get("credits_cloud_svc") or 0)
        cost_usd = round((cost_credits + cloud_svc) * credit_price, 6)
        ops.append(UpdateOne(
            {"_id": doc["_id"]},
            {"$set": {"cost_credits": round(cost_credits, 6), "cost_usd": cost_usd}},
        ))
        if len(ops) >= 500:
            await db.query_history.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        await db.query_history.bulk_write(ops, ordered=False)
    return {"message": "Cost enrichment complete", "credit_price": credit_price}


@router.get("/api/history/export")
async def export_query_history(
    days: int = Query(30, ge=1, le=365),
    warehouse: Optional[str] = Query(None),
    user_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    query_type: Optional[str] = Query(None),
    min_duration_s: Optional[float] = Query(None),
    max_duration_s: Optional[float] = Query(None),
    database: Optional[str] = Query(None),
    has_spill: Optional[bool] = Query(None),
    query_text_search: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
):
    filt = _build_filter(user_id, days, warehouse, user_name, status, query_type,
                          min_duration_s, max_duration_s, database, has_spill, query_text_search)

    cursor = db.query_history.find(filt, {"_id": 0}).sort("end_time", DESCENDING).limit(10000)
    rows = await cursor.to_list(10000)

    COLUMNS = ["end_time", "user_name", "warehouse_name", "query_type",
               "total_elapsed_ms", "cost_usd", "bytes_scanned",
               "execution_status", "query_text"]

    def generate_csv():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            for k in ("start_time", "end_time", "synced_at"):
                if isinstance(r.get(k), datetime):
                    r[k] = r[k].isoformat()
            if r.get("query_text"):
                r["query_text"] = r["query_text"][:200]
            writer.writerow({c: r.get(c, "") for c in COLUMNS})
        yield buf.getvalue()

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=query_history.csv"},
    )
