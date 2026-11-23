from datetime import datetime, timedelta

from app.database import db
from app.services.snowflake import sync_fetch_metric, build_sf_connection
from app.services.email import send_alert_email
from app.utils.helpers import run_in_thread


def _send_alert_slack(webhook_url: str, alert_name: str, metric: str, threshold: float, current_value: float):
    import httpx
    payload = {
        "text": (
            f":warning: *costly Alert: {alert_name}*\n"
            f"Metric `{metric}` has reached *{current_value:.2f}* "
            f"(threshold: {threshold:.2f})"
        )
    }
    try:
        httpx.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"[ALERT] Slack send failed for '{alert_name}': {e}")


async def evaluate_all_alerts():
    """Run every 15 minutes: check all enabled alerts against live Snowflake data."""
    print(f"[ALERT ENGINE] Running evaluation at {datetime.utcnow().isoformat()}")
    try:
        from app.deps import all_snowflake_sources
        conn_by_user: dict = {}
        for c in await all_snowflake_sources():
            conn_by_user.setdefault(c["user_id"], []).append(c)

        if not conn_by_user:
            return

        user_ids = list(conn_by_user.keys())
        alerts = await db.alerts.find({
            "user_id": {"$in": user_ids},
            "enabled": True,
        }).to_list(1000)

        now = datetime.utcnow()
        cooldown = timedelta(hours=1)

        for alert in alerts:
            user_id = alert["user_id"]
            conns = conn_by_user.get(user_id) or []
            # An alert can name one account; otherwise it watches every
            # Snowflake account the user connected and fires on the highest.
            if alert.get("connection_id"):
                conns = [c for c in conns if c.get("connection_id") == alert["connection_id"]]
            if not conns:
                continue

            last_fired = alert.get("last_fired_at")
            if last_fired:
                try:
                    last_fired_dt = datetime.fromisoformat(last_fired)
                    if now - last_fired_dt < cooldown:
                        continue
                except Exception:
                    pass

            values = []
            for conn_doc in conns:
                try:
                    v = await run_in_thread(sync_fetch_metric, conn_doc, alert["metric"])
                    values.append((float(v or 0), conn_doc.get("connection_name") or conn_doc.get("account", "")))
                except Exception as e:
                    print(f"[ALERT ENGINE] Failed to fetch metric '{alert['metric']}' for user {user_id}: {e}")
            if not values:
                continue
            current_value, account_label = max(values)

            if current_value >= alert["threshold"]:
                print(f"[ALERT ENGINE] FIRING: '{alert['name']}' - {alert['metric']} = {current_value} >= {alert['threshold']}")

                if alert["channel"] == "slack" and alert.get("webhook_url"):
                    _send_alert_slack(
                        alert["webhook_url"],
                        f"{alert['name']} ({account_label})" if len(values) > 1 else alert["name"],
                        alert["metric"],
                        alert["threshold"],
                        current_value,
                    )
                elif alert["channel"] == "email":
                    user = await db.users.find_one({"user_id": user_id})
                    if user and user.get("email"):
                        await run_in_thread(
                            send_alert_email,
                            user["email"],
                            alert["name"],
                            alert["metric"],
                            alert["threshold"],
                            current_value,
                        )

                await db.alerts.update_one(
                    {"alert_id": alert["alert_id"]},
                    {"$set": {"last_fired_at": now.isoformat(), "last_value": current_value}},
                )

    except Exception as e:
        print(f"[ALERT ENGINE] Error during evaluation: {e}")
