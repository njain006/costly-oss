"""Generic platform view data endpoint.

Returns { kpis, charts, table } for any platform/view combo,
querying the unified_costs MongoDB collection.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException

from app.deps import get_current_user
from app.database import db

router = APIRouter(prefix="/api/platforms", tags=["platform-views"])


@router.get("/{platform_key}/{view_slug}")
async def get_platform_view_data(
    platform_key: str,
    view_slug: str,
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(get_current_user),
):
    """Fetch view-specific data for a platform from unified_costs."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Base match for this user + platform + date range
    match = {
        "user_id": user_id,
        "platform": platform_key,
        "date": {"$gte": since},
    }

    # Filter by service when viewing a specific sub-view (e.g. aws/s3, aws/redshift)
    if view_slug != "dashboard":
        service_key = f"{platform_key}_{view_slug}"
        match["service"] = {"$regex": f"^{service_key}", "$options": "i"}

    # Check if user has any data for this platform
    count = await db.unified_costs.count_documents(match)
    if count == 0:
        return {"kpis": {}, "charts": {}, "table": [], "demo": True}

    # Exclude inventory records from cost calculations
    cost_match = {**match, "metadata.type": {"$ne": "inventory"}}

    # Build KPIs
    kpi_pipeline = [
        {"$match": cost_match},
        {"$group": {
            "_id": None,
            "total_cost": {"$sum": "$cost_usd"},
            "total_records": {"$sum": 1},
            "total_usage": {"$sum": "$usage_quantity"},
            "unique_services": {"$addToSet": "$service"},
            "unique_resources": {"$addToSet": "$resource"},
            "unique_categories": {"$addToSet": "$category"},
        }},
    ]
    kpi_result = await db.unified_costs.aggregate(kpi_pipeline).to_list(1)
    kpi_raw = kpi_result[0] if kpi_result else {}

    total_cost = kpi_raw.get("total_cost", 0)
    kpis = {
        "total_cost": round(total_cost, 2),
        "daily_avg": round(total_cost / max(days, 1), 2),
        "service_count": len(kpi_raw.get("unique_services", [])),
        "resource_count": len(kpi_raw.get("unique_resources", [])),
        "total_usage": round(kpi_raw.get("total_usage", 0), 2),
        "total_records": kpi_raw.get("total_records", 0),
        # Platform-specific KPIs can be added via metadata aggregation
    }

    # Add platform-specific KPI enrichments
    kpis.update(await _platform_kpis(db, match, platform_key, total_cost, days))

    # Daily trend chart
    daily_pipeline = [
        {"$match": cost_match},
        {"$group": {
            "_id": "$date",
            "cost": {"$sum": "$cost_usd"},
        }},
        {"$sort": {"_id": 1}},
        {"$project": {"date": "$_id", "cost": {"$round": ["$cost", 2]}, "_id": 0}},
    ]
    daily_trend = await db.unified_costs.aggregate(daily_pipeline).to_list(400)

    # By-service breakdown (for pie chart)
    service_pipeline = [
        {"$match": cost_match},
        {"$group": {
            "_id": "$service",
            "cost": {"$sum": "$cost_usd"},
        }},
        {"$sort": {"cost": -1}},
        {"$limit": 10},
        {"$project": {"service": "$_id", "cost": {"$round": ["$cost", 2]}, "_id": 0}},
    ]
    by_service = await db.unified_costs.aggregate(service_pipeline).to_list(10)

    # By-resource (for horizontal bar / top items)
    resource_pipeline = [
        {"$match": cost_match},
        {"$group": {
            "_id": "$resource",
            "cost": {"$sum": "$cost_usd"},
            "usage": {"$sum": "$usage_quantity"},
            "unit": {"$first": "$usage_unit"},
        }},
        {"$sort": {"cost": -1}},
        {"$limit": 15},
        {"$project": {
            "name": "$_id", "cost": {"$round": ["$cost", 2]},
            "usage": {"$round": ["$usage", 2]}, "unit": 1, "_id": 0,
        }},
    ]
    by_resource = await db.unified_costs.aggregate(resource_pipeline).to_list(15)

    # By-category breakdown
    category_pipeline = [
        {"$match": cost_match},
        {"$group": {
            "_id": "$category",
            "cost": {"$sum": "$cost_usd"},
        }},
        {"$sort": {"cost": -1}},
        {"$project": {"category": "$_id", "cost": {"$round": ["$cost", 2]}, "_id": 0}},
    ]
    by_category = await db.unified_costs.aggregate(category_pipeline).to_list(20)

    # View-specific chart data
    extra_charts = await _view_charts(db, match, platform_key, view_slug)

    # Build charts dict — map generic keys that the frontend registry expects
    charts = {
        "daily_trend": daily_trend,
        "cost_trend": daily_trend,
        "by_service": by_service,
        "by_category": by_category,
        "top_resources": by_resource,
        # Alias common chart keys the registry might use
        "by_warehouse": by_resource,
        "by_cluster": by_resource,
        "by_model": by_service,
        "by_job": by_resource,
        "by_connector": by_service,
        "by_repo": by_resource,
        "by_project": by_resource,
        "by_dataset": by_resource,
        "top_warehouses": by_resource,
        "top_jobs": by_resource,
        **extra_charts,
    }

    # Table: view-specific or generic
    table = await _build_table(db, match, platform_key, view_slug)

    return {"kpis": kpis, "charts": charts, "table": table, "demo": False}


