# ==========================================================
# USERS SARBAZ
# ==========================================================

from datetime import datetime, date

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Date,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from .db import Base


class UserSarbaz(Base):
    """
    Пользователи Sarbaz (Firebase social login).

    Премиум определяется НЕ флагом,
    а датой окончания premium_until.
    """

    __tablename__ = "users_sarbaz"

    id = Column(Integer, primary_key=True, index=True)

    # UID из Firebase
    firebase_uid = Column(String(128), unique=True, index=True, nullable=False)

    # провайдер входа
    provider = Column(String(32), nullable=True)

    # email
    email = Column(String(254), nullable=True, index=True)

    # имя и аватар
    name = Column(String(120), nullable=True)
    avatar_url = Column(String(512), nullable=True)

    # =========================
    # PREMIUM
    # =========================

    # дата окончания премиума
    premium_until = Column(DateTime, nullable=True)

    @property
    def is_premium(self) -> bool:
        """
        True если премиум ещё действует.
        """
        if self.premium_until is None:
            return False
        return self.premium_until > datetime.utcnow()

    @property
    def premium_days_left(self) -> int:
        """
        Сколько дней осталось премиума.
        """
        if not self.is_premium:
            return 0
        delta = self.premium_until - datetime.utcnow()
        return max(delta.days, 0)

    # =========================
    # BLOCK
    # =========================

    is_blocked = Column(Boolean, default=False, nullable=False)
    blocked_reason = Column(Text, nullable=True)

    # =========================
    # SERVICE DATES
    # =========================

    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # =========================
    # RELATIONS
    # =========================

    sessions = relationship(
        "UserSarbazSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    ai_usage = relationship(
        "AIUsage",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # =========================
    # DEBUG
    # =========================

    def __repr__(self) -> str:
        return (
            f"<UserSarbaz id={self.id} "
            f"premium={self.is_premium} "
            f"until={self.premium_until}>"
        )


# ==========================================================
# USER SARBAZ SESSIONS
# ==========================================================

class UserSarbazSession(Base):
    __tablename__ = "user_sarbaz_sessions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users_sarbaz.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    refresh_token_hash = Column(String(64), nullable=False, unique=True, index=True)

    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("UserSarbaz", back_populates="sessions")


# ==========================================================
# AI USAGE
# ==========================================================

class AIUsage(Base):
    __tablename__ = "ai_usage"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users_sarbaz.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    day = Column(Date, default=date.today, nullable=False, index=True)

    count = Column(Integer, default=0, nullable=False)

    user = relationship("UserSarbaz", back_populates="ai_usage")

    def __repr__(self) -> str:
        return f"<AIUsage user_id={self.user_id} day={self.day} count={self.count}>"