from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user, get_data_source
from app.services.cache import cache
from app.services.snowflake import sync_workloads, sync_workload_runs

from app.utils.constants import CACHE_TTL
from app.utils.helpers import run_in_thread

router = APIRouter(tags=["workloads"])


@router.get("/api/workloads")
async def workloads_endpoint(
    days: int = Query(30, ge=1, le=365),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        return {"workloads": [], "total_workloads": 0, "total_executions": 0, "days": days, "demo": True}
    cache_key = f"{user_id}:workloads:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True}
    result = await run_in_thread(sync_workloads, source, days)
    cache.set(cache_key, result, CACHE_TTL["workloads"])
    return result


@router.get("/api/workloads/{workload_id}/runs")
async def workload_runs(
    workload_id: str,
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        return {"runs": [], "workload_id": workload_id, "demo": True}
    return await run_in_thread(sync_workload_runs, source, workload_id, days)
