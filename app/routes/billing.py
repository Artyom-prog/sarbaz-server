from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import os, json, requests

from google.oauth2 import service_account
from google.auth.transport.requests import Request

from app.db import get_db
from app.routes.auth import get_current_user
from app.models import UserSarbaz

router = APIRouter(prefix="/api/billing", tags=["Billing"])


PACKAGE_NAME = "kz.sarbazinfo5000.app"
SUB_ID = "sarbaz_premium_monthly"


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

    user.is_premium = expiry > datetime.utcnow()
    user.premium_until = expiry
    db.commit()

    return {
        "is_premium": user.is_premium,
        "premium_until": expiry,
    }