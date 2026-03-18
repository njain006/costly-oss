from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user, get_data_source
from app.services.cache import cache
from app.services.snowflake import sync_queries

from app.utils.constants import CACHE_TTL
from app.utils.helpers import run_in_thread

router = APIRouter(tags=["queries"])


@router.get("/api/queries")
async def queries(
    days: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        return {"data": [], "total": 0, "page": page, "pages": 0, "limit": limit, "days": 7, "demo": True}
    cache_key = f"{user_id}:queries:{days}:{page}:{limit}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True}
    result = await run_in_thread(sync_queries, source, days, page, limit)
    cache.set(cache_key, result, CACHE_TTL["queries"])
    return result
