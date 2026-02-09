from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db
from ..models import User
from ..utils import normalize_phone, create_token

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


@auth_bp.post("/login")
def login():
    data = request.get_json() or {}

    phone = normalize_phone(data.get("phone_number"))
    password = (data.get("password") or "").strip()

    user = User.query.filter_by(phone_number=phone).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({"success": False, "error": "Invalid credentials"}), 401

    token = create_token(phone)

    return jsonify({
        "success": True,
        "token": token,
        "user": {
            "name": user.name,
            "phone_number": phone,
            "is_premium": user.is_premium
        }
    })


@auth_bp.post("/register")
def register():
    data = request.get_json() or {}

    name = (data.get("name") or "").strip()
    phone = normalize_phone(data.get("phone_number"))
    password = (data.get("password") or "").strip()
    is_premium = bool(data.get("is_premium", False))

    if not name or not password:
        return jsonify({"success": False, "error": "Name and password required"}), 400

    if User.query.filter_by(phone_number=phone).first():
        return jsonify({"success": False, "error": "Phone exists"}), 409

    user = User(
        name=name,
        phone_number=phone,
        password=generate_password_hash(password),
        is_premium=is_premium,
    )

    db.session.add(user)
    db.session.commit()

    token = create_token(phone)

    return jsonify({
        "success": True,
        "token": token,
        "user": {
            "name": name,
            "phone_number": phone,
            "is_premium": is_premium
        }
    }), 201