from pydantic import BaseModel
from typing import Optional


class TeamCreate(BaseModel):
    name: str
    description: str = ""
    members: list[str] = []  # user emails


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamMemberAdd(BaseModel):
    email: str
    role: str = "member"  # "admin" or "member"


class BudgetCreate(BaseModel):
    monthly_limit: float
    alert_threshold: float = 0.8  # alert at 80% of budget
    platforms: list[str] = []  # empty = all platforms
