from datetime import datetime, timedelta

import redis as sync_redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import create_indexes
from app.services.alerts_engine import evaluate_all_alerts
from app.services.query_sync import sync_all_users_query_history
from app.services.cost_sync import sync_all_platform_costs
from app.services.budget_checker import check_all_budgets
from app.services.cost_digest import generate_and_store_all_digests

# ---------------------------------------------------------------------------
# Distributed scheduler lock — prevents N Uvicorn workers from each running
# the same scheduled job. Only the worker that acquires the Redis lock runs.
# ---------------------------------------------------------------------------
_redis_lock_client = None


def _get_redis_for_lock():
    global _redis_lock_client
    if _redis_lock_client is None:
        _redis_lock_client = sync_redis.from_url("redis://redis:6379", decode_responses=True)
    return _redis_lock_client


async def _locked_evaluate_alerts():
    r = _get_redis_for_lock()
    if not r.set("costly:lock:evaluate_alerts", "1", nx=True, ex=300):
        return
    try:
        await evaluate_all_alerts()
    finally:
        r.delete("costly:lock:evaluate_alerts")


async def _locked_check_budgets():
    r = _get_redis_for_lock()
    if not r.set("costly:lock:check_budgets", "1", nx=True, ex=3600):
        return
    try:
        await check_all_budgets()
    finally:
        r.delete("costly:lock:check_budgets")


async def _locked_sync_query_history():
    r = _get_redis_for_lock()
    if not r.set("costly:lock:sync_query_history", "1", nx=True, ex=21600):
        return
    try:
        await sync_all_users_query_history()
    finally:
        r.delete("costly:lock:sync_query_history")


async def _locked_sync_costs():
    r = _get_redis_for_lock()
    if not r.set("costly:lock:sync_costs", "1", nx=True, ex=21600):
        return
    try:
        await sync_all_platform_costs()
    finally:
        r.delete("costly:lock:sync_costs")


async def _locked_cost_digest():
    r = _get_redis_for_lock()
    if not r.set("costly:lock:cost_digest", "1", nx=True, ex=3600):
        return
    try:
        await generate_and_store_all_digests()
    finally:
        r.delete("costly:lock:cost_digest")


from app.routers import (
    auth, connections, dashboard, costs, queries,
    storage, warehouses, workloads, recommendations,
    alerts, history, debug, optimization, admin,
    public_demo, chat, platforms, anomalies, platform_views,
    teams, settings as settings_router, ai_costs,
)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="costly API", version="2.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(dashboard.router)
app.include_router(costs.router)
app.include_router(queries.router)
app.include_router(storage.router)
app.include_router(warehouses.router)
app.include_router(workloads.router)
app.include_router(recommendations.router)
app.include_router(alerts.router)
app.include_router(history.router)
app.include_router(debug.router)
app.include_router(optimization.router)
app.include_router(admin.router)
app.include_router(public_demo.router)
app.include_router(chat.router)
app.include_router(platform_views.router)
app.include_router(platforms.router)
app.include_router(anomalies.router)
app.include_router(teams.router)
app.include_router(settings_router.router)
app.include_router(ai_costs.router)

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0"}


_scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    await create_indexes()
    _scheduler.add_job(_locked_evaluate_alerts, "interval", minutes=15, id="alert_evaluator")
    _scheduler.add_job(_locked_check_budgets, "interval", hours=1, id="budget_checker")
    _scheduler.add_job(_locked_sync_query_history, "interval", hours=6, id="query_history_sync")
    _scheduler.add_job(_locked_sync_costs, "interval", hours=6, id="platform_cost_sync")
    _scheduler.add_job(
        _locked_sync_query_history, "date",
        run_date=datetime.utcnow() + timedelta(seconds=90),
        id="query_history_boot",
    )
    _scheduler.add_job(
        _locked_sync_costs, "date",
        run_date=datetime.utcnow() + timedelta(seconds=120),
        id="platform_cost_boot",
    )
    _scheduler.add_job(
        _locked_cost_digest, "cron",
        hour=9, minute=0, id="daily_cost_digest",
    )
    _scheduler.start()
    print("[STARTUP] Indexes created. Alert engine + query/cost sync + daily digest scheduled.")


@app.on_event("shutdown")
async def shutdown_event():
    _scheduler.shutdown(wait=False)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
