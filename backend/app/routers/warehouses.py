from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user, get_data_source
from app.services.cache import cache
from app.services.snowflake import sync_warehouses

from app.utils.constants import CACHE_TTL
from app.utils.helpers import run_in_thread

router = APIRouter(tags=["warehouses"])


@router.get("/api/warehouses")
async def warehouses_endpoint(
    days: int = Query(7, ge=1, le=90),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"warehouses": [], "activity": [], "load_history": [], "wh_stats": [], "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:warehouses:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    result = await run_in_thread(sync_warehouses, source, days)
    cache.set(cache_key, result, CACHE_TTL["warehouses"])
    return {**result, "fetched_at": fetched_at}
