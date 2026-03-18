from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user, get_data_source
from app.services.cache import cache
from app.services.snowflake import sync_recommendations, get_credit_price

from app.utils.constants import CACHE_TTL
from app.utils.helpers import run_in_thread

router = APIRouter(tags=["recommendations"])


@router.get("/api/recommendations")
async def recommendations(
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    if not source:
        return []
    cache_key = f"{user_id}:recommendations"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return cached
    credit_price = await get_credit_price(source)
    result = await run_in_thread(sync_recommendations, source, credit_price)
    cache.set(cache_key, result, CACHE_TTL["recommendations"])
    return result
