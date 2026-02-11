from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from jose import jwt, JWTError
from datetime import datetime, timedelta
import os
import json
import secrets
import hashlib
import firebase_admin
from firebase_admin import auth, credentials

from app.db import SessionLocal
from app.models import UserSarbaz, UserSarbazSession


router = APIRouter(prefix="/api", tags=["Auth"])


# ==================================================
# Firebase init
# ==================================================

firebase_json = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_json:
    raise RuntimeError("FIREBASE_CREDENTIALS is not set")

cred = credentials.Certificate(json.loads(firebase_json))

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)


# ==================================================
# JWT
# ==================================================

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set")

JWT_EXPIRE_MINUTES = 30
REFRESH_EXPIRE_DAYS = 30


def create_access_token(uid: str) -> str:
    payload = {
        "sub": uid,
        "iss": "sarbaz",
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# ==================================================
# Refresh helpers
# ==================================================

def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=REFRESH_EXPIRE_DAYS)


# ==================================================
# DB dependency
# ==================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================================================
# AUTH HEADER
# ==================================================

def get_current_uid(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid Authorization header")

    token = authorization.split(" ", 1)[1]

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload["sub"]
    except JWTError:
        raise HTTPException(401, "Invalid token")


# ==================================================
# POST /api/social-login
# ==================================================

@router.post("/social-login")
def social_login(data: dict, db: Session = Depends(get_db)):

    id_token = data.get("id_token")
    if not id_token:
        raise HTTPException(400, "id_token required")

    # --- verify Firebase ---
    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(401, "Invalid Firebase token")

    uid = decoded["uid"]
    email = decoded.get("email")
    name = decoded.get("name") or "User"
    provider = decoded.get("firebase", {}).get("sign_in_provider")

    # --- find user ---
    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    # --- create if missing ---
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
        except IntegrityError:
            db.rollback()
            user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    # --- update login time ---
    user.last_login_at = datetime.utcnow()
    db.commit()

    # --- create refresh session ---
    raw_refresh = generate_refresh_token()

    session = UserSarbazSession(
        user_id=user.id,
        refresh_token_hash=hash_token(raw_refresh),
        expires_at=refresh_expiry(),
    )

    db.add(session)
    db.commit()

    # --- create access ---
    access_token = create_access_token(uid)

    return {
        "success": True,
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "is_premium": user.is_premium,
        },
    }


# ==================================================
# GET /api/me
# ==================================================

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

# ==================================================
# DELETE /api/me  — удаление аккаунта
# ==================================================

@router.delete("/me")
def delete_me(uid: str = Depends(get_current_uid), db: Session = Depends(get_db)):
    """
    Полное удаление аккаунта пользователя Sarbaz.

    Делает:
    - удаляет refresh-сессии
    - удаляет пользователя из БД
    - удаляет пользователя из Firebase Auth
    """

    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    if not user:
        raise HTTPException(404, "User not found")

    # --- удаляем Firebase-пользователя ---
    try:
        auth.delete_user(uid)
    except Exception:
        # если уже удалён — не падаем
        pass

    # --- удаляем refresh-сессии ---
    db.query(UserSarbazSession).filter_by(user_id=user.id).delete()

    # --- удаляем пользователя ---
    db.delete(user)
    db.commit()

    return {"success": True}


# ==================================================
# POST /api/auth/refresh
# ==================================================

@router.post("/auth/refresh")
def refresh_token(data: dict, db: Session = Depends(get_db)):

    raw_refresh = data.get("refresh_token")
    if not raw_refresh:
        raise HTTPException(400, "refresh_token required")

    token_hash = hash_token(raw_refresh)

    session = (
        db.query(UserSarbazSession)
        .filter(UserSarbazSession.refresh_token_hash == token_hash)
        .first()
    )

    if not session:
        raise HTTPException(401, "Invalid refresh token")

    if session.revoked_at is not None:
        raise HTTPException(401, "Refresh revoked")

    if session.expires_at < datetime.utcnow():
        raise HTTPException(401, "Refresh expired")

    user = db.query(UserSarbaz).filter_by(id=session.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    # --- rotate refresh ---
    session.revoked_at = datetime.utcnow()

    new_refresh = generate_refresh_token()

    new_session = UserSarbazSession(
        user_id=user.id,
        refresh_token_hash=hash_token(new_refresh),
        expires_at=refresh_expiry(),
    )

    db.add(new_session)
    db.commit()

    new_access = create_access_token(user.firebase_uid)

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
    }


# ==================================================
# POST /api/auth/logout
# ==================================================

@router.post("/auth/logout")
def logout(data: dict, db: Session = Depends(get_db)):

    raw_refresh = data.get("refresh_token")
    if not raw_refresh:
        return {"success": True}

    token_hash = hash_token(raw_refresh)

    session = (
        db.query(UserSarbazSession)
        .filter(UserSarbazSession.refresh_token_hash == token_hash)
        .first()
    )

    if session:
        session.revoked_at = datetime.utcnow()
        db.commit()

    return {"success": True}


# ==================================================
# POST /api/auth/logout-all
# ==================================================

@router.post("/auth/logout-all")
def logout_all(uid: str = Depends(get_current_uid), db: Session = Depends(get_db)):

    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()
    if not user:
        return {"success": True}

    db.query(UserSarbazSession).filter_by(user_id=user.id).update(
        {"revoked_at": datetime.utcnow()}
    )

    db.commit()

    return {"success": True}

# ==================================================
# CURRENT USER OBJECT (для других роутов, например AI)
# ==================================================

def get_current_user(
    uid: str = Depends(get_current_uid),
    db: Session = Depends(get_db),
) -> UserSarbaz:
    """
    Возвращает полноценный объект пользователя из БД
    по UID, полученному из JWT.
    Используется в защищённых эндпоинтах.
    """

    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    if not user:
        raise HTTPException(401, "User not found")

    if user.is_blocked:
        raise HTTPException(403, "User is blocked")

    return user