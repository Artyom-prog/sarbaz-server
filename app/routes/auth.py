# app/routes/auth.py (sarbaz-server)
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from datetime import datetime, timedelta
import os
import json
import secrets
import hashlib
import logging
import firebase_admin
from firebase_admin import auth, credentials

from app.db import get_db
from app.models import UserSarbaz, UserSarbazSession


router = APIRouter(prefix="/api", tags=["Auth"])

logger = logging.getLogger("auth")


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
    exp = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)

    payload = {
        "sub": uid,
        "iss": "sarbaz",
        "exp": exp,
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    logger.info(f"JWT CREATED → uid={uid}, exp={exp}")

    return token


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
# AUTH HEADER (ГЛАВНОЕ ИСПРАВЛЕНИЕ)
# ==================================================

def get_current_uid(authorization: str = Header(None)) -> str:
    """
    Достаёт UID из Bearer JWT.
    Даёт ПОЛНУЮ диагностику 401.
    """

    # --- нет header ---
    if not authorization:
        logger.warning("AUTH: Missing Authorization header")
        raise HTTPException(401, "Authorization header missing")

    # --- неправильный формат ---
    if not authorization.startswith("Bearer "):
        logger.warning(f"AUTH: Invalid header format → {authorization}")
        raise HTTPException(401, "Invalid Authorization header")

    token = authorization.split(" ", 1)[1]

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

        uid = payload.get("sub")
        exp = payload.get("exp")

        logger.info(
            f"AUTH OK → uid={uid}, exp={exp}, now={datetime.utcnow().timestamp()}"
        )

        if not uid:
            logger.warning("AUTH: UID missing in payload")
            raise HTTPException(401, "Invalid token payload")

        return uid

    # --- истёк ---
    except ExpiredSignatureError:
        logger.warning("AUTH: Token expired")
        raise HTTPException(401, "Token expired")

    # --- любой другой JWT косяк ---
    except JWTError as e:
        logger.warning(f"AUTH: Invalid token → {str(e)}")
        raise HTTPException(401, "Invalid token")

    # --- вообще неожиданный косяк ---
    except Exception as e:
        logger.error(f"AUTH: Unexpected auth error → {str(e)}")
        raise HTTPException(401, "Auth error")


# ==================================================
# POST /api/social-login
# ==================================================

@router.post("/social-login")
def social_login(data: dict, db: Session = Depends(get_db)):

    id_token = data.get("id_token")
    if not id_token:
        raise HTTPException(400, "id_token required")

    try:
        decoded = auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(401, "Invalid Firebase token")

    uid = decoded["uid"]
    email = decoded.get("email")
    name = decoded.get("name") or "User"
    provider = decoded.get("firebase", {}).get("sign_in_provider")

    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

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

    user.last_login_at = datetime.utcnow()
    db.commit()

    raw_refresh = generate_refresh_token()

    session = UserSarbazSession(
        user_id=user.id,
        refresh_token_hash=hash_token(raw_refresh),
        expires_at=refresh_expiry(),
    )

    db.add(session)
    db.commit()

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


def get_current_user(
    uid: str = Depends(get_current_uid),
    db: Session = Depends(get_db),
) -> UserSarbaz:
    user = db.query(UserSarbaz).filter_by(firebase_uid=uid).first()

    if not user:
        raise HTTPException(401, "User not found")

    if user.is_blocked:
        raise HTTPException(403, "User is blocked")

    return user

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
        raise HTTPException(400, "refresh_token required")

    token_hash = hash_token(raw_refresh)

    session = (
        db.query(UserSarbazSession)
        .filter(UserSarbazSession.refresh_token_hash == token_hash)
        .first()
    )

    if not session:
        # logout должен быть идемпотентным
        return {"success": True}

    session.revoked_at = datetime.utcnow()
    db.commit()

    return {"success": True}