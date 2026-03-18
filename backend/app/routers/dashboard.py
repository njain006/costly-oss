from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user, get_data_source
from app.services.cache import cache
from app.services.snowflake import sync_dashboard, get_credit_price
from app.services.demo import generate_demo_dashboard
from app.utils.constants import CACHE_TTL
from app.utils.helpers import run_in_thread

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
async def dashboard(
    days: int = Query(30, ge=1, le=365),
    refresh: bool = Query(False),
    user_id: str = Depends(get_current_user),
):
    source = await get_data_source(user_id)
    fetched_at = datetime.utcnow().isoformat()
    if not source:
        return {
            "total_cost": 0, "total_credits": 0, "active_warehouses": 0,
            "expensive_queries": 0, "query_count": 0, "failed_queries": 0,
            "storage_gb": 0, "cost_trend": [], "top_warehouses": [],
            "top_users": [], "credit_price": 0, "days": days,
            "anomalies": [], "fetched_at": fetched_at, "demo": True,
        }
    cache_key = f"{user_id}:dashboard:{days}"
    if refresh:
        cache.delete(cache_key)
    cached = cache.get(cache_key)
    if cached:
        return {**cached, "cached": True, "fetched_at": fetched_at}
    credit_price = await get_credit_price(source)
    result = await run_in_thread(sync_dashboard, source, days, credit_price)
    cache.set(cache_key, result, CACHE_TTL["dashboard"])
    return {**result, "fetched_at": fetched_at}
