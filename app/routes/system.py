from fastapi import APIRouter, Query
from app.config.app_config import get_app_config

router = APIRouter(prefix="/api", tags=["System"])


@router.get("/app-version")
def get_app_version(platform: str = Query("android")):
    """
    Универсальная проверка версии приложения.
    Работает со старыми клиентами.
    """

    config = get_app_config()

    cfg = config.get(platform.lower(), config["android"])

    return {
        # --- новый формат ---
        "latest_version": cfg["latest_version"],
        "latest_build": cfg["latest_build"],
        "min_supported_version": cfg["min_supported_version"],
        "min_supported_build": cfg["min_supported_build"],
        "force_update": False,
        "store_url": cfg["store_url"],

        # --- старый формат (для старых APK) ---
        "latestVersion": cfg["latest_version"],
        "latestBuild": cfg["latest_build"],
        "minSupportedVersion": cfg["min_supported_version"],
        "minSupportedBuild": cfg["min_supported_build"],
    }