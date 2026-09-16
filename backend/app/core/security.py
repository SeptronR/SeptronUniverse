"""Passwords, JWTs (kid rotation), TOTP, hashing, signed tokens — Prompts/00_PREREQUISITE_Project_Setup.md §3.18."""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import pyotp
from jose import JWTError, jwt

from app.core.config import settings
from app.core.errors import APIError, ErrorCode

ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12


# ---- passwords ----------------------------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ---- JWT with kid rotation -----------------------------------------------------------------------------------
def _keys() -> dict[str, str]:
    return {settings.JWT_KID: settings.SECRET_KEY, **settings.JWT_PREVIOUS_KEYS}


def _encode(claims: dict[str, Any], expires: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "iat": int(now.timestamp()), "exp": int((now + expires).timestamp())}
    return str(jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM, headers={"kid": settings.JWT_KID}))


def create_access_token(
    sub: uuid.UUID | str, institution_id: uuid.UUID | str | None, is_super_admin: bool = False, jti: str | None = None
) -> str:
    return _encode(
        {
            "sub": str(sub),
            "type": "access",
            "inst": str(institution_id) if institution_id else None,
            "sa": is_super_admin,
            "jti": jti or uuid.uuid4().hex,
        },
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(sub: uuid.UUID | str, family: str, jti: str | None = None) -> str:
    """Refresh tokens rotate; ``family`` ties rotations together so reuse revokes the whole family."""
    return _encode(
        {"sub": str(sub), "type": "refresh", "family": family, "jti": jti or uuid.uuid4().hex},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    try:
        kid = jwt.get_unverified_header(token).get("kid", settings.JWT_KID)
        key = _keys().get(kid)
        if not key:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Unknown signing key")
        claims: dict[str, Any] = jwt.decode(token, key, algorithms=[ALGORITHM])
    except JWTError:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid or expired token") from None
    if claims.get("type") != expected_type:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, f"Expected a {expected_type} token")
    return claims


# ---- TOTP MFA ------------------------------------------------------------------------------------------------
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=settings.APP_NAME)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_recovery_codes(n: int = 8) -> list[str]:
    return [secrets.token_hex(5) for _ in range(n)]


# ---- hashing for device tokens / API keys / recovery codes ---------------------------------------------------
def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "uk") -> tuple[str, str, str]:
    """Return (plain_key, key_prefix, hashed_key); only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    plain = f"{prefix}_{raw}"
    return plain, plain[:12], sha256_hex(plain)


# ---- signed QR tokens (hall tickets, credentials, session QR) -------------------------------------------------
def sign_payload(payload: dict[str, Any], ttl_seconds: int) -> str:
    body = {**payload, "exp": int(time.time()) + ttl_seconds}
    data = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode()).decode()
    sig = hmac.new(settings.SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{data}.{sig}"


def verify_signed(token: str) -> dict[str, Any]:
    try:
        data, sig = token.rsplit(".", 1)
    except ValueError:
        raise APIError(400, ErrorCode.VALIDATION, "Malformed signed token") from None
    expected = hmac.new(settings.SECRET_KEY.encode(), data.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise APIError(400, ErrorCode.VALIDATION, "Invalid signature")
    body: dict[str, Any] = json.loads(base64.urlsafe_b64decode(data.encode()))
    if body.get("exp", 0) < int(time.time()):
        raise APIError(400, ErrorCode.VALIDATION, "Signed token expired")
    return body
