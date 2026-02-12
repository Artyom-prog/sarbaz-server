from datetime import date

from sqlalchemy.orm import Session

from app.models import AIUsage, UserSarbaz

FREE_LIMIT = 5


def get_ai_stats(db: Session, user: UserSarbaz):
    """
    Возвращает статистику использования AI за сегодня.
    """

    # Премиум → безлимит
    if user.is_premium:
        return {
            "used_today": 0,
            "limit": -1,          # -1 = безлимит
            "remaining": -1,
        }

    today = date.today()

    usage = (
        db.query(AIUsage)
        .filter(AIUsage.user_id == user.id, AIUsage.day == today)
        .first()
    )

    used = usage.count if usage else 0
    remaining = max(FREE_LIMIT - used, 0)

    return {
        "used_today": used,
        "limit": FREE_LIMIT,
        "remaining": remaining,
    }