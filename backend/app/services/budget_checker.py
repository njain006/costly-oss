"""Budget checker — runs on a schedule to check team budgets against current spend."""

from datetime import datetime

from app.database import db
from app.services.slack import send_budget_alert


async def check_all_budgets():
    """Run by scheduler. For each team with a budget, check current month spend vs limit."""
    print(f"[BUDGET CHECKER] Running at {datetime.utcnow().isoformat()}")
    try:
        # Find all teams that have a budget configured
        teams = await db.teams.find(
            {"budget.monthly_limit": {"$gt": 0}}
        ).to_list(1000)

        if not teams:
            return

        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        for team in teams:
            budget = team.get("budget", {})
            monthly_limit = budget.get("monthly_limit", 0)
            alert_threshold = budget.get("alert_threshold", 0.8)
            budget_platforms = budget.get("platforms", [])

            # Get all member user_ids for this team
            member_emails = [m["email"] for m in team.get("members", [])]
            if not member_emails:
                continue

            users = await db.users.find(
                {"email": {"$in": member_emails}}
            ).to_list(1000)
            user_ids = [u["user_id"] for u in users]
            if not user_ids:
                continue

            # Build query for unified_costs
            cost_query = {
                "user_id": {"$in": user_ids},
                "date": {"$gte": month_start.isoformat()},
            }
            if budget_platforms:
                cost_query["platform"] = {"$in": budget_platforms}

            # Aggregate current month spend
            pipeline = [
                {"$match": cost_query},
                {"$group": {"_id": None, "total": {"$sum": "$cost"}}},
            ]
            result = await db.unified_costs.aggregate(pipeline).to_list(1)
            current_spend = result[0]["total"] if result else 0.0

            # Check if we should alert
            if current_spend >= monthly_limit * alert_threshold:
                # Check if we already sent an alert this hour to avoid spam
                last_alert = await db.budget_alerts.find_one(
                    {
                        "team_id": team["team_id"],
                        "month": month_start.isoformat(),
                    },
                    sort=[("sent_at", -1)],
                )
                if last_alert:
                    from datetime import timedelta
                    last_sent = datetime.fromisoformat(last_alert["sent_at"])
                    if (now - last_sent) < timedelta(hours=6):
                        continue

                # Send Slack alert if webhook configured
                owner = await db.users.find_one({"user_id": team["owner_id"]})
                webhook_url = owner.get("slack_webhook_url") if owner else None
                if webhook_url:
                    await send_budget_alert(
                        webhook_url, team["name"], current_spend, monthly_limit
                    )

                # Record alert
                await db.budget_alerts.insert_one({
                    "team_id": team["team_id"],
                    "month": month_start.isoformat(),
                    "current_spend": current_spend,
                    "monthly_limit": monthly_limit,
                    "sent_at": now.isoformat(),
                })

                print(
                    f"[BUDGET CHECKER] Alert for team '{team['name']}': "
                    f"${current_spend:,.2f} / ${monthly_limit:,.2f}"
                )

    except Exception as e:
        print(f"[BUDGET CHECKER] Error: {e}")
