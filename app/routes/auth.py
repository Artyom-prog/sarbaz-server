from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from passlib.hash import bcrypt

from ..db import SessionLocal
from ..models import User

router = APIRouter(prefix="/api", tags=["Auth"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/register")
def register(data: dict, db: Session = Depends(get_db)):
    name = (data.get("name") or "").strip()
    phone = (data.get("phone_number") or "").strip()
    password = (data.get("password") or "").strip()
    is_premium = bool(data.get("is_premium", False))

    if not name or not password:
        raise HTTPException(400, "Name and password required")

    if db.query(User).filter_by(phone_number=phone).first():
        raise HTTPException(409, "Phone exists")

    user = User(
        name=name,
        phone_number=phone,
        password=bcrypt.hash(password),
        is_premium=is_premium,
    )

    db.add(user)
    db.commit()

    return {
        "success": True,
        "user": {
            "name": name,
            "phone_number": phone,
            "is_premium": is_premium,
        },
    }


@router.post("/login")
def login(data: dict, db: Session = Depends(get_db)):
    phone = (data.get("phone_number") or "").strip()
    password = (data.get("password") or "").strip()

    user = db.query(User).filter_by(phone_number=phone).first()

    if not user or not bcrypt.verify(password, user.password):
        raise HTTPException(401, "Invalid credentials")

    return {
        "success": True,
        "user": {
            "name": user.name,
            "phone_number": user.phone_number,
            "is_premium": user.is_premium,
        },
    }