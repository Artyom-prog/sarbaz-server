from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from app.db import get_db
from app.routes.auth import get_current_user
from app.schemas.profile import ProfileResponse, PremiumInfo, AIStats
from app.services.ai_profile import get_ai_stats
from app.models import UserSarbaz

router = APIRouter(prefix="/api", tags=["Profile"])


@router.get("/profile", response_model=ProfileResponse)
def get_profile(
    user: UserSarbaz = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Профиль текущего пользователя Sarbaz.
    """

    # ======================================================
    # 1. FAST PREMIUM SYNC (защита от просроченного premium)
    # ======================================================

    if user.premium_until and user.premium_until <= datetime.utcnow():
        user.premium_until = None
        db.commit()
        db.refresh(user)

    # ======================================================
    # 2. PREMIUM
    # ======================================================

    premium = PremiumInfo(
        is_premium=user.is_premium,
        premium_until=user.premium_until,
        days_left=user.premium_days_left,
    )

    # ======================================================
    # 3. AI
    # ======================================================

    ai_stats_raw = get_ai_stats(db, user)
    ai = AIStats(**ai_stats_raw)

    # ======================================================
    # 4. RESPONSE
    # ======================================================

    return ProfileResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        avatar_url=user.avatar_url,
        premium=premium,
        ai=ai,
    )