async def _platform_kpis(db, match: dict, platform: str, total_cost: float, days: int) -> dict:
    """Add platform-specific KPI fields."""
    extra: dict = {}

    if platform == "aws":
        extra["mom_change"] = 0
        # S3 inventory KPIs
        inv_match = {**match, "metadata.type": "inventory", "service": "aws_s3"}
        bucket_pipe = [
            {"$match": inv_match},
            {"$group": {
                "_id": None,
                "bucket_count": {"$sum": 1},
                "total_storage": {"$sum": "$metadata.size_bytes"},
                "total_objects": {"$sum": "$metadata.object_count"},
            }},
        ]
        inv_result = await db.unified_costs.aggregate(bucket_pipe).to_list(1)
        if inv_result:
            extra["bucket_count"] = inv_result[0]["bucket_count"]
            extra["total_storage"] = inv_result[0]["total_storage"]  # bytes
            extra["total_objects"] = inv_result[0]["total_objects"]

        # EC2 instance count
        ec2_match = {**match, "metadata.type": "inventory", "service": "aws_ec2"}
        ec2_count = await db.unified_costs.count_documents(ec2_match)
        extra["ec2_count"] = ec2_count

        # Lambda count
        lambda_match = {**match, "metadata.type": "inventory", "service": "aws_lambda"}
        lambda_count = await db.unified_costs.count_documents(lambda_match)
        extra["lambda_count"] = lambda_count

    elif platform in ("openai", "anthropic", "gemini"):
        # Token counts from usage_quantity where unit contains "tokens"
        token_match = {**match, "usage_unit": {"$regex": "token", "$options": "i"}}
        token_pipe = [
            {"$match": token_match},
            {"$group": {"_id": None, "total": {"$sum": "$usage_quantity"}}},
        ]
        result = await db.unified_costs.aggregate(token_pipe).to_list(1)
        extra["total_tokens"] = int(result[0]["total"]) if result else 0

        # Model count
        model_pipe = [
            {"$match": match},
            {"$group": {"_id": "$service"}},
            {"$count": "count"},
        ]
        result = await db.unified_costs.aggregate(model_pipe).to_list(1)
        extra["model_count"] = result[0]["count"] if result else 0

    return extra


async def _view_charts(db, match: dict, platform: str, view: str) -> dict:
    """Generate view-specific chart data beyond the generic ones."""
    charts: dict = {}

    if view == "usage" and platform in ("openai", "anthropic"):
        # Daily token breakdown
        pipe = [
            {"$match": {**match, "usage_unit": {"$regex": "token", "$options": "i"}}},
            {"$group": {
                "_id": "$date",
                "input": {"$sum": {"$cond": [
                    {"$regexMatch": {"input": "$service", "regex": "input|prompt"}},
                    "$usage_quantity", 0,
                ]}},
                "output": {"$sum": {"$cond": [
                    {"$regexMatch": {"input": "$service", "regex": "output|completion"}},
                    "$usage_quantity", 0,
                ]}},
                "tokens": {"$sum": "$usage_quantity"},
            }},
            {"$sort": {"_id": 1}},
            {"$project": {"date": "$_id", "input": 1, "output": 1, "tokens": 1, "_id": 0}},
        ]
        charts["daily_tokens"] = await db.unified_costs.aggregate(pipe).to_list(400)

    return charts


