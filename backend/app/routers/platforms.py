from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException

from app.deps import get_current_user
from app.models.platform import PlatformConnectionCreate
from pydantic import BaseModel

from app.services.unified_costs import (
    get_platform_connections,
    add_platform_connection,
    test_platform_connection,
    sync_platform_costs,
    get_unified_costs,
    update_pricing_overrides,
    CONNECTOR_MAP,
)
from app.services.pricing import (
    get_effective_pricing,
    get_snowflake_cost_breakdown,
    get_platform_pricing_template,
    MARKET_RATES,
)

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("")
async def list_connections(user_id: str = Depends(get_current_user)):
    conns = await get_platform_connections(user_id)
    return [
        {
            "id": str(c["_id"]),
            "platform": c["platform"],
            "name": c["name"],
            "created_at": c["created_at"],
            "last_synced": c.get("last_synced"),
            "pricing_overrides": c.get("pricing_overrides"),
        }
        for c in conns
    ]


@router.get("/supported")
async def list_supported():
    return {"platforms": list(CONNECTOR_MAP.keys())}


@router.post("/connect")
async def connect_platform(
    body: PlatformConnectionCreate,
    user_id: str = Depends(get_current_user),
):
    if body.platform not in CONNECTOR_MAP:
        raise HTTPException(400, f"Unsupported platform: {body.platform}")

    # Test first
    result = await test_platform_connection(body.platform, body.credentials)
    if not result["success"]:
        raise HTTPException(400, f"Connection failed: {result['message']}")

    doc = await add_platform_connection(user_id, body.platform, body.name, body.credentials)
    return {"id": doc["_id"], "platform": body.platform, "name": body.name, "message": "Connected"}


@router.post("/test")
async def test_connection(
    body: PlatformConnectionCreate,
    user_id: str = Depends(get_current_user),
):
    return await test_platform_connection(body.platform, body.credentials)


@router.post("/{connection_id}/sync")
async def sync_costs(
    connection_id: str,
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(get_current_user),
):
    result = await sync_platform_costs(user_id, connection_id, days)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


class PricingOverrideRequest(BaseModel):
    pricing_overrides: dict


@router.put("/{connection_id}/pricing")
async def set_pricing(
    connection_id: str,
    body: PricingOverrideRequest,
    user_id: str = Depends(get_current_user),
):
    """Set custom/negotiated pricing for a platform connection.

    Examples:
    - Snowflake: {"credit_price": 2.50}
    - AWS: {"edp_discount_pct": 10}
    - OpenAI: {"gpt-4o": {"input": 2.0, "output": 8.0}}
    - Any platform: {"discount_pct": 15}
    """
    ok = await update_pricing_overrides(user_id, connection_id, body.pricing_overrides)
    if not ok:
        raise HTTPException(404, "Connection not found")
    return {"success": True, "message": "Pricing overrides updated. Re-sync to apply."}


@router.get("/{connection_id}/pricing")
async def get_pricing(
    connection_id: str,
    user_id: str = Depends(get_current_user),
):
    """Get effective pricing for a connection (custom overrides merged with defaults)."""
    return await get_effective_pricing(user_id, connection_id)


@router.get("/pricing/templates/{platform}")
async def pricing_template(platform: str):
    """Get the configurable pricing fields for a platform.
    Returns field definitions for the pricing configuration UI.
    """
    template = get_platform_pricing_template(platform)
    defaults = MARKET_RATES.get(platform, {})
    return {"platform": platform, "template": template, "market_defaults": defaults}


@router.get("/pricing/market-rates")
async def market_rates():
    """Get all market-rate defaults for reference."""
    return MARKET_RATES


@router.get("/snowflake/cost-breakdown")
async def snowflake_breakdown(user_id: str = Depends(get_current_user)):
    """Get full Snowflake cost decomposition: credit price, storage rate,
    edition, serverless rates, and all cost components.
    """
    return await get_snowflake_cost_breakdown(user_id)


@router.get("/costs")
async def unified_cost_summary(
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(get_current_user),
):
    # TODO: frontend rendering of by_account breakdown is a tracked follow-up
    return await get_unified_costs(user_id, days)
