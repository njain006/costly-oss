import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends

from app.database import db
from app.deps import get_current_user
from app.models.alert import AlertCreate, AlertUpdate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
async def get_alerts(user_id: str = Depends(get_current_user)):
    alerts = await db.alerts.find({"user_id": user_id}).to_list(100)
    return [
        {
            "id": a["alert_id"],
            "name": a["name"],
            "metric": a["metric"],
            "threshold": a["threshold"],
            "channel": a["channel"],
            "webhook_url": a.get("webhook_url"),
            "enabled": a["enabled"],
            "created_at": a["created_at"],
            "last_fired_at": a.get("last_fired_at"),
            "last_value": a.get("last_value"),
        }
        for a in alerts
    ]


@router.post("")
async def create_alert(alert: AlertCreate, user_id: str = Depends(get_current_user)):
    alert_id = f"alert_{uuid.uuid4().hex[:12]}"
    doc = {
        "alert_id": alert_id,
        "user_id": user_id,
        "name": alert.name,
        "metric": alert.metric,
        "threshold": alert.threshold,
        "channel": alert.channel,
        "webhook_url": alert.webhook_url,
        "connection_id": alert.connection_id,
        "enabled": True,
        "created_at": datetime.utcnow().isoformat(),
    }
    await db.alerts.insert_one(doc)
    return {
        "id": alert_id, "name": alert.name, "metric": alert.metric,
        "threshold": alert.threshold, "channel": alert.channel,
        "webhook_url": alert.webhook_url, "enabled": True, "created_at": doc["created_at"],
    }


@router.patch("/{alert_id}")
async def update_alert(alert_id: str, update: AlertUpdate, user_id: str = Depends(get_current_user)):
    update_doc = {}
    if update.enabled is not None:
        update_doc["enabled"] = update.enabled
    if not update_doc:
        raise HTTPException(400, "Nothing to update")
    result = await db.alerts.update_one(
        {"alert_id": alert_id, "user_id": user_id},
        {"$set": update_doc},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Alert not found")
    return {"message": "Updated"}


@router.delete("/{alert_id}")
async def delete_alert(alert_id: str, user_id: str = Depends(get_current_user)):
    result = await db.alerts.delete_one({"alert_id": alert_id, "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Alert not found")
    return {"message": "Alert deleted"}
