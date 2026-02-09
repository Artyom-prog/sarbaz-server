from sqlalchemy import Column, Integer, String, Boolean
from .db import Base


class User(Base):
    __tablename__ = "users_sarbaz"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    is_premium = Column(Boolean, default=False)