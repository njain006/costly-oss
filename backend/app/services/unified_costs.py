"""Unified cost service — syncs, stores, and queries normalized cost data
across all connected platforms.
"""

from datetime import datetime, timedelta

from app.database import db
from app.models.platform import PlatformType, UnifiedCost
from app.services.connectors.base import BaseConnector
from app.services.connectors.aws_connector import AWSConnector
from app.services.connectors.anthropic_connector import AnthropicConnector
from app.services.connectors.dbt_cloud_connector import DbtCloudConnector
from app.services.connectors.openai_connector import OpenAIConnector
from app.services.connectors.fivetran_connector import FivetranConnector
from app.services.connectors.gemini_connector import GeminiConnector
from app.services.connectors.airbyte_connector import AirbyteConnector
from app.services.connectors.monte_carlo_connector import MonteCarloConnector
from app.services.connectors.bigquery_connector import BigQueryConnector
from app.services.connectors.databricks_connector import DatabricksConnector
from app.services.connectors.looker_connector import LookerConnector
from app.services.connectors.tableau_connector import TableauConnector
from app.services.connectors.github_connector import GitHubConnector
from app.services.connectors.gitlab_connector import GitLabConnector
from app.services.connectors.omni_connector import OmniConnector
from app.services.connectors.snowflake_connector import SnowflakeConnector
from app.services.encryption import decrypt_value

CONNECTOR_MAP: dict[str, type[BaseConnector]] = {
    "snowflake": SnowflakeConnector,
    "aws": AWSConnector,
    "anthropic": AnthropicConnector,
    "dbt_cloud": DbtCloudConnector,
    "openai": OpenAIConnector,
    "fivetran": FivetranConnector,
    "gemini": GeminiConnector,
    "airbyte": AirbyteConnector,
    "monte_carlo": MonteCarloConnector,
    "gcp": BigQueryConnector,
    "databricks": DatabricksConnector,
    "looker": LookerConnector,
    "tableau": TableauConnector,
    "github": GitHubConnector,
    "gitlab": GitLabConnector,
    "omni": OmniConnector,
}


def _get_connector(connection_doc: dict) -> BaseConnector:
    """Instantiate the right connector from a stored connection document."""
    platform = connection_doc["platform"]
    connector_cls = CONNECTOR_MAP.get(platform)
    if not connector_cls:
        raise ValueError(f"No connector for platform: {platform}")

    # Decrypt stored credentials
    creds = {}
    for k, v in connection_doc.get("credentials", {}).items():
        try:
            creds[k] = decrypt_value(v)
        except Exception:
            creds[k] = v  # Not encrypted (e.g. region)
    return connector_cls(creds)


async def get_platform_connections(user_id: str) -> list[dict]:
    """Get all platform connections for a user."""
    cursor = db.platform_connections.find({"user_id": user_id})
    return await cursor.to_list(length=100)


async def add_platform_connection(user_id: str, platform: str, name: str, credentials: dict) -> dict:
    """Store a new platform connection with encrypted credentials."""
    from app.services.encryption import encrypt_value
    from app.utils.helpers import run_in_thread

    encrypted_creds = {}
    for k, v in credentials.items():
        if k in ("region", "account", "warehouse", "database", "schema_name", "role"):  # Don't encrypt non-secret fields
            encrypted_creds[k] = v
        else:
            encrypted_creds[k] = encrypt_value(v)

    doc = {
        "user_id": user_id,
        "platform": platform,
        "name": name,
        "credentials": encrypted_creds,
        "pricing_overrides": None,
        "created_at": datetime.utcnow().isoformat(),
        "last_synced": None,
    }

    if platform == "aws":
        try:
            from app.services.connectors.aws_connector import AWSConnector
            connector = await run_in_thread(lambda: AWSConnector(credentials))
            doc["account_id"] = connector.account_id
        except Exception:
            pass

    result = await db.platform_connections.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


async def test_platform_connection(platform: str, credentials: dict) -> dict:
    """Test a platform connection without storing it."""
    from app.utils.helpers import run_in_thread

    connector_cls = CONNECTOR_MAP.get(platform)
    if not connector_cls:
        return {"success": False, "message": f"Unsupported platform: {platform}"}
    try:
        connector = connector_cls(credentials)
        return await run_in_thread(connector.test_connection)
    except Exception as e:
        return {"success": False, "message": str(e)}


async def sync_platform_costs(user_id: str, connection_id: str, days: int = 30) -> dict:
    """Sync costs from a single platform connection into the unified store."""
    from bson import ObjectId
    conn = await db.platform_connections.find_one({"_id": ObjectId(connection_id), "user_id": user_id})
    if not conn:
        return {"success": False, "message": "Connection not found"}

    try:
        connector = _get_connector(conn)
    except ValueError as e:
        return {"success": False, "message": str(e)}

    from app.utils.helpers import run_in_thread
    costs: list[UnifiedCost] = await run_in_thread(connector.fetch_costs, days)

    if not costs:
        return {"success": True, "records": 0, "message": "No cost data found"}

    # Apply pricing overrides if user has negotiated rates
    pricing_overrides = conn.get("pricing_overrides")
    if pricing_overrides:
        costs = _apply_pricing_overrides(costs, pricing_overrides, conn["platform"])

    # Upsert into unified_costs collection
    ops = []
    for cost in costs:
        doc = cost.model_dump()
        doc["user_id"] = user_id
        doc["connection_id"] = connection_id
        doc["account_name"] = conn["name"]
        doc["account_id"] = conn.get("account_id", "")
        ops.append({
            "filter": {
                "user_id": user_id,
                "connection_id": connection_id,
                "date": cost.date,
                "platform": cost.platform,
                "service": cost.service,
                "resource": cost.resource,
            },
            "update": {"$set": doc},
        })

    # Batch upsert
    from pymongo import UpdateOne
    bulk_ops = [UpdateOne(op["filter"], op["update"], upsert=True) for op in ops]
    result = await db.unified_costs.bulk_write(bulk_ops)

    # Update last_synced
    await db.platform_connections.update_one(
        {"_id": conn["_id"]},
        {"$set": {"last_synced": datetime.utcnow().isoformat()}},
    )

    return {
        "success": True,
        "records": len(costs),
        "upserted": result.upserted_count,
        "modified": result.modified_count,
    }


