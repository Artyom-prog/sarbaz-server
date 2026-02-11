# Подключение к PostgreSQL (той же базе, что и OSA)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL")  # строка подключения Render

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


# ==================================================
# DB dependency for FastAPI
# ==================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()