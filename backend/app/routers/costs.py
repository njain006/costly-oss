from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user, get_data_source
from app.services.cache import cache
from app.services.snowflake import sync_costs, get_credit_price

from app.utils.constants import CACHE_TTL
from app.utils.helpers import run_in_thread

router = APIRouter(tags=["costs"])


@router.get("/api/costs")
async def costs(
    days: int = Query(30, ge=1, le=365),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {"daily": [], "by_user": [], "days": days, "fetched_at": fetched_at, "demo": True}
    cache_key = f"{user_id}:costs:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    credit_price = await get_credit_price(source)
    result = await run_in_thread(sync_costs, source, days, credit_price)
    cache.set(cache_key, result, CACHE_TTL["costs"])
    return {**result, "fetched_at": fetched_at}
