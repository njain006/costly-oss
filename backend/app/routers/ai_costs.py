"""AI Costs dashboard — cross-provider AI spend intelligence.

Aggregates cost and token data from OpenAI, Anthropic, Claude Code, and
Gemini connectors into KPIs, provider comparisons, trends, and
recommendations. Surfaces cache-tier metrics (read / write / hit rate
/ $ saved) that are unique to the Anthropic + Claude Code connectors.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user
from app.database import db

router = APIRouter(prefix="/api/ai-costs", tags=["ai-costs"])

AI_PLATFORMS = ["openai", "anthropic", "claude_code", "gemini"]

# Model migration mapping: expensive → cheaper alternative
MODEL_ALTERNATIVES = {
    "claude-opus-4": ("claude-sonnet-4", 0.20),  # (alternative, savings_factor)
    "claude-3-opus": ("claude-sonnet-4", 0.25),
    "gpt-4": ("gpt-4o-mini", 0.10),
    "gpt-4-turbo": ("gpt-4o-mini", 0.10),
    "o1": ("o1-mini", 0.25),
    "o1-preview": ("o1-mini", 0.25),
}


@router.get("")
async def get_ai_costs(
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    prev_since = (now - timedelta(days=days * 2)).strftime("%Y-%m-%d")

    # Exclude synthetic rollup records (emitted by the Anthropic connector for
    # per-workspace / per-api_key anomaly surfacing) so totals are not
    # double-counted.
    base_match = {
        "user_id": user_id,
        "platform": {"$in": AI_PLATFORMS},
        "category": "ai_inference",
        "metadata.type": {"$nin": ["inventory", "rollup"]},
    }
    current_match = {**base_match, "date": {"$gte": since}}
    prev_match = {**base_match, "date": {"$gte": prev_since, "$lt": since}}

    count = await db.unified_costs.count_documents(current_match)
    if count == 0:
        empty_kpis = {
            "total_cost": 0, "total_tokens": 0, "avg_cost_per_1k": 0,
            "mom_change": None, "model_count": 0, "provider_count": 0,
            "cache_hit_rate": 0, "cache_savings_usd": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
        }
        return {"demo": True, "kpis": empty_kpis, "providers": [], "daily_spend": [],
                "daily_tokens": [], "cost_per_1k_trend": [], "model_breakdown": [],
                "recommendations": []}

    # --- KPIs (incl. cache-tier metrics from Anthropic + Claude Code) ---
    kpi_result = await db.unified_costs.aggregate([
        {"$match": current_match},
        {"$group": {
            "_id": None,
            "total_cost": {"$sum": "$cost_usd"},
            "total_tokens": {"$sum": "$usage_quantity"},
            "cache_read_tokens": {"$sum": {"$ifNull": ["$metadata.cache_read_tokens", 0]}},
            "cache_write_5m_tokens": {"$sum": {"$ifNull": ["$metadata.cache_write_5m_tokens", 0]}},
            "cache_write_1h_tokens": {"$sum": {"$ifNull": ["$metadata.cache_write_1h_tokens", 0]}},
            "input_tokens": {"$sum": {"$ifNull": ["$metadata.input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$metadata.output_tokens", 0]}},
            "models": {"$addToSet": "$resource"},
            "providers": {"$addToSet": "$platform"},
        }},
    ]).to_list(1)

    prev_result = await db.unified_costs.aggregate([
        {"$match": prev_match},
        {"$group": {"_id": None, "total_cost": {"$sum": "$cost_usd"}}},
    ]).to_list(1)

    kpi = kpi_result[0] if kpi_result else {
        "total_cost": 0, "total_tokens": 0,
        "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "input_tokens": 0, "output_tokens": 0,
        "models": [], "providers": [],
    }
    prev_cost = prev_result[0]["total_cost"] if prev_result else 0
    total_cost = kpi["total_cost"]
    total_tokens = kpi["total_tokens"]
    avg_cost_per_1k = (total_cost / total_tokens * 1000) if total_tokens > 0 else 0
    mom_change = ((total_cost - prev_cost) / prev_cost * 100) if prev_cost > 0 else None

    # Cache metrics: hit rate = cache_read / (cache_read + uncached_input + cache_write)
    cache_read = kpi["cache_read_tokens"]
    cache_write = kpi["cache_write_5m_tokens"] + kpi["cache_write_1h_tokens"]
    uncached_input = kpi["input_tokens"]
    cache_denominator = cache_read + cache_write + uncached_input
    cache_hit_rate = (cache_read / cache_denominator * 100) if cache_denominator > 0 else 0

    # $ saved vs list price: cache_read would have cost (cache_read × list_price_per_token)
    # Approximation — use a weighted average input rate across providers.
    # Anthropic Sonnet default: $3/M input; cache_read is 10% of that.
    # So savings per cache_read_token = $3/M × 0.90 = $2.70/M
    cache_savings_usd = round((cache_read * 2.70) / 1_000_000, 2)

    # --- Provider comparison ---
    providers = await db.unified_costs.aggregate([
        {"$match": current_match},
        {"$group": {
            "_id": "$platform",
            "cost": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$usage_quantity"},
            "input_tokens": {"$sum": {"$ifNull": ["$metadata.input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$metadata.output_tokens", 0]}},
        }},
        {"$sort": {"cost": -1}},
    ]).to_list(10)

    provider_list = []
    for p in providers:
        tokens = p["tokens"] or 1
        provider_list.append({
            "platform": p["_id"],
            "cost": round(p["cost"], 2),
            "tokens": p["tokens"],
            "input_tokens": p["input_tokens"],
            "output_tokens": p["output_tokens"],
            "cost_per_1k": round(p["cost"] / tokens * 1000, 4),
        })

    # --- Daily spend by provider ---
    daily_raw = await db.unified_costs.aggregate([
        {"$match": current_match},
        {"$group": {
            "_id": {"date": "$date", "platform": "$platform"},
            "cost": {"$sum": "$cost_usd"},
        }},
        {"$sort": {"_id.date": 1}},
    ]).to_list(5000)

    daily_map: dict[str, dict] = {}
    for row in daily_raw:
        d = row["_id"]["date"]
        if d not in daily_map:
            daily_map[d] = {"date": d, "openai": 0, "anthropic": 0, "claude_code": 0, "gemini": 0}
        daily_map[d][row["_id"]["platform"]] = round(row["cost"], 2)
    daily_spend = sorted(daily_map.values(), key=lambda x: x["date"])

    # --- Daily tokens by tier (input / output / cache_read / cache_write) ---
    daily_tokens_raw = await db.unified_costs.aggregate([
        {"$match": current_match},
        {"$group": {
            "_id": "$date",
            "input_tokens": {"$sum": {"$ifNull": ["$metadata.input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$metadata.output_tokens", 0]}},
            "cache_read_tokens": {"$sum": {"$ifNull": ["$metadata.cache_read_tokens", 0]}},
            "cache_write_5m_tokens": {"$sum": {"$ifNull": ["$metadata.cache_write_5m_tokens", 0]}},
            "cache_write_1h_tokens": {"$sum": {"$ifNull": ["$metadata.cache_write_1h_tokens", 0]}},
            "total_tokens": {"$sum": "$usage_quantity"},
        }},
        {"$sort": {"_id": 1}},
    ]).to_list(500)

    daily_tokens = [
        {
            "date": r["_id"],
            "input": r["input_tokens"],
            "output": r["output_tokens"],
            "cache_read": r["cache_read_tokens"],
            "cache_write": r["cache_write_5m_tokens"] + r["cache_write_1h_tokens"],
            "total": r["total_tokens"],
        }
        for r in daily_tokens_raw
    ]

    # --- Cost per 1K trend ---
    cost_per_1k_trend = []
    for r in daily_tokens_raw:
        tokens = r["total_tokens"]
        # Get cost for this date
        cost_day = sum(daily_map.get(r["_id"], {}).get(p, 0) for p in AI_PLATFORMS)
        cpk = round(cost_day / tokens * 1000, 4) if tokens > 0 else 0
        cost_per_1k_trend.append({"date": r["_id"], "cost_per_1k": cpk})

    # --- Model breakdown ---
    model_raw = await db.unified_costs.aggregate([
        {"$match": current_match},
        {"$group": {
            "_id": {"model": "$resource", "platform": "$platform"},
            "cost": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$usage_quantity"},
            "input_tokens": {"$sum": {"$ifNull": ["$metadata.input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$metadata.output_tokens", 0]}},
        }},
        {"$sort": {"cost": -1}},
        {"$limit": 20},
    ]).to_list(20)

    model_breakdown = []
    for m in model_raw:
        tokens = m["tokens"] or 1
        model_breakdown.append({
            "model": m["_id"]["model"],
            "platform": m["_id"]["platform"],
            "cost": round(m["cost"], 2),
            "tokens": m["tokens"],
            "input_tokens": m["input_tokens"],
            "output_tokens": m["output_tokens"],
            "cost_per_1k": round(m["cost"] / tokens * 1000, 4),
        })

    # --- Recommendations ---
    recommendations = _generate_recommendations(model_breakdown, total_cost, daily_tokens)

    # --- Workspace breakdown (Anthropic) — from rollup records ---
    workspace_breakdown = await _anthropic_workspace_breakdown(user_id, since)

    # --- Service-tier breakdown (Anthropic priority / batch / flex isolation) ---
    tier_breakdown = await _anthropic_service_tier_breakdown(user_id, since)

    # --- Deprecation spend — how much is still on deprecated models ---
    deprecated_spend = await _anthropic_deprecated_spend(user_id, since)

    return {
        "kpis": {
            "total_cost": round(total_cost, 2),
            "total_tokens": total_tokens,
            "avg_cost_per_1k": round(avg_cost_per_1k, 4),
            "mom_change": round(mom_change, 1) if mom_change is not None else None,
            "model_count": len(kpi.get("models", [])),
            "provider_count": len(kpi.get("providers", [])),
            "cache_hit_rate": round(cache_hit_rate, 1),
            "cache_savings_usd": cache_savings_usd,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "deprecated_spend_usd": deprecated_spend,
        },
        "providers": provider_list,
        "daily_spend": daily_spend,
        "daily_tokens": daily_tokens,
        "cost_per_1k_trend": cost_per_1k_trend,
        "model_breakdown": model_breakdown,
        "workspace_breakdown": workspace_breakdown,
        "tier_breakdown": tier_breakdown,
        "recommendations": recommendations,
    }


async def _anthropic_workspace_breakdown(user_id: str, since: str) -> list[dict]:
    """Aggregate Anthropic workspace rollup records into a per-workspace view."""
    rows = await db.unified_costs.aggregate([
        {"$match": {
            "user_id": user_id,
            "platform": "anthropic",
            "date": {"$gte": since},
            "metadata.type": "rollup",
            "metadata.rollup_type": "workspace",
        }},
        {"$group": {
            "_id": "$metadata.workspace_id",
            "cost": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$usage_quantity"},
            "cache_read_tokens": {
                "$sum": {"$ifNull": ["$metadata.cache_read_tokens", 0]}
            },
            "deprecated_cost": {
                "$sum": {"$ifNull": ["$metadata.deprecated_cost_usd", 0]}
            },
            "has_isolated_tier": {"$max": "$metadata.has_isolated_tier"},
            "models": {"$addToSet": "$metadata.models"},
            "service_tiers": {"$addToSet": "$metadata.service_tiers"},
            "inference_geos": {"$addToSet": "$metadata.inference_geos"},
        }},
        {"$sort": {"cost": -1}},
    ]).to_list(100)

    def _flatten(nested):
        flat = set()
        for entry in nested or []:
            if isinstance(entry, list):
                flat.update(entry)
            elif entry:
                flat.add(entry)
        return sorted(flat)

    return [
        {
            "workspace_id": r["_id"],
            "cost": round(r["cost"], 2),
            "tokens": r["tokens"],
            "cache_read_tokens": r["cache_read_tokens"],
            "deprecated_cost": round(r["deprecated_cost"], 2),
            "has_isolated_tier": bool(r.get("has_isolated_tier")),
            "models": _flatten(r["models"]),
            "service_tiers": _flatten(r["service_tiers"]),
            "inference_geos": _flatten(r["inference_geos"]),
        }
        for r in rows
    ]


async def _anthropic_service_tier_breakdown(user_id: str, since: str) -> list[dict]:
    """Aggregate Anthropic primary records by service_tier for budget tracking."""
    rows = await db.unified_costs.aggregate([
        {"$match": {
            "user_id": user_id,
            "platform": "anthropic",
            "date": {"$gte": since},
            "metadata.type": {"$ne": "rollup"},
            "metadata.service_tier": {"$exists": True},
        }},
        {"$group": {
            "_id": "$metadata.service_tier",
            "cost": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$usage_quantity"},
            "workspaces": {"$addToSet": "$metadata.workspace_id"},
        }},
        {"$sort": {"cost": -1}},
    ]).to_list(20)

    return [
        {
            "service_tier": r["_id"],
            "cost": round(r["cost"], 2),
            "tokens": r["tokens"],
            "workspace_count": len([w for w in r["workspaces"] if w]),
        }
        for r in rows
    ]


async def _anthropic_deprecated_spend(user_id: str, since: str) -> float:
    """Total $ still being spent on deprecated Claude models."""
    rows = await db.unified_costs.aggregate([
        {"$match": {
            "user_id": user_id,
            "platform": "anthropic",
            "date": {"$gte": since},
            "metadata.type": {"$ne": "rollup"},
            "metadata.deprecation_notice": {"$exists": True, "$ne": None},
        }},
        {"$group": {"_id": None, "cost": {"$sum": "$cost_usd"}}},
    ]).to_list(1)
    return round(rows[0]["cost"], 2) if rows else 0.0


def _generate_recommendations(models: list[dict], total_cost: float, daily_tokens: list[dict]) -> list[dict]:
    recs = []

    # Model migration savings
    for m in models:
        model_name = m["model"].lower()
        for expensive, (cheaper, factor) in MODEL_ALTERNATIVES.items():
            if expensive in model_name and m["cost"] > 5:
                savings = round(m["cost"] * (1 - factor), 2)
                recs.append({
                    "type": "model_migration",
                    "title": f"Switch {m['model']} → {cheaper}",
                    "description": f"Moving {m['model']} calls to {cheaper} could save ~{(1 - factor) * 100:.0f}% while maintaining quality for most tasks.",
                    "potential_savings": savings,
                })
                break

    # Token efficiency — check if output/input ratio is unusually high
    if daily_tokens and len(daily_tokens) >= 7:
        recent = daily_tokens[-7:]
        total_input = sum(d["input"] for d in recent)
        total_output = sum(d["output"] for d in recent)
        if total_input > 0:
            ratio = total_output / total_input
            if ratio > 2.0:
                recs.append({
                    "type": "token_efficiency",
                    "title": "High output/input token ratio",
                    "description": f"Output tokens are {ratio:.1f}x input tokens over the last 7 days. Consider shorter system prompts or more concise output formatting to reduce costs.",
                    "potential_savings": round(total_cost * 0.1, 2),
                })

    # Sort by potential savings
    recs.sort(key=lambda x: x["potential_savings"], reverse=True)
    return recs
