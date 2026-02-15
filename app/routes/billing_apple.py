# app/routes/billing_apple.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import os
import requests
import logging

from app.db import get_db
from app.routes.auth import get_current_user
from app.models import UserSarbaz

router = APIRouter(prefix="/api/billing", tags=["Billing"])
log = logging.getLogger("billing.apple")


class AppleVerifyRequest(BaseModel):
    productId: str
    receiptData: str
    transactionId: str | None = None


APPLE_SHARED_SECRET = os.getenv("APPLE_SHARED_SECRET")
if not APPLE_SHARED_SECRET:
    raise RuntimeError("APPLE_SHARED_SECRET is not set")


APPLE_PROD_URL = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"


# =========================================================
# CALL APPLE
# =========================================================
def _call_apple_verify(receipt_data: str) -> dict:
    payload = {
        "receipt-data": receipt_data,
        "password": APPLE_SHARED_SECRET,
        "exclude-old-transactions": True,
    }

    r = requests.post(APPLE_PROD_URL, json=payload, timeout=12)
    data = r.json()

    # sandbox receipt
    if data.get("status") == 21007:
        r = requests.post(APPLE_SANDBOX_URL, json=payload, timeout=12)
        data = r.json()

    return data


# =========================================================
# EXTRACT EXPIRY
# =========================================================
def _extract_latest_expiry(data: dict, product_id: str) -> datetime | None:
    latest = data.get("latest_receipt_info") or []

    # фильтр по продукту
    filtered = [x for x in latest if x.get("product_id") == product_id]
    if not filtered:
        return None

    def _ms(x):
        try:
            return int(x.get("expires_date_ms") or 0)
        except Exception:
            return 0

    best = max(filtered, key=_ms)
    ms = _ms(best)
    if ms <= 0:
        return None

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


# =========================================================
# ENDPOINT
# =========================================================
@router.post("/apple/verify")
def verify_apple(
    req: AppleVerifyRequest,
    user: UserSarbaz = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    receipt = (req.receiptData or "").strip()
    product_id = (req.productId or "").strip()

    if not receipt or not product_id:
        raise HTTPException(status_code=400, detail="receiptData/productId required")

    data = _call_apple_verify(receipt)

    status = data.get("status")

    # =============================
    # INVALID RECEIPT
    # =============================
    if status != 0:
        log.warning("Apple verify failed", extra={"status": status, "data": data})
        return {"is_premium": False, "premium_until": None}

    # =============================
    # SECURITY: bundle_id check
    # =============================
    bundle_id = (data.get("receipt") or {}).get("bundle_id")
    if bundle_id != "kz.sarbazinfo5000.app":  # <-- ВАЖНО: твой bundle id
        log.error("Bundle ID mismatch", extra={"bundle_id": bundle_id})
        return {"is_premium": False, "premium_until": None}

    # =============================
    # EXPIRY
    # =============================
    premium_until = _extract_latest_expiry(data, product_id)
    if premium_until is None:
        return {"is_premium": False, "premium_until": None}

    now = datetime.now(timezone.utc)
    is_premium = premium_until > now

    # =============================
    # UPDATE USER
    # =============================
    if user.premium_until is None or premium_until > user.premium_until.replace(tzinfo=timezone.utc):
        user.premium_until = premium_until
        db.add(user)
        db.commit()

    return {
        "is_premium": is_premium,
        "premium_until": premium_until.isoformat(),
    }