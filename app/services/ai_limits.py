from datetime import date
from sqlalchemy.orm import Session
from app.models import AIUsage


FREE_LIMIT = 5


def check_and_increment_usage(db: Session, user):
    """
    Проверяет лимит и увеличивает счётчик.

    Возвращает:
        allowed: bool
        remaining: int | None
        is_premium: bool
    """

    # ===== PREMIUM → безлимит =====
    if user.is_premium:
        return True, None, True

    today = date.today()

    usage = (
        db.query(AIUsage)
        .filter(AIUsage.user_id == user.id, AIUsage.day == today)
        .first()
    )

    if not usage:
        usage = AIUsage(user_id=user.id, day=today, count=0)
        db.add(usage)
        db.commit()
        db.refresh(usage)

    # ===== лимит достигнут =====
    if usage.count >= FREE_LIMIT:
        return False, 0, False

    # ===== увеличиваем счётчик =====
    usage.count += 1
    db.commit()

    remaining = max(FREE_LIMIT - usage.count, 0)

    return True, remaining, False