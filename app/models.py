# Модель пользователя Sarbaz
# Таблица отдельная, но база общая с OSA

from sqlalchemy import Column, Integer, String, Boolean
from .db import Base


class UserSarbaz(Base):
    __tablename__ = "users_sarbaz"

    id = Column(Integer, primary_key=True, index=True)

    # UID из Firebase (главный идентификатор)
    firebase_uid = Column(String, unique=True, index=True, nullable=False)

    # резервный email
    email = Column(String, nullable=True)

    # имя пользователя
    name = Column(String, nullable=True)

    # премиум-флаг
    is_premium = Column(Boolean, default=False)