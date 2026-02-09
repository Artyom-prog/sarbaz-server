from flask import Blueprint, request, jsonify

from ..extensions import db
from ..models import User
from ..utils import verify_token, normalize_phone

user_bp = Blueprint("user", __name__, url_prefix="/api")


@user_bp.delete("/delete_account")
def delete_account():
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"success": False, "error": "Missing token"}), 401

    token = auth_header.split(" ")[1]
    phone = verify_token(token)

    if not phone:
        return jsonify({"success": False, "error": "Invalid token"}), 401

    data = request.get_json() or {}
    requested_phone = normalize_phone(data.get("phone_number"))

    if requested_phone != phone:
        return jsonify({"success": False, "error": "Token mismatch"}), 403

    user = User.query.filter_by(phone_number=phone).first()
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    db.session.delete(user)
    db.session.commit()

    return jsonify({"success": True})