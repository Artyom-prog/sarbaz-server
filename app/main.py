from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from jose import jwt
from datetime import datetime, timedelta
import os
import firebase_admin
from firebase_admin import auth, credentials

from .db import SessionLocal, engine, Base
from .models import UserSarbaz


# --------------------------------------------------
# Создаём таблицы (для первого запуска)
# --------------------------------------------------
Base.metadata.create_all(bind=engine)


# --------------------------------------------------
# Инициализация Firebase Admin SDK
# --------------------------------------------------
cred = credentials.Certificate("config/firebase.json")
firebase_admin.initialize_app(cred)


# --------------------------------------------------
# Настройки JWT Sarbaz
# --------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "sarbaz_secret")
JWT_EXPIRE_HOURS = 24


def create_token(uid: str) -> str:
    """
    Создание JWT токена Sarbaz.
    Внутри хранится firebase_uid пользователя.
    """
    payload = {
        "sub": uid,
        "iss": "sarbaz",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# --------------------------------------------------
# Получение сессии БД
# --------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------
# FastAPI приложение
# --------------------------------------------------
app = FastAPI(title="Sarbaz API")


@app.get("/")
def root():
    return {"status": "ok"}


# --------------------------------------------------
# Социальный логин через Firebase
# --------------------------------------------------
@app.post("/api/social-login")
def social_login(data: dict, db: Session = Depends(get_db)):
    """
    Flutter отправляет:
    {
        "id_token": "...firebase token..."
    }
    """

    id_token = data.get("id_token")
    if not id_token:
        raise HTTPException(400, "id_token required")

    # Проверяем токен Firebase
    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(401, "Invalid Firebase token")

    uid = decoded["uid"]
    email = decoded.get("email")
    name = decoded.get("name")

    # Ищем пользователя в таблице Sarbaz
    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    # Если нет — создаём
    if not user:
        user = UserSarbaz(
            firebase_uid=uid,
            email=email,
            name=name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # Создаём JWT Sarbaz
    token = create_token(uid)

    return {
        "success": True,
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "is_premium": user.is_premium,
        },
    }