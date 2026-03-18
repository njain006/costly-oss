from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user, get_data_source
from app.database import db
from app.services.cache import cache
from app.services.snowflake import (
    get_credit_price,
    sync_warehouse_sizing,
    sync_autosuspend_analysis,
    sync_spillage,
    sync_query_patterns,
    sync_cost_attribution,
    sync_stale_tables,
    sync_execute_resize,
    sync_execute_autosuspend,
)


from app.models.warehouse_action import WarehouseResize, WarehouseAutoSuspend
from app.services.snowflake_actions import (
    resize_warehouse as exec_resize,
    set_autosuspend as exec_autosuspend,
    suspend_warehouse as exec_suspend,
    resume_warehouse as exec_resume,
)
from app.utils.constants import CACHE_TTL
from app.utils.helpers import run_in_thread

router = APIRouter(tags=["optimization"])


@router.get("/api/warehouses/sizing")
async def warehouse_sizing(
    days: int = Query(30, ge=1, le=90),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"recommendations": [], "total_monthly_savings": 0, "days": 30, "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:warehouse_sizing:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    credit_price = await get_credit_price(source)
    result = await run_in_thread(sync_warehouse_sizing, source, days, credit_price)
    cache.set(cache_key, result, CACHE_TTL["warehouse_sizing"])
    return {**result, "fetched_at": fetched_at}


@router.get("/api/warehouses/autosuspend")
async def autosuspend_analysis(
    days: int = Query(30, ge=1, le=90),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"recommendations": [], "total_monthly_savings": 0, "days": 30, "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:autosuspend:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    credit_price = await get_credit_price(source)
    result = await run_in_thread(sync_autosuspend_analysis, source, days, credit_price)
    cache.set(cache_key, result, CACHE_TTL["autosuspend"])
    return {**result, "fetched_at": fetched_at}


@router.get("/api/spillage")
async def spillage(
    days: int = Query(30, ge=1, le=90),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"by_warehouse": [], "by_user": [], "top_queries": [], "summary": {"total_spill_gb": 0, "affected_queries": 0, "affected_warehouses": 0}, "days": 30, "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:spillage:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    result = await run_in_thread(sync_spillage, source, days)
    cache.set(cache_key, result, CACHE_TTL["spillage"])
    return {**result, "fetched_at": fetched_at}


@router.get("/api/query-patterns")
async def query_patterns(
    days: int = Query(30, ge=1, le=90),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"patterns": [], "total_patterns": 0, "total_cost_usd": 0, "days": 30, "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:query_patterns:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    credit_price = await get_credit_price(source)
    result = await run_in_thread(sync_query_patterns, source, days, credit_price)
    cache.set(cache_key, result, CACHE_TTL["query_patterns"])
    return {**result, "fetched_at": fetched_at}


@router.get("/api/cost-attribution")
async def cost_attribution(
    days: int = Query(30, ge=1, le=90),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"by_user": [], "by_role": [], "by_database": [], "by_warehouse": [], "top_queries": [], "total_cost_usd": 0, "days": 30, "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:cost_attribution:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    credit_price = await get_credit_price(source)
    result = await run_in_thread(sync_cost_attribution, source, days, credit_price)
    cache.set(cache_key, result, CACHE_TTL["cost_attribution"])
    return {**result, "fetched_at": fetched_at}


@router.get("/api/stale-tables")
async def stale_tables(
    days: int = Query(30, ge=1, le=90),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"stale_tables": [], "stale_count": 0, "stale_total_gb": 0, "stale_monthly_cost": 0, "days": 30, "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:stale_tables:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    result = await run_in_thread(sync_stale_tables, source, days)
    cache.set(cache_key, result, CACHE_TTL["stale_tables"])
    return {**result, "fetched_at": fetched_at}


@router.post("/api/warehouses/{name}/resize")
async def resize_warehouse(
    name: str,
    body: WarehouseResize,
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        raise HTTPException(400, "Cannot execute DDL in demo mode. Connect a Snowflake account first.")
    result = await run_in_thread(sync_execute_resize, source, name, body.new_size)
    if result.get("success"):
        cache.delete_prefix(f"{user_id}:warehouse")
    return result


@router.post("/api/warehouses/{name}/autosuspend")
async def update_autosuspend(
    name: str,
    body: WarehouseAutoSuspend,
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        raise HTTPException(400, "Cannot execute DDL in demo mode. Connect a Snowflake account first.")
    result = await run_in_thread(sync_execute_autosuspend, source, name, body.seconds)
    if result.get("success"):
        cache.delete_prefix(f"{user_id}:autosuspend")
        cache.delete_prefix(f"{user_id}:warehouse")
    return result


# --- New optimization execution endpoints ---


@router.post("/api/optimization/warehouses/{name}/resize")
async def optimization_resize_warehouse(
    name: str,
    body: WarehouseResize,
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        raise HTTPException(400, "Cannot execute DDL in demo mode. Connect a Snowflake account first.")
    result = await exec_resize(source, name, body.new_size, user_id=user_id)
    if result.get("success"):
        cache.delete_prefix(f"{user_id}:warehouse")
    return result


class AutoSuspendBody(BaseModel):
    seconds: int = Field(..., ge=0, le=86400)


@router.post("/api/optimization/warehouses/{name}/autosuspend")
async def optimization_set_autosuspend(
    name: str,
    body: AutoSuspendBody,
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        raise HTTPException(400, "Cannot execute DDL in demo mode. Connect a Snowflake account first.")
    result = await exec_autosuspend(source, name, body.seconds, user_id=user_id)
    if result.get("success"):
        cache.delete_prefix(f"{user_id}:autosuspend")
        cache.delete_prefix(f"{user_id}:warehouse")
    return result


@router.post("/api/optimization/warehouses/{name}/suspend")
async def optimization_suspend_warehouse(
    name: str,
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        raise HTTPException(400, "Cannot execute DDL in demo mode. Connect a Snowflake account first.")
    result = await exec_suspend(source, name, user_id=user_id)
    if result.get("success"):
        cache.delete_prefix(f"{user_id}:warehouse")
    return result


@router.post("/api/optimization/warehouses/{name}/resume")
async def optimization_resume_warehouse(
    name: str,
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        raise HTTPException(400, "Cannot execute DDL in demo mode. Connect a Snowflake account first.")
    result = await exec_resume(source, name, user_id=user_id)
    if result.get("success"):
        cache.delete_prefix(f"{user_id}:warehouse")
    return result


@router.get("/api/optimization/actions")
async def list_optimization_actions(
    limit: int = Query(50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
):
    cursor = db.warehouse_actions.find(
        {"user_id": user_id},
        {"_id": 0, "user_id": 0},
    ).sort("timestamp", -1).limit(limit)
    actions = await cursor.to_list(length=limit)
    return {"actions": actions}
