from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import os
import json
import requests

from google.oauth2 import service_account
from google.auth.transport.requests import Request

from app.db import get_db
from app.routes.auth import get_current_user
from app.models import UserSarbaz, AppPurchase

router = APIRouter(prefix="/api/billing", tags=["Billing"])


# ==========================================================
# CONFIG
# ==========================================================

PACKAGE_NAME = "kz.sarbazinfo5000.app"
SUB_ID = "sarbaz_premium_monthly"


# ==========================================================
# GOOGLE ACCESS TOKEN
# ==========================================================

def get_access_token() -> str:
    """
    Получает OAuth access token для Google Play Developer API
    из service account JSON, лежащего в ENV.
    """
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
# VERIFY SUBSCRIPTION PURCHASE
# ==========================================================

@router.post("/verify")
def verify_purchase(
    data: dict,
    user: UserSarbaz = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Проверяет подписку в Google Play и:

    1) делает UPSERT в app_purchases
    2) обновляет premium_until у пользователя
    """

    purchase_token = data.get("purchaseToken")
    if not purchase_token:
        raise HTTPException(400, "purchaseToken required")

    # ------------------------------------------------------
    # 1. VERIFY IN GOOGLE
    # ------------------------------------------------------

    access_token = get_access_token()

    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{PACKAGE_NAME}/purchases/subscriptions/"
        f"{SUB_ID}/tokens/{purchase_token}"
    )

    r = requests.get(url, headers={"Authorization": f"Bearer {access_token}"})

    if r.status_code != 200:
        raise HTTPException(400, f"Google verify failed: {r.text}")

    payload = r.json()

    expiry_ms = int(payload["expiryTimeMillis"])
    expiry = datetime.utcfromtimestamp(expiry_ms / 1000)

    now = datetime.utcnow()
    is_active = expiry > now

    # ------------------------------------------------------
    # 2. UPSERT GLOBAL PURCHASE (app_purchases)
    # ------------------------------------------------------

    gp = (
        db.query(AppPurchase)
        .filter(AppPurchase.purchase_token == purchase_token)
        .first()
    )

    if not gp:
        gp = AppPurchase(
            app_code="sarbaz",
            user_id=user.id,
            product_id=SUB_ID,
            purchase_token=purchase_token,
            store="google",
            purchased_at=now,
            expires_at=expiry,
            is_active=is_active,
        )
        db.add(gp)
    else:
        gp.expires_at = expiry
        gp.is_active = is_active

    # ------------------------------------------------------
    # 3. UPDATE USER PREMIUM CACHE
    # ------------------------------------------------------

    if is_active:
        user.premium_until = expiry
    else:
        # если подписка закончилась — очищаем кэш
        user.premium_until = None

    db.commit()

    return {
        "is_premium": user.is_premium,
        "premium_until": user.premium_until,
    }