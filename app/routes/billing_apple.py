# app/routes/billing_apple.py
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import UserSarbaz
from app.routes.auth import get_current_user

router = APIRouter(prefix="/api/billing", tags=["Billing"])
log = logging.getLogger("billing.apple")

# =========================
# CONFIG
# =========================
BUNDLE_ID_EXPECTED = "kz.sarbazinfo5000.app"

# ⚠️ Для StoreKit2 verifyReceipt обычно НЕ нужен.
# Но можешь оставить, если параллельно поддерживаешь legacy-чеки.
APPLE_SHARED_SECRET = os.getenv("APPLE_SHARED_SECRET")  # optional for SK2 path

# Корневой сертификат Apple (PEM) — положи в репо
APPLE_ROOT_CERT_PATH = Path(__file__).resolve().parent.parent / "certs" / "AppleRootCA-G3.pem"


class AppleVerifyRequest(BaseModel):
    productId: str
    receiptData: str  # StoreKit2: JWS (jwsRepresentation)
    transactionId: str | None = None


# =========================================================
# CERT / JWS HELPERS
# =========================================================
def _load_apple_root_cert() -> x509.Certificate:
    if not APPLE_ROOT_CERT_PATH.exists():
        raise RuntimeError(f"Apple root cert not found: {APPLE_ROOT_CERT_PATH}")

    pem = APPLE_ROOT_CERT_PATH.read_bytes()
    return x509.load_pem_x509_certificate(pem)


def _b64_to_der_cert(b64: str) -> x509.Certificate:
    der = base64.b64decode(b64)
    return x509.load_der_x509_certificate(der)


def _verify_cert_signed_by(child: x509.Certificate, issuer: x509.Certificate) -> None:
    issuer_pub = issuer.public_key()
    sig = child.signature
    tbs = child.tbs_certificate_bytes
    algo = child.signature_hash_algorithm

    if isinstance(issuer_pub, rsa.RSAPublicKey):
        issuer_pub.verify(sig, tbs, padding.PKCS1v15(), algo)
        return

    if isinstance(issuer_pub, ec.EllipticCurvePublicKey):
        issuer_pub.verify(sig, tbs, ec.ECDSA(algo))
        return

    raise RuntimeError(f"Unsupported public key type: {type(issuer_pub)}")


def _verify_x5c_chain(x5c: list[str], apple_root: x509.Certificate) -> x509.Certificate:
    """
    Apple JWS содержит x5c: [leaf, intermediate, ...]
    Проверяем:
      leaf подписан intermediate
      intermediate подписан root (наш Apple Root CA)
    Возвращаем leaf cert (его public key используется для проверки подписи JWS).
    """
    if len(x5c) < 2:
        raise ValueError("x5c chain is too short")

    leaf = _b64_to_der_cert(x5c[0])
    intermediate = _b64_to_der_cert(x5c[1])

    _verify_cert_signed_by(leaf, intermediate)
    _verify_cert_signed_by(intermediate, apple_root)

    return leaf


def _looks_like_jws(s: str) -> bool:
    # JWS = header.payload.signature → 3 части с точками
    parts = s.split(".")
    return len(parts) == 3 and all(p.strip() for p in parts)


def _decode_and_verify_storekit2_jws(jws: str) -> dict[str, Any]:
    """
    1) достаём header без проверки
    2) проверяем цепочку x5c до Apple Root
    3) проверяем подпись JWS leaf public key
    4) возвращаем payload dict
    """
    try:
        header = jwt.get_unverified_header(jws)
    except Exception as e:
        raise ValueError(f"Invalid JWS header: {e}")

    x5c = header.get("x5c")
    alg = header.get("alg")

    if not x5c or not isinstance(x5c, list):
        raise ValueError("Missing x5c in JWS header")
    if not alg:
        raise ValueError("Missing alg in JWS header")

    apple_root = _load_apple_root_cert()
    leaf_cert = _verify_x5c_chain(x5c, apple_root)
    leaf_pub = leaf_cert.public_key()

    try:
        payload = jwt.decode(
            jws,
            key=leaf_pub,
            algorithms=[alg],
            options={
                "verify_aud": False,  # StoreKit2 transaction JWS обычно без aud
            },
        )
    except Exception as e:
        raise ValueError(f"JWS signature verify failed: {e}")

    if not isinstance(payload, dict):
        raise ValueError("JWS payload is not an object")

    return payload


def _extract_expiry_from_sk2_payload(payload: dict[str, Any]) -> datetime | None:
    """
    Для подписок StoreKit2 transaction payload содержит expiresDate (ms unix).
    """
    expires_ms = payload.get("expiresDate")
    if expires_ms is None:
        return None
    try:
        ms = int(expires_ms)
    except Exception:
        return None

    if ms <= 0:
        return None

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


# =========================================================
# ENDPOINT (StoreKit2)
# =========================================================
@router.post("/apple/verify")
def verify_apple(
    req: AppleVerifyRequest,
    user: UserSarbaz = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    jws = (req.receiptData or "").strip()
    product_id = (req.productId or "").strip()

    if not jws or not product_id:
        raise HTTPException(status_code=400, detail="receiptData/productId required")

    if not _looks_like_jws(jws):
        # Если хочешь — можно тут оставить legacy verifyReceipt,
        # но ты просил StoreKit2, поэтому явно фейлим.
        log.warning("Non-JWS receiptData received (expected StoreKit2 JWS)")
        return {"is_premium": False, "premium_until": None}

    try:
        payload = _decode_and_verify_storekit2_jws(jws)
    except Exception as e:
        log.warning("Apple SK2 JWS verify failed: %s", str(e))
        return {"is_premium": False, "premium_until": None}

    # =============================
    # SECURITY CHECKS
    # =============================
    bundle_id = (payload.get("bundleId") or "").strip()
    if bundle_id != BUNDLE_ID_EXPECTED:
        log.error("Bundle ID mismatch (SK2)", extra={"bundleId": bundle_id})
        return {"is_premium": False, "premium_until": None}

    pid = (payload.get("productId") or "").strip()
    if pid != product_id:
        # Нормально строго сравнивать: клиент прислал productId, payload тоже его содержит
        log.warning("Product ID mismatch (SK2)", extra={"req": product_id, "payload": pid})
        return {"is_premium": False, "premium_until": None}

    # (опционально) можно валидировать transactionId
    # tid_payload = (payload.get("transactionId") or "").strip()

    # =============================
    # EXPIRY
    # =============================
    premium_until = _extract_expiry_from_sk2_payload(payload)
    if premium_until is None:
        # Не подписка или Apple не дал expiresDate
        return {"is_premium": False, "premium_until": None}

    now = datetime.now(timezone.utc)
    is_premium = premium_until > now

    # =============================
    # UPDATE USER
    # =============================
    # user.premium_until у тебя может быть naive/aware — приводим аккуратно
    current = user.premium_until
    if current is not None and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    if current is None or premium_until > current:
        user.premium_until = premium_until
        db.add(user)
        db.commit()

    return {
        "is_premium": is_premium,
        "premium_until": premium_until.isoformat(),
    }