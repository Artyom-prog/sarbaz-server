# app/routes/billing_apple.py
# FastAPI endpoint для Apple verifyReceipt (iOS подписка)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone

import os
import requests

from app.db import get_db
from app.routes.auth import get_current_user
from app.models import UserSarbaz

router = APIRouter(prefix="/api/billing", tags=["Billing"])


class AppleVerifyRequest(BaseModel):
    productId: str
    receiptData: str  # base64
    transactionId: str | None = None


APPLE_SHARED_SECRET = os.getenv("APPLE_SHARED_SECRET")
if not APPLE_SHARED_SECRET:
    # лучше падать при старте сервиса, чем ловить "missing metadata" в рантайме
    raise RuntimeError("APPLE_SHARED_SECRET is not set")


APPLE_PROD_URL = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"


def _call_apple_verify(receipt_data: str) -> dict:
    payload = {
        "receipt-data": receipt_data,
        "password": APPLE_SHARED_SECRET,
        "exclude-old-transactions": True,
    }

    r = requests.post(APPLE_PROD_URL, json=payload, timeout=12)
    data = r.json()

    # 21007 = это sandbox receipt, отправленный в prod endpoint
    if data.get("status") == 21007:
        r = requests.post(APPLE_SANDBOX_URL, json=payload, timeout=12)
        data = r.json()

    return data


def _extract_latest_expiry(data: dict, product_id: str) -> datetime | None:
    """
    Достаём expires_date_ms по нужному product_id из latest_receipt_info.
    Для подписок это самый прямой способ.
    """
    items = data.get("latest_receipt_info") or []
    if not items:
        return None

    # фильтруем по product_id (важно, если в receipt есть несколько продуктов)
    filtered = [x for x in items if x.get("product_id") == product_id]
    if not filtered:
        return None

    # берём самый свежий expires_date_ms
    def _ms(x):
        v = x.get("expires_date_ms")
        try:
            return int(v)
        except Exception:
            return 0

    best = max(filtered, key=_ms)
    ms = _ms(best)
    if ms <= 0:
        return None

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


@router.post("/apple/verify")
def verify_apple(
    req: AppleVerifyRequest,
    user: UserSarbaz = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Проверяет iOS подписку по receipt (base64):
    - verifyReceipt (prod + fallback sandbox)
    - вычисляет premium_until
    - обновляет user.premium_until
    """
    receipt = (req.receiptData or "").strip()
    product_id = (req.productId or "").strip()

    if not receipt or not product_id:
        raise HTTPException(status_code=400, detail="receiptData/productId required")

    data = _call_apple_verify(receipt)

    status = data.get("status")
    # 0 = OK
    if status != 0:
        # полезно вернуть статус Apple для дебага
        raise HTTPException(status_code=400, detail={"apple_status": status, "apple": data})

    premium_until = _extract_latest_expiry(data, product_id)
    if premium_until is None:
        # receipt валиден, но нет активной подписки по этому productId
        return {"is_premium": False, "premium_until": None}

    now = datetime.now(timezone.utc)
    is_premium = premium_until > now

    # Обновляем premium_until только если он реально больше текущего
    if user.premium_until is None or premium_until > user.premium_until.replace(tzinfo=timezone.utc):
        user.premium_until = premium_until

    db.add(user)
    db.commit()

    return {
        "is_premium": is_premium,
        "premium_until": premium_until.isoformat(),
    }