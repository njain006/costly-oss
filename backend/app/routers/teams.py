import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends

from app.database import db
from app.deps import get_current_user
from app.models.team import TeamCreate, TeamUpdate, TeamMemberAdd, BudgetCreate

router = APIRouter(prefix="/api/teams", tags=["teams"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_team_or_404(team_id: str, user_id: str):
    """Fetch a team and verify the user is a member."""
    team = await db.teams.find_one({"team_id": team_id})
    if not team:
        raise HTTPException(404, "Team not found")
    member_emails = [m["email"] for m in team.get("members", [])]
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(401, "User not found")
    if team["owner_id"] != user_id and user.get("email") not in member_emails:
        raise HTTPException(403, "Not a member of this team")
    return team, user


async def _is_team_admin(team: dict, user_id: str, user_email: str) -> bool:
    """Check if user is team owner or has admin role."""
    if team["owner_id"] == user_id:
        return True
    for m in team.get("members", []):
        if m["email"] == user_email and m.get("role") == "admin":
            return True
    return False


def _team_response(team: dict) -> dict:
    return {
        "id": team["team_id"],
        "name": team["name"],
        "description": team.get("description", ""),
        "members": team.get("members", []),
        "budget": team.get("budget"),
        "created_at": team["created_at"],
        "owner_id": team["owner_id"],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post("")
async def create_team(body: TeamCreate, user_id: str = Depends(get_current_user)):
    """Create a new team. The creating user becomes the owner."""
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(401, "User not found")

    team_id = f"team_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    members = [{"email": user["email"], "role": "admin", "joined_at": now}]
    for email in body.members:
        if email != user["email"]:
            members.append({"email": email, "role": "member", "joined_at": now})

    doc = {
        "team_id": team_id,
        "owner_id": user_id,
        "name": body.name,
        "description": body.description,
        "members": members,
        "budget": None,
        "created_at": now,
    }
    await db.teams.insert_one(doc)
    return _team_response(doc)


@router.get("")
async def list_teams(user_id: str = Depends(get_current_user)):
    """List teams the current user belongs to."""
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(401, "User not found")
    email = user["email"]
    teams = await db.teams.find({
        "$or": [
            {"owner_id": user_id},
            {"members.email": email},
        ]
    }).to_list(100)
    return [_team_response(t) for t in teams]


@router.get("/{team_id}")
async def get_team(team_id: str, user_id: str = Depends(get_current_user)):
    """Get team detail with members and current-month cost summary."""
    team, user = await _get_team_or_404(team_id, user_id)

    # Compute current month cost summary
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    member_emails = [m["email"] for m in team.get("members", [])]
    member_users = await db.users.find(
        {"email": {"$in": member_emails}}
    ).to_list(1000)
    member_user_ids = [u["user_id"] for u in member_users]

    cost_query = {
        "user_id": {"$in": member_user_ids},
        "date": {"$gte": month_start.isoformat()},
    }
    pipeline = [
        {"$match": cost_query},
        {"$group": {
            "_id": "$platform",
            "total": {"$sum": "$cost_usd"},
        }},
    ]
    cost_agg = await db.unified_costs.aggregate(pipeline).to_list(100)
    cost_by_platform = {r["_id"]: round(r["total"], 2) for r in cost_agg}
    total_spend = sum(cost_by_platform.values())

    resp = _team_response(team)
    resp["cost_summary"] = {
        "period": f"{month_start.strftime('%Y-%m')}-01 to {now.strftime('%Y-%m-%d')}",
        "total_spend": round(total_spend, 2),
        "by_platform": cost_by_platform,
    }
    return resp


@router.put("/{team_id}")
async def update_team(team_id: str, body: TeamUpdate, user_id: str = Depends(get_current_user)):
    team, user = await _get_team_or_404(team_id, user_id)
    if not await _is_team_admin(team, user_id, user.get("email", "")):
        raise HTTPException(403, "Admin access required")

    update_doc = {}
    if body.name is not None:
        update_doc["name"] = body.name
    if body.description is not None:
        update_doc["description"] = body.description
    if not update_doc:
        raise HTTPException(400, "Nothing to update")

    await db.teams.update_one({"team_id": team_id}, {"$set": update_doc})
    return {"message": "Team updated"}


@router.delete("/{team_id}")
async def delete_team(team_id: str, user_id: str = Depends(get_current_user)):
    team, user = await _get_team_or_404(team_id, user_id)
    if team["owner_id"] != user_id:
        raise HTTPException(403, "Only the team owner can delete the team")
    await db.teams.delete_one({"team_id": team_id})
    await db.budget_alerts.delete_many({"team_id": team_id})
    return {"message": "Team deleted"}


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@router.post("/{team_id}/members")
async def add_member(team_id: str, body: TeamMemberAdd, user_id: str = Depends(get_current_user)):
    team, user = await _get_team_or_404(team_id, user_id)
    if not await _is_team_admin(team, user_id, user.get("email", "")):
        raise HTTPException(403, "Admin access required")

    # Check if already a member
    existing_emails = [m["email"] for m in team.get("members", [])]
    if body.email in existing_emails:
        raise HTTPException(400, "User is already a member")

    member = {
        "email": body.email,
        "role": body.role if body.role in ("admin", "member") else "member",
        "joined_at": datetime.utcnow().isoformat(),
    }
    await db.teams.update_one(
        {"team_id": team_id},
        {"$push": {"members": member}},
    )
    return {"message": f"Added {body.email} to team", "member": member}


@router.delete("/{team_id}/members/{email}")
async def remove_member(team_id: str, email: str, user_id: str = Depends(get_current_user)):
    team, user = await _get_team_or_404(team_id, user_id)
    if not await _is_team_admin(team, user_id, user.get("email", "")):
        raise HTTPException(403, "Admin access required")

    # Cannot remove the owner
    owner = await db.users.find_one({"user_id": team["owner_id"]})
    if owner and owner.get("email") == email:
        raise HTTPException(400, "Cannot remove the team owner")

    result = await db.teams.update_one(
        {"team_id": team_id},
        {"$pull": {"members": {"email": email}}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Member not found")
    return {"message": f"Removed {email} from team"}


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@router.post("/{team_id}/budget")
async def set_budget(team_id: str, body: BudgetCreate, user_id: str = Depends(get_current_user)):
    team, user = await _get_team_or_404(team_id, user_id)
    if not await _is_team_admin(team, user_id, user.get("email", "")):
        raise HTTPException(403, "Admin access required")

    budget = {
        "monthly_limit": body.monthly_limit,
        "alert_threshold": body.alert_threshold,
        "platforms": body.platforms,
    }
    await db.teams.update_one({"team_id": team_id}, {"$set": {"budget": budget}})
    return {"message": "Budget set", "budget": budget}


@router.get("/{team_id}/budget")
async def get_budget_status(team_id: str, user_id: str = Depends(get_current_user)):
    team, user = await _get_team_or_404(team_id, user_id)
    budget = team.get("budget")
    if not budget or not budget.get("monthly_limit"):
        return {"budget": None, "current_spend": 0, "status": "no_budget"}

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    member_emails = [m["email"] for m in team.get("members", [])]
    member_users = await db.users.find(
        {"email": {"$in": member_emails}}
    ).to_list(1000)
    member_user_ids = [u["user_id"] for u in member_users]

    cost_query = {
        "user_id": {"$in": member_user_ids},
        "date": {"$gte": month_start.isoformat()},
    }
    if budget.get("platforms"):
        cost_query["platform"] = {"$in": budget["platforms"]}

    pipeline = [
        {"$match": cost_query},
        {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
    ]
    result = await db.unified_costs.aggregate(pipeline).to_list(1)
    current_spend = result[0]["total"] if result else 0.0

    monthly_limit = budget["monthly_limit"]
    pct = (current_spend / monthly_limit * 100) if monthly_limit > 0 else 0

    if pct >= 100:
        status = "exceeded"
    elif pct >= budget.get("alert_threshold", 0.8) * 100:
        status = "warning"
    else:
        status = "ok"

    return {
        "budget": budget,
        "current_spend": round(current_spend, 2),
        "percentage": round(pct, 1),
        "status": status,
    }


# ---------------------------------------------------------------------------
# Cost breakdown
# ---------------------------------------------------------------------------

@router.get("/{team_id}/costs")
async def get_team_costs(team_id: str, days: int = 30, user_id: str = Depends(get_current_user)):
    """Get team cost breakdown from unified_costs filtered by team members."""
    team, user = await _get_team_or_404(team_id, user_id)

    from datetime import timedelta
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).isoformat()

    member_emails = [m["email"] for m in team.get("members", [])]
    member_users = await db.users.find(
        {"email": {"$in": member_emails}}
    ).to_list(1000)
    member_user_ids = [u["user_id"] for u in member_users]

    cost_query = {
        "user_id": {"$in": member_user_ids},
        "date": {"$gte": start},
    }

    # By platform
    by_platform = await db.unified_costs.aggregate([
        {"$match": cost_query},
        {"$group": {"_id": "$platform", "total": {"$sum": "$cost_usd"}}},
        {"$sort": {"total": -1}},
    ]).to_list(100)

    # By date (daily totals)
    by_date = await db.unified_costs.aggregate([
        {"$match": cost_query},
        {"$group": {"_id": "$date", "total": {"$sum": "$cost_usd"}}},
        {"$sort": {"_id": 1}},
    ]).to_list(1000)

    # By service
    by_service = await db.unified_costs.aggregate([
        {"$match": cost_query},
        {"$group": {"_id": {"platform": "$platform", "service": "$service"}, "total": {"$sum": "$cost_usd"}}},
        {"$sort": {"total": -1}},
        {"$limit": 20},
    ]).to_list(20)

    total = sum(r["total"] for r in by_platform)

    return {
        "days": days,
        "total": round(total, 2),
        "by_platform": [{"platform": r["_id"], "cost": round(r["total"], 2)} for r in by_platform],
        "by_date": [{"date": r["_id"], "cost": round(r["total"], 2)} for r in by_date],
        "by_service": [
            {
                "platform": r["_id"]["platform"],
                "service": r["_id"]["service"],
                "cost": round(r["total"], 2),
            }
            for r in by_service
        ],
    }