def _apply_pricing_overrides(
    costs: list[UnifiedCost], overrides: dict, platform: str,
) -> list[UnifiedCost]:
    """Apply user's negotiated pricing to cost records.

    Supported override formats:
    - Snowflake: {"credit_price": 2.50}  — multiplies credits by custom price
    - AWS: {"edp_discount_pct": 10}      — applies % discount to all AWS costs
    - OpenAI/Anthropic: {"gpt-4o": {"input": 2.0, "output": 8.0}} — per-model rates
    - Generic: {"discount_pct": 15}       — flat % discount on any platform
    """
    discount_pct = overrides.get("discount_pct", 0) or overrides.get("edp_discount_pct", 0)
    credit_price = overrides.get("credit_price")

    adjusted = []
    for cost in costs:
        c = cost.model_copy()

        # Snowflake credit price override
        if credit_price and platform == "snowflake" and cost.usage_unit == "credits":
            c.cost_usd = round(cost.usage_quantity * credit_price, 6)

        # Per-model pricing (AI platforms)
        elif platform in ("openai", "anthropic", "gemini"):
            model = cost.metadata.get("model", "")
            model_override = None
            for key in sorted(overrides.keys(), key=lambda x: -len(x)):
                if key in model and isinstance(overrides[key], dict):
                    model_override = overrides[key]
                    break
            if model_override:
                input_tokens = cost.metadata.get("input_tokens", 0)
                output_tokens = cost.metadata.get("output_tokens", 0)
                input_rate = model_override.get("input", 0)
                output_rate = model_override.get("output", 0)
                c.cost_usd = round(
                    (input_tokens / 1_000_000) * input_rate +
                    (output_tokens / 1_000_000) * output_rate,
                    6,
                )

        # Flat percentage discount
        if discount_pct > 0:
            c.cost_usd = round(c.cost_usd * (1 - discount_pct / 100), 6)

        adjusted.append(c)

    return adjusted


async def update_pricing_overrides(user_id: str, connection_id: str, overrides: dict) -> bool:
    """Update pricing overrides for a platform connection."""
    from bson import ObjectId
    result = await db.platform_connections.update_one(
        {"_id": ObjectId(connection_id), "user_id": user_id},
        {"$set": {"pricing_overrides": overrides}},
    )
    return result.modified_count > 0


async def get_unified_costs(user_id: str, days: int = 30) -> dict:
    """Query the unified cost store for aggregated data."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    pipeline = [
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {
            "_id": None,
            "total_cost": {"$sum": "$cost_usd"},
            "record_count": {"$sum": 1},
        }},
    ]
    total = await db.unified_costs.aggregate(pipeline).to_list(1)
    total_cost = total[0]["total_cost"] if total else 0

    # By platform
    by_platform = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {"_id": "$platform", "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"cost": -1}},
    ]).to_list(50)

    # By category
    by_category = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {"_id": "$category", "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"cost": -1}},
    ]).to_list(50)

    # By service
    by_service = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {"_id": "$service", "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"cost": -1}},
    ]).to_list(50)

    # Daily trend
    daily_trend = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {"_id": "$date", "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"_id": 1}},
    ]).to_list(365)

    # Top resources
    top_resources = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {
            "_id": {"platform": "$platform", "resource": "$resource"},
            "cost": {"$sum": "$cost_usd"},
            "usage": {"$sum": "$usage_quantity"},
        }},
        {"$sort": {"cost": -1}},
        {"$limit": 20},
    ]).to_list(20)

    # By account — per-connection breakdown (useful when multiple accounts share a platform)
    by_account = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": since}}},
        {"$group": {
            "_id": {
                "platform": "$platform",
                "connection_id": "$connection_id",
                "account_name": {"$ifNull": ["$account_name", "Unknown"]},
            },
            "account_id": {"$first": "$account_id"},
            "cost": {"$sum": "$cost_usd"},
        }},
        {"$sort": {"cost": -1}},
    ]).to_list(200)

    return {
        "total_cost": round(total_cost, 2),
        "days": days,
        "by_platform": [{"platform": r["_id"], "cost": round(r["cost"], 2)} for r in by_platform],
        "by_category": [{"category": r["_id"], "cost": round(r["cost"], 2)} for r in by_category],
        "by_service": [{"service": r["_id"], "cost": round(r["cost"], 2)} for r in by_service],
        "daily_trend": [{"date": r["_id"], "cost": round(r["cost"], 2)} for r in daily_trend],
        "top_resources": [
            {
                "platform": r["_id"]["platform"],
                "resource": r["_id"]["resource"],
                "cost": round(r["cost"], 2),
                "usage": round(r["usage"], 2),
            }
            for r in top_resources
        ],
        "by_account": [
            {
                "platform": r["_id"]["platform"],
                "connection_id": r["_id"].get("connection_id"),
                "account_name": r["_id"]["account_name"],
                "account_id": r.get("account_id", ""),
                "cost": round(r["cost"], 2),
            }
            for r in by_account
        ],
    }
