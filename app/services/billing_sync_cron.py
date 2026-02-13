import os
import json
import requests
from datetime import datetime

from sqlalchemy.orm import Session

from google.oauth2 import service_account
from google.auth.transport.requests import Request

from app.db import SessionLocal
from app.models import AppPurchase, UserSarbaz


PACKAGE_NAME = "kz.sarbazinfo5000.app"
SUB_ID = "sarbaz_premium_monthly"


# ==========================================================
# GOOGLE ACCESS TOKEN
# ==========================================================

def get_access_token() -> str:
    raw = os.getenv("GOOGLE_PLAY_SERVICE_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_PLAY_SERVICE_JSON not set")

    info = json.loads(raw)

    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/androidpublisher"],
    )

    creds.refresh(Request())
    return creds.token


# ==========================================================
# VERIFY ONE SUBSCRIPTION
# ==========================================================

def verify_purchase_google(purchase_token: str) -> datetime | None:
    """
    Возвращает дату окончания подписки
    или None если подписка больше не активна.
    """

    access_token = get_access_token()

    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{PACKAGE_NAME}/purchases/subscriptions/"
        f"{SUB_ID}/tokens/{purchase_token}"
    )

    r = requests.get(url, headers={"Authorization": f"Bearer {access_token}"})

    if r.status_code != 200:
        return None

    payload = r.json()
    expiry_ms = int(payload["expiryTimeMillis"])

    return datetime.utcfromtimestamp(expiry_ms / 1000)


# ==========================================================
# MAIN SYNC
# ==========================================================

def sync_premium_once() -> None:
    """
    Разовая синхронизация всех активных подписок.
    """

    db: Session = SessionLocal()

    try:
        now = datetime.utcnow()

        purchases = (
            db.query(AppPurchase)
            .filter(AppPurchase.is_active == True)
            .all()
        )

        for purchase in purchases:
            expiry = verify_purchase_google(purchase.purchase_token)

            # ---------- обновляем покупку ----------
            if not expiry or expiry <= now:
                purchase.is_active = False
                purchase.expires_at = expiry
            else:
                purchase.expires_at = expiry
                purchase.is_active = True

            # ---------- обновляем пользователя ----------
            user = db.get(UserSarbaz, purchase.user_id)
            if not user:
                continue

            if purchase.is_active:
                if not user.premium_until or expiry > user.premium_until:
                    user.premium_until = expiry
            else:
                active_other = (
                    db.query(AppPurchase)
                    .filter(
                        AppPurchase.user_id == user.id,
                        AppPurchase.is_active == True,
                        AppPurchase.expires_at > now,
                    )
                    .first()
                )

                if not active_other:
                    user.premium_until = None

        db.commit()

    finally:
        db.close()