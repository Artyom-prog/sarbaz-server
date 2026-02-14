from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import os
import json
import requests

from google.oauth2 import service_account
from google.auth.transport.requests import Request
from dateutil import parser as date_parser  # pip install python-dateutil

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
# Вспомогательная функция парсинга дат от Google (RFC 3339)
# ==========================================================

def parse_google_datetime(dt_str: str | None) -> datetime | None:
    """
    Парсит строку в формате RFC 3339 / ISO 8601 от Google Play API.
    Возвращает None при ошибке или пустой строке.
    """
    if not dt_str:
        return None
    try:
        # dateutil.parser.isoparse отлично справляется с Z, +offset, наносекундами
        return date_parser.isoparse(dt_str)
    except (ValueError, TypeError):
        return None


# ==========================================================
# GOOGLE VERIFY (SUBSCRIPTIONS V2) — ИСПРАВЛЕННАЯ ВЕРСИЯ
# ==========================================================

def verify_google_subscription_v2(purchase_token: str):
    """
    Проверяет подписку через новый endpoint subscriptionsv2.
    Возвращает:
        is_active: bool           — есть ли право доступа (entitlement) сейчас
        expiry: datetime | None   — самая поздняя дата окончания среди всех lineItems
        product_id: str | None    — productId из первого активного или первого элемента
        raw: dict                 — полный ответ от Google для отладки
    """
    access_token = get_access_token()

    url = (
        f"https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{purchase_token}"
    )

    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        r.raise_for_status()  # сразу кидает исключение при 4xx/5xx
    except requests.RequestException as e:
        raise HTTPException(502, f"Google verification request failed: {str(e)}")

    payload = r.json()

    line_items = payload.get("lineItems", [])
    if not line_items:
        return False, None, None, payload

    now = datetime.now(timezone.utc)
    max_expiry: datetime | None = None
    is_entitled = False
    selected_product_id: str | None = None

    # subscriptionState обычно находится на верхнем уровне (SubscriptionPurchaseV2)
    top_level_state = payload.get("subscriptionState", "UNKNOWN")

    for item in line_items:
        expiry = parse_google_datetime(item.get("expiryTime"))

        # Обновляем максимальную дату истечения
        if expiry and (max_expiry is None or expiry > max_expiry):
            max_expiry = expiry

        # Определяем, даёт ли этот item право доступа
        # Используем top-level state, т.к. в subscriptionsv2 он основной
        state = top_level_state

        item_entitled = False

        if state in [
            "SUBSCRIPTION_STATE_ACTIVE",
            "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
        ]:
            item_entitled = True
        elif state == "SUBSCRIPTION_STATE_CANCELED" and expiry and expiry > now:
            item_entitled = True
        # paused, on_hold, expired, revoked → не даём доступ

        if item_entitled:
            is_entitled = True
            if not selected_product_id:
                selected_product_id = item.get("productId")

    # Финальное решение: есть entitlement И срок действия не истёк
    is_active = is_entitled and max_expiry is not None and max_expiry > now

    # Если не нашли product_id среди активных — берём первый
    if not selected_product_id and line_items:
        selected_product_id = line_items[0].get("productId")

    return is_active, max_expiry, selected_product_id, payload


# ==========================================================
# VERIFY ENDPOINT — ИСПРАВЛЕННЫЙ
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

    # 1. Проверяем в Google
    is_active, expiry, product_id, payload = verify_google_subscription_v2(purchase_token)

    now = datetime.now(timezone.utc)

    # Получаем реальное время покупки из API (лучше, чем now)
    start_time = parse_google_datetime(payload.get("startTime"))
    purchased_at = start_time or now

    # 2. UPSERT в таблицу покупок
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
            purchased_at=purchased_at,
            expires_at=expiry,
            is_active=is_active,
        )
        db.add(gp)
    else:
        gp.expires_at = expiry
        gp.is_active = is_active
        gp.product_id = product_id
        # purchased_at обычно не меняем, если запись уже была

    # 3. Обновляем кэш премиума у пользователя
    if is_active and expiry:
        if not user.premium_until or expiry > user.premium_until:
            user.premium_until = expiry
    else:
        # Ищем хотя бы одну другую активную подписку
        other_active = (
            db.query(AppPurchase)
            .filter(
                AppPurchase.user_id == user.id,
                AppPurchase.is_active == True,
                AppPurchase.expires_at > now,
            )
            .order_by(AppPurchase.expires_at.desc())
            .first()
        )
        user.premium_until = other_active.expires_at if other_active else None

    db.commit()
    db.refresh(user)

    # 4. Ответ клиенту
    is_premium = bool(user.premium_until and user.premium_until > now)

    return {
        "is_premium": is_premium,
        "premium_until": user.premium_until.isoformat() if user.premium_until else None,
    }