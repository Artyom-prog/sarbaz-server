from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone
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
# GOOGLE VERIFY (SUBSCRIPTIONS V2)
# ==========================================================

def verify_google_subscription_v2(purchase_token: str):
    """
    Проверяет подписку через новый endpoint subscriptionsv2.
    Возвращает:
        is_active: bool
        expiry: datetime | None
        product_id: str | None
        raw: dict
    """

    access_token = get_access_token()

    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{purchase_token}"
    )

    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except requests.RequestException:
        raise HTTPException(502, "Google verification request failed")

    if r.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail={
                "msg": "Google verify failed",
                "google_status": r.status_code,
                "google_body": r.text,
            },
        )

    payload = r.json()

    # ------------------------------------------------------
    # lineItems — список активных entitlement’ов
    # ------------------------------------------------------

    line_items = payload.get("lineItems", [])
    if not line_items:
        return False, None, None, payload

    line = line_items[0]

    # expiryTime может быть строкой миллисекунд
    expiry_ms = int(line.get("expiryTime", "0"))
    expiry = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc)

    is_active = expiry > datetime.now(tz=timezone.utc)

    product_id = line.get("productId")

    return is_active, expiry, product_id, payload


# ==========================================================
# VERIFY ENDPOINT
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

    purchase_token = (data.get("purchaseToken") or "").strip()
    if not purchase_token:
        raise HTTPException(400, "purchaseToken required")

    # ------------------------------------------------------
    # 1. VERIFY IN GOOGLE
    # ------------------------------------------------------

    is_active, expiry, product_id, _ = verify_google_subscription_v2(purchase_token)

    now = datetime.now(tz=timezone.utc)

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
            product_id=product_id,
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
        gp.product_id = product_id

    # ------------------------------------------------------
    # 3. UPDATE USER PREMIUM CACHE
    # ------------------------------------------------------

    if is_active:
        if not user.premium_until or expiry > user.premium_until:
            user.premium_until = expiry
    else:
        other_active = (
            db.query(AppPurchase)
            .filter(
                AppPurchase.user_id == user.id,
                AppPurchase.is_active == True,
                AppPurchase.expires_at > now,
            )
            .first()
        )

        if not other_active:
            user.premium_until = None

    db.commit()
    db.refresh(user)

    # ------------------------------------------------------
    # 4. RESPONSE ДЛЯ КЛИЕНТА
    # ------------------------------------------------------

    return {
        "is_premium": bool(user.premium_until and user.premium_until > now),
        "premium_until": user.premium_until,
    }