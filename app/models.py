from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from .db import Base


# ==========================================================
# USERS SARBAZ
# ==========================================================
class UserSarbaz(Base):
    __tablename__ = "users_sarbaz"

    id = Column(Integer, primary_key=True, index=True)

    # UID из Firebase — главный идентификатор
    firebase_uid = Column(String(128), unique=True, index=True, nullable=False)

    # провайдер входа (google, apple, etc.)
    provider = Column(String(32), nullable=True)

    # резервный email
    email = Column(String(254), nullable=True, index=True)

    # имя пользователя
    name = Column(String(120), nullable=True)

    # аватар
    avatar_url = Column(String(512), nullable=True)

    # премиум
    is_premium = Column(Boolean, default=False, nullable=False)

    # блокировка
    is_blocked = Column(Boolean, default=False, nullable=False)
    blocked_reason = Column(Text, nullable=True)

    # время последнего входа
    last_login_at = Column(DateTime, nullable=True)

    # дата создания
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # связь с сессиями
    sessions = relationship(
        "UserSarbazSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ==========================================================
# USER SARBAZ SESSIONS
# Таблица физически создана в OSA БД
# ==========================================================
class UserSarbazSession(Base):
    __tablename__ = "user_sarbaz_sessions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)

    # связь с пользователем Sarbaz
    user_id = Column(
        Integer,
        ForeignKey("users_sarbaz.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # SHA-256 hash refresh-токена (64 символа)
    refresh_token_hash = Column(String(64), nullable=False, unique=True, index=True)

    # срок жизни refresh
    expires_at = Column(DateTime, nullable=False, index=True)

    # отзыв токена
    revoked_at = Column(DateTime, nullable=True, index=True)

    # дата создания
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # ORM-связь
    user = relationship("UserSarbaz", back_populates="sessions")