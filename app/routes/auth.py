from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from jose import jwt, JWTError
from datetime import datetime, timedelta
import os, json
import firebase_admin
from firebase_admin import auth, credentials

from app.db import SessionLocal
from app.models import UserSarbaz


router = APIRouter(prefix="/api", tags=["Auth"])


# --------------------------------------------------
# Firebase init
# --------------------------------------------------
firebase_json = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_json:
    raise RuntimeError("FIREBASE_CREDENTIALS is not set")

cred = credentials.Certificate(json.loads(firebase_json))

# чтобы не падало при повторной инициализации (важно для reload/gunicorn)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)


# --------------------------------------------------
# JWT
# --------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set")

JWT_EXPIRE_HOURS = 24


def create_token(uid: str) -> str:
    payload = {
        "sub": uid,
        "iss": "sarbaz",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# --------------------------------------------------
# DB
# --------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------
# AUTH HEADER
# --------------------------------------------------
def get_current_uid(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid Authorization header")

    token = authorization.split(" ", 1)[1]

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except JWTError:
        raise HTTPException(401, "Invalid token")


# --------------------------------------------------
# POST /api/social-login
# --------------------------------------------------
@router.post("/social-login")
def social_login(data: dict, db: Session = Depends(get_db)):

    id_token = data.get("id_token")
    if not id_token:
        raise HTTPException(400, "id_token required")

    # --- проверяем Firebase токен ---
    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(401, "Invalid Firebase token")

    uid = decoded["uid"]
    email = decoded.get("email")
    name = decoded.get("name")
    provider = decoded.get("firebase", {}).get("sign_in_provider")

    # fallback имени (особенно важно для Apple)
    if not name:
        name = "User"

    # --- ищем пользователя ---
    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    # --- если нет → создаём ---
    if not user:
        user = UserSarbaz(
            firebase_uid=uid,
            email=email,
            name=name,
            provider=provider,
            last_login_at=datetime.utcnow(),
        )
        db.add(user)

        try:
            db.commit()
            db.refresh(user)

        # 🔥 защита от гонки двух запросов
        except IntegrityError:
            db.rollback()
            user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    # --- обновляем время входа всегда ---
    user.last_login_at = datetime.utcnow()
    db.commit()

    # --- создаём JWT ---
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


# --------------------------------------------------
# GET /api/me
# --------------------------------------------------
@router.get("/me")
def get_me(uid: str = Depends(get_current_uid), db: Session = Depends(get_db)):
    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    if not user:
        raise HTTPException(404, "User not found")

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_premium": user.is_premium,
    }

@router.post("/auth/refresh")
def refresh_token(refresh_token: str):
    # проверяем refresh token
    # если валиден → выдаём новый access token
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
    }


# --------------------------------------------------
# DELETE /api/me
# --------------------------------------------------
@router.delete("/me")
def delete_me(uid: str = Depends(get_current_uid), db: Session = Depends(get_db)):

    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    if not user:
        raise HTTPException(404, "User not found")

    db.delete(user)
    db.commit()

    return {"success": True}