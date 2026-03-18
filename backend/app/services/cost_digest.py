"""Daily cost digest — generates a markdown summary of recent spending for each user."""

from datetime import datetime, timedelta

from app.database import db


async def generate_daily_digest(user_id: str) -> str:
    """Generate a daily cost digest for a user.

    Compares last 24h spend to the previous 24h, highlights top movers
    and anomalies, and returns formatted markdown.
    """
    now = datetime.utcnow()
    today_start = (now - timedelta(hours=24)).strftime("%Y-%m-%d")
    yesterday_start = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
    today_end = now.strftime("%Y-%m-%d")

    # Last 24h costs by platform
    current_costs = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": today_start, "$lte": today_end}}},
        {"$group": {
            "_id": "$platform",
            "cost": {"$sum": "$cost_usd"},
        }},
        {"$sort": {"cost": -1}},
    ]).to_list(50)

    # Previous 24h costs by platform
    prev_costs = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": yesterday_start, "$lt": today_start}}},
        {"$group": {
            "_id": "$platform",
            "cost": {"$sum": "$cost_usd"},
        }},
    ]).to_list(50)

    prev_map = {r["_id"]: r["cost"] for r in prev_costs}

    total_current = sum(r["cost"] for r in current_costs)
    total_prev = sum(prev_map.values())

    # By-service breakdown for current period
    by_service = await db.unified_costs.aggregate([
        {"$match": {"user_id": user_id, "date": {"$gte": today_start, "$lte": today_end}}},
        {"$group": {"_id": "$service", "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"cost": -1}},
        {"$limit": 10},
    ]).to_list(10)

    # Recent anomalies (last 24h)
    anomalies = await db.anomalies.find(
        {"user_id": user_id, "date": {"$gte": today_start}},
    ).sort("date", -1).to_list(10)

    # Build markdown
    lines = ["## Daily Cost Digest", ""]

    # Total spend
    change_pct = ((total_current - total_prev) / total_prev * 100) if total_prev > 0 else 0
    direction = "up" if change_pct > 0 else "down" if change_pct < 0 else "flat"
    lines.append(f"**Total spend (last 24h):** ${total_current:,.2f}")
    if total_prev > 0:
        lines.append(
            f"**vs previous 24h:** ${total_prev:,.2f} ({direction} {abs(change_pct):.1f}%)"
        )
    lines.append("")

    # Platform breakdown
    if current_costs:
        lines.append("### By Platform")
        lines.append("| Platform | Cost | Change |")
        lines.append("|----------|------|--------|")
        for r in current_costs:
            platform = r["_id"]
            cost = r["cost"]
            prev = prev_map.get(platform, 0)
            if prev > 0:
                pct = (cost - prev) / prev * 100
                change_str = f"{'+'if pct>0 else ''}{pct:.1f}%"
            else:
                change_str = "new"
            lines.append(f"| {platform} | ${cost:,.2f} | {change_str} |")
        lines.append("")

    # Top services
    if by_service:
        lines.append("### Top Services")
        for r in by_service[:5]:
            lines.append(f"- **{r['_id']}**: ${r['cost']:,.2f}")
        lines.append("")

    # Biggest increases
    increases = []
    for r in current_costs:
        platform = r["_id"]
        prev = prev_map.get(platform, 0)
        if prev > 0:
            delta = r["cost"] - prev
            pct = delta / prev * 100
            if pct > 10:  # Only flag >10% increases
                increases.append((platform, delta, pct))
    increases.sort(key=lambda x: -x[1])

    if increases:
        lines.append("### Biggest Increases")
        for platform, delta, pct in increases[:5]:
            lines.append(f"- **{platform}**: +${delta:,.2f} (+{pct:.1f}%)")
        lines.append("")

    # Anomalies
    if anomalies:
        lines.append("### Anomalies Detected")
        for a in anomalies[:5]:
            severity = a.get("severity", "medium")
            scope = a.get("scope", "total")
            platform = a.get("platform", "unknown")
            lines.append(
                f"- [{severity.upper()}] {platform}/{scope}: "
                f"${a.get('actual_cost', 0):,.2f} vs ${a.get('baseline_cost', 0):,.2f} baseline"
            )
        lines.append("")

    if not current_costs:
        lines.append("*No cost data recorded in the last 24 hours.*")

    return "\n".join(lines)


async def generate_and_store_all_digests():
    """Generate digests for all users with connections and store them."""
    user_ids = await db.platform_connections.distinct("user_id")
    # Also include users with snowflake connections
    sf_user_ids = await db.snowflake_connections.distinct("user_id")
    all_user_ids = list(set(user_ids + sf_user_ids))

    now = datetime.utcnow()
    count = 0

    for user_id in all_user_ids:
        try:
            digest = await generate_daily_digest(user_id)
            await db.digests.update_one(
                {"user_id": user_id, "date": now.strftime("%Y-%m-%d")},
                {"$set": {
                    "user_id": user_id,
                    "date": now.strftime("%Y-%m-%d"),
                    "content": digest,
                    "generated_at": now.isoformat(),
                }},
                upsert=True,
            )
            count += 1
        except Exception as e:
            print(f"[DIGEST] Error generating digest for {user_id}: {e}")

    print(f"[DIGEST] Generated {count} digests for {len(all_user_ids)} users")
