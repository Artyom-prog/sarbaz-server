from pydantic import BaseModel
from datetime import datetime


class AIStats(BaseModel):
    used_today: int
    limit: int
    remaining: int


class PremiumInfo(BaseModel):
    is_premium: bool
    premium_until: datetime | None
    days_left: int


class ProfileResponse(BaseModel):
    id: int
    name: str | None
    email: str | None
    avatar_url: str | None

    premium: PremiumInfo
    ai: AIStats