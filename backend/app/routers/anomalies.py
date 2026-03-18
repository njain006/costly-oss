"""Anomaly detection API endpoints."""

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.services.anomaly_detector import (
    get_anomalies,
    acknowledge_anomaly,
    detect_anomalies_for_user,
)

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("")
async def list_anomalies(
    days: int = 30,
    unread: bool = False,
    user_id: str = Depends(get_current_user),
):
    """Get detected anomalies for the current user."""
    acknowledged = False if unread else None
    results = await get_anomalies(user_id, days=days, acknowledged=acknowledged)
    return {
        "anomalies": results,
        "count": len(results),
        "unacknowledged": sum(1 for r in results if not r.get("acknowledged")),
    }


@router.post("/{anomaly_id}/acknowledge")
async def ack_anomaly(anomaly_id: str, user_id: str = Depends(get_current_user)):
    """Mark an anomaly as acknowledged."""
    ok = await acknowledge_anomaly(user_id, anomaly_id)
    if not ok:
        return {"success": False, "message": "Anomaly not found"}
    return {"success": True}


@router.post("/detect")
async def trigger_detection(user_id: str = Depends(get_current_user)):
    """Manually trigger anomaly detection for the current user."""
    anomalies = await detect_anomalies_for_user(user_id)
    return {
        "anomalies": len(anomalies),
        "message": f"Detection complete. {len(anomalies)} anomalies found.",
    }
