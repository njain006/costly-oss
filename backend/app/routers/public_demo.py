"""Public demo endpoints — no authentication required.

These mirror the authenticated dashboard/optimization endpoints but always
return demo data.  Used by the public /demo experience so visitors can
explore the product without signing up.
"""

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

limiter = Limiter(key_func=get_remote_address)

from app.services.unified_costs import CONNECTOR_MAP
from app.services.demo import (
    generate_demo_dashboard,
    generate_demo_costs,
    generate_demo_queries_paginated,
    generate_demo_storage,
    generate_demo_warehouses,
    generate_demo_warehouse_sizing,
    generate_demo_autosuspend,
    generate_demo_spillage,
    generate_demo_query_patterns,
    generate_demo_cost_attribution,
    generate_demo_stale_tables,
    generate_demo_recommendations,
    generate_demo_workloads,
    generate_demo_workload_runs,
)

router = APIRouter(prefix="/api/demo", tags=["public-demo"])

_now = lambda: datetime.utcnow().isoformat()


@router.get("/dashboard")
async def demo_dashboard(days: int = Query(30, ge=1, le=365)):
    return {**generate_demo_dashboard(days), "fetched_at": _now(), "demo": True}


@router.get("/costs")
async def demo_costs(days: int = Query(30, ge=1, le=365)):
    return {**generate_demo_costs(days), "fetched_at": _now(), "demo": True}


@router.get("/queries")
async def demo_queries(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    return {**generate_demo_queries_paginated(page, limit), "demo": True}


@router.get("/storage")
async def demo_storage():
    return {**generate_demo_storage(), "fetched_at": _now(), "demo": True}


@router.get("/warehouses")
async def demo_warehouses():
    return {**generate_demo_warehouses(), "fetched_at": _now(), "demo": True}


@router.get("/warehouses/sizing")
async def demo_sizing(days: int = Query(30, ge=1, le=90)):
    return {**generate_demo_warehouse_sizing(), "fetched_at": _now(), "demo": True}


@router.get("/warehouses/autosuspend")
async def demo_autosuspend(days: int = Query(30, ge=1, le=90)):
    return {**generate_demo_autosuspend(), "fetched_at": _now(), "demo": True}


@router.get("/spillage")
async def demo_spillage(days: int = Query(30, ge=1, le=90)):
    return {**generate_demo_spillage(), "fetched_at": _now(), "demo": True}


@router.get("/query-patterns")
async def demo_query_patterns(days: int = Query(30, ge=1, le=90)):
    return {**generate_demo_query_patterns(), "fetched_at": _now(), "demo": True}


@router.get("/cost-attribution")
async def demo_cost_attribution(days: int = Query(30, ge=1, le=90)):
    return {**generate_demo_cost_attribution(), "fetched_at": _now(), "demo": True}


@router.get("/stale-tables")
async def demo_stale_tables(days: int = Query(30, ge=1, le=90)):
    return {**generate_demo_stale_tables(), "fetched_at": _now(), "demo": True}


@router.get("/recommendations")
async def demo_recommendations():
    return generate_demo_recommendations()


@router.get("/workloads")
async def demo_workloads(days: int = Query(30, ge=1, le=365)):
    return {**generate_demo_workloads(days), "demo": True}


@router.get("/workloads/{workload_id}/runs")
async def demo_workload_runs(workload_id: str, days: int = Query(30, ge=1, le=365)):
    return {**generate_demo_workload_runs(workload_id, days), "demo": True}


@router.get("/connections/status")
async def demo_connections_status():
    return {"has_connection": False, "demo": True}


@router.get("/alerts")
async def demo_alerts():
    return []


@router.get("/platforms")
async def demo_platforms():
    from app.services.demo_platforms import generate_demo_platform_connections
    return generate_demo_platform_connections()


@router.get("/platforms/costs")
async def demo_platform_costs(days: int = Query(30, ge=1, le=365)):
    from app.services.demo_platforms import generate_demo_unified_costs
    return generate_demo_unified_costs(days)


@router.get("/platforms/supported")
async def demo_supported():
    return {"platforms": list(CONNECTOR_MAP.keys())}


class DemoChatRequest(BaseModel):
    messages: list[dict]


@router.post("/chat")
@limiter.limit("5/minute")
async def demo_chat(request: Request, body: DemoChatRequest):
    from app.services.agent import run_agent
    if not body.messages:
        return {"response": "Please send a message.", "demo": True}
    response = await run_agent(body.messages, source=None, credit_price=3.0)
    return {"response": response, "demo": True}
