from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import AIUsage

FREE_LIMIT = 5


def check_and_increment_usage(db: Session, user):
    """
    Проверяет лимит и увеличивает счётчик атомарно.

    Возвращает:
        allowed: bool
        remaining: int | None
        is_premium: bool
    """

    # ===== PREMIUM → безлимит =====
    if user.is_premium:
        return True, None, True

    today = date.today()

    # ===== берём запись С БЛОКИРОВКОЙ =====
    usage = (
        db.execute(
            select(AIUsage)
            .where(AIUsage.user_id == user.id, AIUsage.day == today)
            .with_for_update()
        )
        .scalar_one_or_none()
    )

    # ===== если записи нет — создаём =====
    if not usage:
        usage = AIUsage(user_id=user.id, day=today, count=0)
        db.add(usage)
        db.flush()  # без commit, просто получаем объект

    # ===== лимит достигнут =====
    if usage.count >= FREE_LIMIT:
        db.commit()
        return False, 0, False

    # ===== увеличиваем счётчик =====
    usage.count += 1
    db.commit()

    remaining = max(FREE_LIMIT - usage.count, 0)

    return True, remaining, False