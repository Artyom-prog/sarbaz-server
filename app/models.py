#  app/models.py (sarbaz-server)

from datetime import date

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Date
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from .db import Base


# ==========================================================
# USERS SARBAZ
# Основная таблица пользователей Sarbaz (физически в OSA БД)
# ==========================================================
class UserSarbaz(Base):
    __tablename__ = "users_sarbaz"

    id = Column(Integer, primary_key=True, index=True)

    # UID из Firebase — главный идентификатор пользователя
    firebase_uid = Column(String(128), unique=True, index=True, nullable=False)

    # провайдер входа (google, apple и т.д.)
    provider = Column(String(32), nullable=True)

    # резервный email
    email = Column(String(254), nullable=True, index=True)

    # отображаемое имя пользователя
    name = Column(String(120), nullable=True)

    # ссылка на аватар
    avatar_url = Column(String(512), nullable=True)

    # флаг премиум-доступа (используется для снятия лимитов ИИ)
    is_premium = Column(Boolean, default=False, nullable=False)

    # блокировка пользователя администратором
    is_blocked = Column(Boolean, default=False, nullable=False)
    blocked_reason = Column(Text, nullable=True)

    # время последнего входа
    last_login_at = Column(DateTime, nullable=True)

    # дата создания пользователя
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # ORM-связь с refresh-сессиями
    sessions = relationship(
        "UserSarbazSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ORM-связь с использованием ИИ
    ai_usage = relationship(
        "AIUsage",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ==========================================================
# USER SARBAZ SESSIONS
# Таблица refresh-сессий (физически создана в OSA БД)
# ==========================================================
class UserSarbazSession(Base):
    __tablename__ = "user_sarbaz_sessions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)

    # ссылка на пользователя Sarbaz
    user_id = Column(
        Integer,
        ForeignKey("users_sarbaz.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # SHA-256 hash refresh-токена (64 символа)
    refresh_token_hash = Column(String(64), nullable=False, unique=True, index=True)

    # срок действия refresh-токена
    expires_at = Column(DateTime, nullable=False, index=True)

    # момент отзыва токена (logout / revoke)
    revoked_at = Column(DateTime, nullable=True, index=True)

    # дата создания записи
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # ORM-связь обратно к пользователю
    user = relationship("UserSarbaz", back_populates="sessions")


# ==========================================================
# AI USAGE
# Учёт количества запросов к ИИ по дням
# Таблица также должна быть создана в OSA БД через миграцию
# ==========================================================
class AIUsage(Base):
    __tablename__ = "ai_usage"

    id = Column(Integer, primary_key=True, index=True)

    # пользователь, который сделал запрос к ИИ
    user_id = Column(
        Integer,
        ForeignKey("users_sarbaz.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # день, за который считается лимит
    day = Column(Date, default=date.today, nullable=False, index=True)

    # количество запросов за этот день
    count = Column(Integer, default=0, nullable=False)

    # ORM-связь обратно к пользователю
    user = relationship("UserSarbaz", back_populates="ai_usage")