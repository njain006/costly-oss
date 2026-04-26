"""Multi-platform demo data generators.

Generates realistic fake cost data across AWS, dbt Cloud, AI APIs,
and Snowflake so demo users can experience the full platform view.
"""

import random
from datetime import datetime, timedelta


def _date_range(days: int) -> list[str]:
    today = datetime.utcnow().date()
    return [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def generate_demo_platform_connections() -> list[dict]:
    """Return a list of "connected" platforms for the demo /platforms page.

    Shape matches the real ``GET /api/platforms`` endpoint exactly
    (``id``, ``platform``, ``name``, ``created_at``, ``last_synced``,
    ``pricing_overrides``) so the connected-badge UI renders correctly.
    """
    now = datetime.utcnow()
    now_iso = now.isoformat()
    # Use deterministic-looking ids and a small spread of sync timestamps
    # so the page doesn't look like everything synced a millisecond ago.
    def _synced(hours_ago: int) -> str:
        return (now - timedelta(hours=hours_ago)).isoformat()

    def _created(days_ago_: int) -> str:
        return (now - timedelta(days=days_ago_)).isoformat()

    return [
        {
            "id": "demo_conn_snowflake",
            "platform": "snowflake",
            "name": "Production Snowflake",
            "created_at": _created(86),
            "last_synced": _synced(1),
            "pricing_overrides": {"credit_price": 2.85},
        },
        {
            "id": "demo_conn_aws",
            "platform": "aws",
            "name": "AWS Data Platform",
            "created_at": _created(74),
            "last_synced": _synced(2),
            "pricing_overrides": {"edp_discount_pct": 8},
        },
        {
            "id": "demo_conn_dbt",
            "platform": "dbt_cloud",
            "name": "dbt Cloud — Production",
            "created_at": _created(54),
            "last_synced": _synced(3),
            "pricing_overrides": None,
        },
        {
            "id": "demo_conn_openai",
            "platform": "openai",
            "name": "OpenAI API",
            "created_at": _created(42),
            "last_synced": _synced(2),
            "pricing_overrides": None,
        },
        {
            "id": "demo_conn_anthropic",
            "platform": "anthropic",
            "name": "Anthropic API",
            "created_at": _created(38),
            "last_synced": _synced(4),
            "pricing_overrides": None,
        },
        {
            "id": "demo_conn_gemini",
            "platform": "gemini",
            "name": "Gemini (Vertex AI)",
            "created_at": _created(21),
            "last_synced": _synced(5),
            "pricing_overrides": None,
        },
        {
            "id": "demo_conn_github",
            "platform": "github",
            "name": "GitHub Actions — costly-oss",
            "created_at": _created(18),
            "last_synced": _synced(6),
            "pricing_overrides": None,
        },
    ]


def generate_demo_unified_costs(days: int = 30) -> dict:
    dates = _date_range(days)
    random.seed(42)

    # --- Snowflake costs ---
    sf_daily = []
    for d in dates:
        base = 155 + random.gauss(0, 15)
        # Spike days
        if d.endswith("-18"):
            base *= 2.8
        if d.endswith("01") and "-03-" in d:
            base *= 1.9
        sf_daily.append({"date": d, "platform": "snowflake", "service": "snowflake", "cost": round(max(base, 40), 2)})

    # --- AWS S3 ---
    s3_daily = [{"date": d, "platform": "aws", "service": "aws_s3", "cost": round(12 + random.gauss(0, 1.5), 2)} for d in dates]

    # --- AWS Redshift ---
    redshift_daily = [{"date": d, "platform": "aws", "service": "aws_redshift", "cost": round(45 + random.gauss(0, 5), 2)} for d in dates]

    # --- AWS MWAA (Airflow) ---
    airflow_daily = [{"date": d, "platform": "aws", "service": "aws_mwaa", "cost": round(8.5 + random.gauss(0, 1), 2)} for d in dates]

    # --- AWS Glue ---
    glue_daily = [{"date": d, "platform": "aws", "service": "aws_glue", "cost": round(6 + random.gauss(0, 2), 2)} for d in dates]

    # --- AWS SQS ---
    sqs_daily = [{"date": d, "platform": "aws", "service": "aws_sqs", "cost": round(1.2 + random.gauss(0, 0.3), 2)} for d in dates]

    # --- AWS Lambda ---
    lambda_daily = [{"date": d, "platform": "aws", "service": "aws_lambda", "cost": round(3.5 + random.gauss(0, 0.8), 2)} for d in dates]

    # --- dbt Cloud ---
    dbt_daily = [{"date": d, "platform": "dbt_cloud", "service": "dbt_cloud", "cost": round(4.5 + random.gauss(0, 1.5), 2)} for d in dates]

    # --- AI API tokens ---
    ai_daily = []
    for d in dates:
        gpt4o_cost = round(18 + random.gauss(0, 5), 2)
        gpt4o_mini_cost = round(2.5 + random.gauss(0, 0.8), 2)
        o1_cost = round(8 + random.gauss(0, 3), 2)
        ai_daily.append({"date": d, "platform": "openai", "service": "openai", "resource": "gpt-4o", "cost": max(gpt4o_cost, 1), "tokens": int(gpt4o_cost / 2.5 * 1_000_000)})
        ai_daily.append({"date": d, "platform": "openai", "service": "openai", "resource": "gpt-4o-mini", "cost": max(gpt4o_mini_cost, 0.2), "tokens": int(gpt4o_mini_cost / 0.15 * 1_000_000)})
        ai_daily.append({"date": d, "platform": "openai", "service": "openai", "resource": "o1", "cost": max(o1_cost, 1), "tokens": int(o1_cost / 15 * 1_000_000)})

    # Aggregate all records
    all_records = sf_daily + s3_daily + redshift_daily + airflow_daily + glue_daily + sqs_daily + lambda_daily + dbt_daily + ai_daily

    # Total cost
    total_cost = round(sum(r["cost"] for r in all_records), 2)

    # By platform
    platform_totals = {}
    for r in all_records:
        platform_totals[r["platform"]] = platform_totals.get(r["platform"], 0) + r["cost"]
    by_platform = sorted(
        [{"platform": k, "cost": round(v, 2)} for k, v in platform_totals.items()],
        key=lambda x: -x["cost"],
    )

    # By category
    category_map = {
        "snowflake": "compute",
        "aws_s3": "storage",
        "aws_redshift": "compute",
        "aws_mwaa": "orchestration",
        "aws_glue": "transformation",
        "aws_sqs": "networking",
        "aws_lambda": "compute",
        "dbt_cloud": "transformation",
        "openai": "ai_inference",
    }
    category_totals = {}
    for r in all_records:
        cat = category_map.get(r["service"], "compute")
        category_totals[cat] = category_totals.get(cat, 0) + r["cost"]
    by_category = sorted(
        [{"category": k, "cost": round(v, 2)} for k, v in category_totals.items()],
        key=lambda x: -x["cost"],
    )

    # By service
    service_totals = {}
    for r in all_records:
        service_totals[r["service"]] = service_totals.get(r["service"], 0) + r["cost"]
    by_service = sorted(
        [{"service": k, "cost": round(v, 2)} for k, v in service_totals.items()],
        key=lambda x: -x["cost"],
    )

    # Daily trend (aggregated across all platforms)
    daily_totals = {}
    for r in all_records:
        daily_totals[r["date"]] = daily_totals.get(r["date"], 0) + r["cost"]
    daily_trend = [{"date": d, "cost": round(daily_totals.get(d, 0), 2)} for d in dates]

    # Top resources
    top_resources = [
        {"platform": "snowflake", "resource": "COMPUTE_WH", "cost": round(total_cost * 0.18, 2), "usage": 631},
        {"platform": "snowflake", "resource": "ANALYTICS_WH", "cost": round(total_cost * 0.15, 2), "usage": 535},
        {"platform": "aws", "resource": "Amazon Redshift", "cost": round(sum(r["cost"] for r in redshift_daily), 2), "usage": days * 24},
        {"platform": "openai", "resource": "gpt-4o", "cost": round(sum(r["cost"] for r in ai_daily if r.get("resource") == "gpt-4o"), 2), "usage": sum(r.get("tokens", 0) for r in ai_daily if r.get("resource") == "gpt-4o")},
        {"platform": "aws", "resource": "Amazon S3", "cost": round(sum(r["cost"] for r in s3_daily), 2), "usage": 1100},
        {"platform": "snowflake", "resource": "ETL_WH", "cost": round(total_cost * 0.07, 2), "usage": 248},
        {"platform": "openai", "resource": "o1", "cost": round(sum(r["cost"] for r in ai_daily if r.get("resource") == "o1"), 2), "usage": sum(r.get("tokens", 0) for r in ai_daily if r.get("resource") == "o1")},
        {"platform": "aws", "resource": "AWS MWAA (Airflow)", "cost": round(sum(r["cost"] for r in airflow_daily), 2), "usage": days * 48},
        {"platform": "dbt_cloud", "resource": "nightly_transform", "cost": round(sum(r["cost"] for r in dbt_daily) * 0.6, 2), "usage": days * 45},
        {"platform": "aws", "resource": "AWS Glue", "cost": round(sum(r["cost"] for r in glue_daily), 2), "usage": days * 12},
    ]

    return {
        "total_cost": total_cost,
        "days": days,
        "by_platform": by_platform,
        "by_category": by_category,
        "by_service": by_service,
        "daily_trend": daily_trend,
        "top_resources": sorted(top_resources, key=lambda x: -x["cost"]),
    }
