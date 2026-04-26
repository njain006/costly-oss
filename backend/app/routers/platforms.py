import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.deps import get_current_user
from app.database import db
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


# ─── Claude Code — upload-based flow for hosted users who cannot mount
#     ~/.claude/projects into the backend container. Accepts a multipart
#     form of .jsonl session files, parses them with the same connector
#     used for filesystem reads, and upserts the resulting UnifiedCost
#     rows into the caller's account. Creates a stable "Claude Code
#     (uploaded)" connection on first use so the sync appears in the UI.
MAX_UPLOAD_BYTES_PER_FILE = 100 * 1024 * 1024  # 100 MB
MAX_UPLOAD_BYTES_TOTAL = 500 * 1024 * 1024  # 500 MB per request


@router.post("/claude-code/upload")
async def upload_claude_code_jsonl(
    files: list[UploadFile] = File(...),
    user_id: str = Depends(get_current_user),
):
    if not files:
        raise HTTPException(400, "No files provided")

    # Lazy imports — the connector module is optional at startup
    from app.services.connectors.claude_code_connector import (
        ClaudeCodeConnector,
        aggregate_costs,
        iter_jsonl_turns,
    )

    total_bytes = 0
    with tempfile.TemporaryDirectory(prefix="claude-upload-") as tmpdir:
        # Each file is written under a pseudo-project directory because
        # iter_jsonl_turns walks projects_dir/*/*.jsonl. Use the filename
        # stem as the project folder so different uploads don't collide.
        for upload in files:
            name = Path(upload.filename or "upload.jsonl").name
            if not name.endswith(".jsonl"):
                raise HTTPException(400, f"Only .jsonl files accepted (got {name})")
            project = Path(tmpdir) / (Path(name).stem or "session")
            project.mkdir(parents=True, exist_ok=True)
            dest = project / name
            # Stream to disk with size cap
            written = 0
            with dest.open("wb") as fh:
                while chunk := await upload.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES_PER_FILE:
                        raise HTTPException(413, f"{name} exceeds 100MB per-file limit")
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_BYTES_TOTAL:
                        raise HTTPException(413, "Upload exceeds 500MB total limit")
                    fh.write(chunk)

        # Parse + aggregate using the live connector logic
        turns = list(iter_jsonl_turns(Path(tmpdir)))
        costs = aggregate_costs(turns)

    if not costs:
        return {
            "success": True,
            "files": len(files),
            "turns_parsed": len(turns),
            "records": 0,
            "total_cost_usd": 0.0,
            "message": "Uploaded files contained no billable assistant turns (empty, malformed, or user-only).",
        }

    # Find-or-create the Claude Code (uploaded) connection
    conn = await db.platform_connections.find_one({
        "user_id": user_id,
        "platform": "claude_code",
        "name": "Claude Code (uploaded)",
    })
    if conn is None:
        insert = await db.platform_connections.insert_one({
            "user_id": user_id,
            "platform": "claude_code",
            "name": "Claude Code (uploaded)",
            "credentials": {},
            "pricing_overrides": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_synced": None,
        })
        connection_id = str(insert.inserted_id)
    else:
        connection_id = str(conn["_id"])

    # Upsert UnifiedCost rows
    from pymongo import UpdateOne

    ops = []
    total_cost = 0.0
    for cost in costs:
        doc = cost.model_dump()
        doc["user_id"] = user_id
        doc["connection_id"] = connection_id
        doc["account_name"] = "Claude Code (uploaded)"
        doc["account_id"] = ""
        total_cost += doc["cost_usd"]
        ops.append(UpdateOne(
            {
                "user_id": user_id,
                "connection_id": connection_id,
                "date": cost.date,
                "platform": cost.platform,
                "service": cost.service,
                "resource": cost.resource,
                "team": cost.team,
            },
            {"$set": doc},
            upsert=True,
        ))

    result = await db.unified_costs.bulk_write(ops)

    await db.platform_connections.update_one(
        {"_id": ObjectId(connection_id)},
        {"$set": {"last_synced": datetime.now(timezone.utc).isoformat()}},
    )

    return {
        "success": True,
        "connection_id": connection_id,
        "files": len(files),
        "turns_parsed": len(turns),
        "records": len(costs),
        "upserted": result.upserted_count,
        "modified": result.modified_count,
        "total_cost_usd": round(total_cost, 2),
    }


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
