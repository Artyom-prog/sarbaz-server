from datetime import date
from sqlalchemy.orm import Session

from app.models import AIUsage


FREE_LIMIT = 5


def check_and_increment_usage(db: Session, user) -> bool:
    """
    True  -> можно делать запрос
    False -> лимит достигнут
    """

    # Премиум без лимита
    if getattr(user, "is_premium", False):
        return True

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

    if usage.count >= FREE_LIMIT:
        return False

    usage.count += 1
    db.commit()

    return True