from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from jose import jwt
from datetime import datetime, timedelta
import os, json
import firebase_admin
from firebase_admin import auth, credentials

from .db import SessionLocal
from .models import UserSarbaz


# --------------------------------------------------
# Инициализация Firebase Admin SDK (через ENV)
# --------------------------------------------------
firebase_json = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_json:
    raise RuntimeError("FIREBASE_CREDENTIALS is not set")

cred = credentials.Certificate(json.loads(firebase_json))
firebase_admin.initialize_app(cred)


# --------------------------------------------------
# Настройки JWT Sarbaz
# --------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set")

JWT_EXPIRE_HOURS = 24


def create_token(uid: str) -> str:
    """Создание JWT токена Sarbaz."""
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
    provider = decoded.get("firebase", {}).get("sign_in_provider")

    # Ищем пользователя в таблице users_sarbaz (БД OSA)
    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    # Если нет — создаём запись
    if not user:
        user = UserSarbaz(
            firebase_uid=uid,
            email=email,
            name=name,
            provider=provider,
            last_login_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # обновляем время последнего входа
        user.last_login_at = datetime.utcnow()
        db.commit()

    # создаём JWT Sarbaz
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