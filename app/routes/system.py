import json
from flask import Blueprint, jsonify, request, current_app

system_bp = Blueprint("system", __name__, url_prefix="/api")


@system_bp.get("/ping")
def ping():
    return jsonify({"success": True, "status": "Server is running"})


@system_bp.get("/app-version")
def app_version():
    try:
        with open(current_app.config["CONFIG_PATH"], "r", encoding="utf-8") as f:
            data = json.load(f)

        latest = str(data.get("latestVersion", "")).strip()
        latest_build = int(data.get("latestBuild", 0))

        if not latest or latest_build <= 0:
            return jsonify({"error": "invalid config"}), 500

        return jsonify({
            "latestVersion": latest,
            "latestBuild": latest_build,
            "minSupportedVersion": data.get("minSupportedVersion"),
            "minSupportedBuild": data.get("minSupportedBuild"),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500