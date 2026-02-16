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

APPLE_ROOT_CERT_PATH = (
    Path(__file__).resolve().parent.parent / "certs" / "AppleRootCA-G3.pem"
)


class AppleVerifyRequest(BaseModel):
    productId: str
    receiptData: str  # StoreKit2 JWS
    transactionId: str | None = None


# =========================================================
# CERT / JWS HELPERS
# =========================================================
def _load_apple_root_cert() -> x509.Certificate:
    if not APPLE_ROOT_CERT_PATH.exists():
        raise RuntimeError(f"Apple root cert not found: {APPLE_ROOT_CERT_PATH}")

    return x509.load_pem_x509_certificate(APPLE_ROOT_CERT_PATH.read_bytes())


def _b64_to_der_cert(b64: str) -> x509.Certificate:
    return x509.load_der_x509_certificate(base64.b64decode(b64))


def _verify_cert_signed_by(child: x509.Certificate, issuer: x509.Certificate) -> None:
    issuer_pub = issuer.public_key()

    if isinstance(issuer_pub, rsa.RSAPublicKey):
        issuer_pub.verify(
            child.signature,
            child.tbs_certificate_bytes,
            padding.PKCS1v15(),
            child.signature_hash_algorithm,
        )
        return

    if isinstance(issuer_pub, ec.EllipticCurvePublicKey):
        issuer_pub.verify(
            child.signature,
            child.tbs_certificate_bytes,
            ec.ECDSA(child.signature_hash_algorithm),
        )
        return

    raise RuntimeError(f"Unsupported public key type: {type(issuer_pub)}")


def _verify_cert_validity(*certs: x509.Certificate) -> None:
    now = datetime.now(timezone.utc)

    for cert in certs:
        if cert.not_valid_before.replace(tzinfo=timezone.utc) > now:
            raise ValueError("Certificate not yet valid")
        if cert.not_valid_after.replace(tzinfo=timezone.utc) < now:
            raise ValueError("Certificate expired")


def _verify_x5c_chain(x5c: list[str], apple_root: x509.Certificate) -> x509.Certificate:
    """
    Проверяем:
    leaf -> intermediate -> Apple Root
    """
    if len(x5c) < 2:
        raise ValueError("x5c chain too short")

    leaf = _b64_to_der_cert(x5c[0])
    intermediate = _b64_to_der_cert(x5c[1])

    _verify_cert_validity(leaf, intermediate, apple_root)
    _verify_cert_signed_by(leaf, intermediate)
    _verify_cert_signed_by(intermediate, apple_root)

    return leaf


def _looks_like_jws(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 3 and all(p.strip() for p in parts)


def _decode_and_verify_storekit2_jws(jws: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(jws)
    except Exception as e:
        raise ValueError(f"Invalid JWS header: {e}")

    x5c = header.get("x5c")
    alg = header.get("alg")

    if not isinstance(x5c, list) or not x5c:
        raise ValueError("Missing x5c in header")

    if not alg:
        raise ValueError("Missing alg in header")

    apple_root = _load_apple_root_cert()
    leaf_cert = _verify_x5c_chain(x5c, apple_root)
    leaf_pub = leaf_cert.public_key()

    try:
        payload = jwt.decode(
            jws,
            key=leaf_pub,
            algorithms=[alg],
            options={
                "verify_aud": False,
                "verify_exp": False,
            },
        )
    except Exception as e:
        raise ValueError(f"JWS signature verify failed: {e}")

    if not isinstance(payload, dict):
        raise ValueError("Payload is not dict")

    return payload


def _extract_expiry(payload: dict[str, Any]) -> datetime | None:
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
# ENDPOINT
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
        log.warning("Non-JWS receipt received")
        return {"is_premium": False, "premium_until": None}

    try:
        payload = _decode_and_verify_storekit2_jws(jws)
    except Exception as e:
        log.warning("Apple SK2 verify failed: %s", str(e))
        return {"is_premium": False, "premium_until": None}

    # =============================
    # SECURITY CHECKS
    # =============================
    if payload.get("bundleId") != BUNDLE_ID_EXPECTED:
        log.error("Bundle mismatch: %s", payload.get("bundleId"))
        return {"is_premium": False, "premium_until": None}

    if payload.get("productId") != product_id:
        log.warning("Product mismatch")
        return {"is_premium": False, "premium_until": None}

    # =============================
    # EXPIRY
    # =============================
    premium_until = _extract_expiry(payload)
    if premium_until is None:
        return {"is_premium": False, "premium_until": None}

    now = datetime.now(timezone.utc)
    is_premium = premium_until > now

    # =============================
    # UPDATE USER
    # =============================
    current = user.premium_until
    if current and current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    if current is None or premium_until > current:
        user.premium_until = premium_until
        db.add(user)
        db.commit()

    return {
        "is_premium": is_premium,
        "premium_until": premium_until.isoformat(),
    }