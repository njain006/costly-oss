from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.database import db
from app.deps import get_current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SlackWebhookUpdate(BaseModel):
    webhook_url: str


@router.put("/slack")
async def update_slack_webhook(body: SlackWebhookUpdate, user_id: str = Depends(get_current_user)):
    """Store a Slack webhook URL on the user document."""
    if not body.webhook_url.startswith("https://hooks.slack.com/"):
        raise HTTPException(400, "Invalid Slack webhook URL")
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"slack_webhook_url": body.webhook_url}},
    )
    return {"message": "Slack webhook configured"}


@router.get("/slack")
async def get_slack_settings(user_id: str = Depends(get_current_user)):
    """Check if Slack webhook is configured."""
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(401, "User not found")
    configured = bool(user.get("slack_webhook_url"))
    return {"configured": configured}


@router.delete("/slack")
async def remove_slack_webhook(user_id: str = Depends(get_current_user)):
    """Remove the Slack webhook URL."""
    await db.users.update_one(
        {"user_id": user_id},
        {"$unset": {"slack_webhook_url": ""}},
    )
    return {"message": "Slack webhook removed"}