async def _build_table(db, match: dict, platform: str, view: str) -> list:
    """Build the table data, with special handling for inventory views."""

    # S3 inventory — show buckets with size, objects, region, created
    if platform == "aws" and view == "s3":
        inv_match = {**match, "metadata.type": "inventory"}
        inv_pipeline = [
            {"$match": inv_match},
            {"$sort": {"usage_quantity": -1}},
            {"$limit": 100},
            {"$project": {
                "_id": 0,
                "name": "$resource",
                "size_bytes": "$metadata.size_bytes",
                "size_mb": "$metadata.size_mb",
                "objects": "$metadata.object_count",
                "region": "$metadata.region",
                "created": "$metadata.created",
                "cost": {"$round": ["$cost_usd", 2]},
            }},
        ]
        rows = await db.unified_costs.aggregate(inv_pipeline).to_list(100)

        # Format size for display
        for row in rows:
            size_bytes = row.get("size_bytes", 0) or 0
            if size_bytes >= 1024 ** 3:
                row["size_display"] = f"{size_bytes / (1024 ** 3):.2f} GB"
            elif size_bytes >= 1024 ** 2:
                row["size_display"] = f"{size_bytes / (1024 ** 2):.2f} MB"
            elif size_bytes >= 1024:
                row["size_display"] = f"{size_bytes / 1024:.1f} KB"
            elif size_bytes > 0:
                row["size_display"] = f"{int(size_bytes)} B"
            else:
                row["size_display"] = "Empty"

            # Format created date
            created = row.get("created", "")
            if created and "T" in str(created):
                row["created"] = str(created).split("T")[0]

        return rows

    # AWS Dashboard — aggregated cost summary + resource inventory
    if platform == "aws" and view == "dashboard":
        # Cost summary aggregated by service
        cost_match = {**match, "metadata.type": {"$ne": "inventory"}}
        cost_pipe = [
            {"$match": cost_match},
            {"$group": {
                "_id": "$resource",
                "service": {"$first": "$service"},
                "cost": {"$sum": "$cost_usd"},
                "category": {"$first": "$category"},
            }},
            {"$sort": {"cost": -1}},
            {"$project": {"_id": 0, "name": "$_id", "service": 1, "cost": {"$round": ["$cost", 2]}, "category": 1, "type": {"$literal": "cost"}}},
        ]
        cost_rows = await db.unified_costs.aggregate(cost_pipe).to_list(50)

        # EC2 inventory
        ec2_match = {**match, "metadata.type": "inventory", "service": "aws_ec2"}
        ec2_pipe = [
            {"$match": ec2_match},
            {"$project": {
                "_id": 0, "name": "$resource",
                "detail": "$metadata.instance_type",
                "status": "$metadata.state",
                "type": {"$literal": "ec2"},
            }},
        ]
        ec2_rows = await db.unified_costs.aggregate(ec2_pipe).to_list(100)

        # S3 inventory (top 10 by size)
        s3_match = {**match, "metadata.type": "inventory", "service": "aws_s3"}
        s3_pipe = [
            {"$match": s3_match},
            {"$sort": {"metadata.size_bytes": -1}},
            {"$limit": 10},
            {"$project": {
                "_id": 0, "name": "$resource",
                "detail": {"$concat": [
                    {"$toString": {"$round": [{"$divide": [{"$ifNull": ["$metadata.size_bytes", 0]}, 1048576]}, 2]}},
                    " MB, ",
                    {"$toString": {"$ifNull": ["$metadata.object_count", 0]}},
                    " objects",
                ]},
                "status": "$metadata.region",
                "type": {"$literal": "s3"},
            }},
        ]
        s3_rows = await db.unified_costs.aggregate(s3_pipe).to_list(10)

        # Lambda inventory
        lam_match = {**match, "metadata.type": "inventory", "service": "aws_lambda"}
        lam_pipe = [
            {"$match": lam_match},
            {"$project": {
                "_id": 0, "name": "$resource",
                "detail": "$metadata.runtime",
                "status": {"$concat": [{"$toString": {"$ifNull": ["$metadata.memory_mb", 0]}}, " MB"]},
                "type": {"$literal": "lambda"},
            }},
        ]
        lam_rows = await db.unified_costs.aggregate(lam_pipe).to_list(100)

        return cost_rows + ec2_rows + s3_rows + lam_rows

    # EC2 inventory
    if platform == "aws" and view == "ec2":
        inv_match = {**match, "metadata.type": "inventory", "service": "aws_ec2"}
        inv_pipeline = [
            {"$match": inv_match},
            {"$project": {
                "_id": 0,
                "name": "$resource",
                "instance_type": "$metadata.instance_type",
                "state": "$metadata.state",
                "instance_id": "$metadata.instance_id",
                "cost": {"$round": ["$cost_usd", 2]},
            }},
        ]
        return await db.unified_costs.aggregate(inv_pipeline).to_list(100)

    # Default: generic table (aggregated by resource)
    cost_match = {**match, "metadata.type": {"$ne": "inventory"}}
    table_pipeline = [
        {"$match": cost_match},
        {"$group": {
            "_id": {"resource": "$resource", "service": "$service"},
            "cost": {"$sum": "$cost_usd"},
            "usage": {"$sum": "$usage_quantity"},
            "unit": {"$first": "$usage_unit"},
            "category": {"$first": "$category"},
        }},
        {"$sort": {"cost": -1}},
        {"$limit": 50},
        {"$project": {
            "_id": 0,
            "name": "$_id.resource",
            "service": "$_id.service",
            "cost": {"$round": ["$cost", 2]},
            "usage": {"$round": ["$usage", 2]},
            "unit": 1, "category": 1,
            "warehouse": "$_id.resource",
            "model": "$_id.service",
            "job": "$_id.resource",
            "connector": "$_id.service",
            "bucket": "$_id.resource",
        }},
    ]
    return await db.unified_costs.aggregate(table_pipeline).to_list(50)
