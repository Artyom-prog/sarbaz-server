from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import os, json, requests

from google.oauth2 import service_account
from google.auth.transport.requests import Request

from app.db import get_db
from app.routes.auth import get_current_user
from app.models import UserSarbaz, UserSubscription, AppPurchase

router = APIRouter(prefix="/api/billing", tags=["Billing"])


PACKAGE_NAME = "kz.sarbazinfo5000.app"
SUB_ID = "sarbaz_premium_monthly"


# ==========================================================
# GOOGLE ACCESS TOKEN
# ==========================================================

def get_access_token():
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
# VERIFY PURCHASE
# ==========================================================

@router.post("/verify")
def verify_purchase(
    data: dict,
    user: UserSarbaz = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    purchase_token = data.get("purchaseToken")
    if not purchase_token:
        raise HTTPException(400, "purchaseToken required")

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

    order_id = payload.get("orderId")

    # ======================================================
    # 1. UPSERT user_subscriptions
    # ======================================================

    sub = (
        db.query(UserSubscription)
        .filter(UserSubscription.purchase_token == purchase_token)
        .first()
    )

    if not sub:
        sub = UserSubscription(
            user_id=user.id,
            product_id=SUB_ID,
            purchase_token=purchase_token,
            order_id=order_id,
            platform="android",
            purchased_at=datetime.utcnow(),
            expires_at=expiry,
            is_active=True,
        )
        db.add(sub)
    else:
        sub.expires_at = expiry
        sub.is_active = expiry > datetime.utcnow()

    # ======================================================
    # 2. GLOBAL PURCHASE HISTORY
    # ======================================================

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
            purchased_at=datetime.utcnow(),
            expires_at=expiry,
            is_active=True,
        )
        db.add(gp)
    else:
        gp.expires_at = expiry
        gp.is_active = expiry > datetime.utcnow()

    # ======================================================
    # 3. UPDATE USER PREMIUM CACHE
    # ======================================================

    user.premium_until = expiry

    db.commit()

    return {
        "is_premium": user.is_premium,
        "premium_until": expiry,
    }