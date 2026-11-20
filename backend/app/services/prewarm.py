"""Precompute the Snowflake pages in the background.

ACCOUNT_USAGE queries take seconds to minutes on large accounts, and the data
itself lags 1-3 hours, so computing a page live when someone opens it is both
slow and pointless. This job fills the same cache keys the routers read, every
few hours, so pages open instantly. The refresh button still recomputes live.
"""
import asyncio
import logging

from app.config import settings
from app.database import db
from app.deps import _platform_conn_to_sf_doc
from app.services.cache import cache
from app.services.connectors.errors import QuotaExceededError
from app.services.snowflake import (
    get_credit_price, sync_dashboard, sync_costs, sync_storage, sync_queries,
    sync_workloads, sync_warehouses, sync_warehouse_sizing, sync_autosuspend_analysis,
    sync_spillage, sync_query_patterns, sync_cost_attribution, sync_stale_tables,
    sync_recommendations,
)
from app.utils.helpers import run_in_thread

logger = logging.getLogger(__name__)

# Outlive the refresh interval, so a page is never cold between runs.
PREWARM_TTL = (max(settings.prewarm_interval_hours, 1) + 2) * 3600
PREWARM_DAYS = (30, 7)      # default range first
PREWARM_CONCURRENCY = 4     # pages computed at once; each holds one Snowflake session


def _jobs(source: dict, days: int, price: float) -> list:
    return [
        (f"dashboard:{days}", sync_dashboard, (source, days, price)),
        (f"costs:{days}", sync_costs, (source, days, price)),
        (f"warehouses:{days}", sync_warehouses, (source, days)),
        (f"autosuspend:{days}", sync_autosuspend_analysis, (source, days, price)),
        (f"warehouse_sizing:{days}", sync_warehouse_sizing, (source, days, price)),
        (f"storage:{days}", sync_storage, (source, days)),
        (f"stale_tables:{days}", sync_stale_tables, (source, days)),
        (f"cost_attribution:{days}", sync_cost_attribution, (source, days, price)),
        (f"query_patterns:{days}", sync_query_patterns, (source, days, price)),
        (f"workloads:{days}", sync_workloads, (source, days)),
        (f"queries:{days}:1:50", sync_queries, (source, days, 1, 50)),
        (f"spillage:{days}", sync_spillage, (source, days)),
    ]


async def prewarm_snowflake_pages() -> None:
    from app.deps import cache_scope
    conns = await db.platform_connections.find({"platform": "snowflake"}).to_list(500)
    # Every account, so switching accounts is instant too. Default-account
    # pages read the same per-account keys.
    for pc in sorted(conns, key=lambda c: c.get("last_synced") or "", reverse=True):
        user_id = pc.get("user_id")
        if not user_id:
            continue
        source = _platform_conn_to_sf_doc(pc)
        scope = cache_scope(user_id, source)
        try:
            price = await get_credit_price(source)
        except Exception:
            logger.warning("prewarm: credit price failed for %s", scope, exc_info=True)
            continue
        jobs = _jobs(source, PREWARM_DAYS[0], price)
        jobs.append(("recommendations", sync_recommendations, (source, price)))
        for days in PREWARM_DAYS[1:]:
            jobs += _jobs(source, days, price)
        sem = asyncio.Semaphore(PREWARM_CONCURRENCY)
        blocked: list = []

        async def _run(key, fn, args, scope=scope, blocked=blocked):
            async with sem:
                if blocked:
                    return  # warehouse quota used up; don't keep calling Snowflake
                try:
                    result = await run_in_thread(fn, *args)
                    # Keep a long-lived copy too, so a page never opens empty
                    # even if this job is late or the backend just restarted.
                    cache.set_with_stale(f"{scope}:{key}", result, PREWARM_TTL)
                except QuotaExceededError as e:
                    if not blocked:
                        logger.warning("prewarm: stopping for %s: %s", scope, e)
                    blocked.append(e)
                except Exception:
                    # One slow or failing page must not stop the rest.
                    logger.warning("prewarm: %s failed for %s", key, scope, exc_info=True)

        # Jobs are listed default-range first; gather keeps that priority
        # because the semaphore admits them in order.
        await asyncio.gather(*(_run(k, f, a) for k, f, a in jobs))
        logger.info("prewarm: finished %d pages for %s", len(jobs), scope)
