"""Slack webhook integration for notifications."""

import httpx


async def send_slack_notification(webhook_url: str, message: str, blocks: list = None):
    """Send a message to a Slack channel via incoming webhook."""
    payload = {"text": message}
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
    except Exception as e:
        print(f"[SLACK] Failed to send notification: {e}")


async def send_budget_alert(webhook_url: str, team_name: str, current_spend: float, budget_limit: float):
    """Send a budget alert with formatted Slack blocks."""
    pct = (current_spend / budget_limit * 100) if budget_limit > 0 else 0
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":warning: Budget Alert"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Team:*\n{team_name}"},
                {"type": "mrkdwn", "text": f"*Usage:*\n{pct:.1f}%"},
                {"type": "mrkdwn", "text": f"*Current Spend:*\n${current_spend:,.2f}"},
                {"type": "mrkdwn", "text": f"*Budget Limit:*\n${budget_limit:,.2f}"},
            ]
        }
    ]
    message = f"Budget alert for team '{team_name}': ${current_spend:,.2f} / ${budget_limit:,.2f} ({pct:.1f}%)"
    await send_slack_notification(webhook_url, message, blocks)


async def send_anomaly_alert(webhook_url: str, anomaly: dict):
    """Send an anomaly notification."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":rotating_light: Cost Anomaly Detected"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Type:*\n{anomaly.get('type', 'unknown')}"},
                {"type": "mrkdwn", "text": f"*Platform:*\n{anomaly.get('platform', 'unknown')}"},
                {"type": "mrkdwn", "text": f"*Resource:*\n{anomaly.get('resource', 'N/A')}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{anomaly.get('severity', 'unknown')}"},
            ]
        }
    ]
    message = f"Cost anomaly detected: {anomaly.get('type', 'unknown')} on {anomaly.get('platform', 'unknown')}"
    await send_slack_notification(webhook_url, message, blocks)


async def send_daily_digest(webhook_url: str, digest: str):
    """Send the daily cost digest."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":bar_chart: Daily Cost Digest"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": digest}
        }
    ]
    await send_slack_notification(webhook_url, digest, blocks)
