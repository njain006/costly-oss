"""AI Costs dashboard — cross-provider AI spend intelligence.

Aggregates cost and token data from OpenAI, Anthropic, and Gemini
connectors into KPIs, provider comparisons, trends, and recommendations.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from app.deps import get_current_user
from app.database import db

router = APIRouter(prefix="/api/ai-costs", tags=["ai-costs"])

AI_PLATFORMS = ["openai", "anthropic", "gemini"]

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
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    prev_since = (datetime.utcnow() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

    base_match = {
        "user_id": user_id,
        "platform": {"$in": AI_PLATFORMS},
        "category": "ai_inference",
        "metadata.type": {"$ne": "inventory"},
    }
    current_match = {**base_match, "date": {"$gte": since}}
    prev_match = {**base_match, "date": {"$gte": prev_since, "$lt": since}}

    count = await db.unified_costs.count_documents(current_match)
    if count == 0:
        return {"demo": True, "kpis": {}, "providers": [], "daily_spend": [],
                "daily_tokens": [], "cost_per_1k_trend": [], "model_breakdown": [],
                "recommendations": []}

    # --- KPIs ---
    kpi_result = await db.unified_costs.aggregate([
        {"$match": current_match},
        {"$group": {
            "_id": None,
            "total_cost": {"$sum": "$cost_usd"},
            "total_tokens": {"$sum": "$usage_quantity"},
            "models": {"$addToSet": "$resource"},
            "providers": {"$addToSet": "$platform"},
        }},
    ]).to_list(1)

    prev_result = await db.unified_costs.aggregate([
        {"$match": prev_match},
        {"$group": {"_id": None, "total_cost": {"$sum": "$cost_usd"}}},
    ]).to_list(1)

    kpi = kpi_result[0] if kpi_result else {"total_cost": 0, "total_tokens": 0, "models": [], "providers": []}
    prev_cost = prev_result[0]["total_cost"] if prev_result else 0
    total_cost = kpi["total_cost"]
    total_tokens = kpi["total_tokens"]
    avg_cost_per_1k = (total_cost / total_tokens * 1000) if total_tokens > 0 else 0
    mom_change = ((total_cost - prev_cost) / prev_cost * 100) if prev_cost > 0 else None

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
            daily_map[d] = {"date": d, "openai": 0, "anthropic": 0, "gemini": 0}
        daily_map[d][row["_id"]["platform"]] = round(row["cost"], 2)
    daily_spend = sorted(daily_map.values(), key=lambda x: x["date"])

    # --- Daily tokens (input vs output) ---
    daily_tokens_raw = await db.unified_costs.aggregate([
        {"$match": current_match},
        {"$group": {
            "_id": "$date",
            "input_tokens": {"$sum": {"$ifNull": ["$metadata.input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$metadata.output_tokens", 0]}},
            "total_tokens": {"$sum": "$usage_quantity"},
        }},
        {"$sort": {"_id": 1}},
    ]).to_list(500)

    daily_tokens = [
        {"date": r["_id"], "input": r["input_tokens"], "output": r["output_tokens"], "total": r["total_tokens"]}
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

    return {
        "kpis": {
            "total_cost": round(total_cost, 2),
            "total_tokens": total_tokens,
            "avg_cost_per_1k": round(avg_cost_per_1k, 4),
            "mom_change": round(mom_change, 1) if mom_change is not None else None,
            "model_count": len(kpi.get("models", [])),
            "provider_count": len(kpi.get("providers", [])),
        },
        "providers": provider_list,
        "daily_spend": daily_spend,
        "daily_tokens": daily_tokens,
        "cost_per_1k_trend": cost_per_1k_trend,
        "model_breakdown": model_breakdown,
        "recommendations": recommendations,
    }


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
