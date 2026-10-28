"""Passwords, JWTs (kid rotation), TOTP, hashing, signed tokens, secret encryption — Prompts/00 §3.18, Prompts/02 §02.6.

Phase 02 additions: access tokens carry the session id (``sid``) and, during impersonation, ``imp`` / ``imp_log`` /
``imp_ro`` claims; ``create_limited_token`` mints the short-lived ``mfa_setup`` token handed out with
``403 MFA_REQUIRED``; ``encrypt_secret`` / ``decrypt_secret`` protect TOTP secrets at rest (AES-GCM keyed from
``INTEGRATION_ENCRYPTION_KEY``); ``check_password_policy`` implements rule 5 (≥ 10 chars, 3 of 4 classes).
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import string
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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


_CLASSES = (re.compile(r"[a-z]"), re.compile(r"[A-Z]"), re.compile(r"\d"), re.compile(r"[^A-Za-z0-9]"))


def check_password_policy(password: str, history: list[str] | None = None) -> None:
    """Rule 5: ≥ ``PASSWORD_MIN_LENGTH`` chars, 3 of 4 character classes, not one of the last N hashes."""
    problems: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"at least {settings.PASSWORD_MIN_LENGTH} characters")
    if sum(1 for c in _CLASSES if c.search(password)) < 3:
        problems.append("3 of 4 character classes (lower, upper, digit, symbol)")
    if problems:
        raise APIError(
            422, ErrorCode.VALIDATION, "Password does not meet the policy", {"field": "password", "policy": problems}
        )
    for old in history or []:
        if verify_password(password, old):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Password was used recently (last {settings.PASSWORD_HISTORY} passwords cannot be reused)",
                {"field": "password"},
            )


def generate_temp_password(length: int = 12) -> str:
    """Temporary password that satisfies the policy (credential sheets, admin resets)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pwd = (
            "".join(secrets.choice(alphabet) for _ in range(length - 2))
            + secrets.choice("!@#$%&*")
            + secrets.choice(string.digits)
        )
        if sum(1 for c in _CLASSES if c.search(pwd)) >= 3:
            return pwd


# ---- JWT with kid rotation -----------------------------------------------------------------------------------
# HS256 (shared secret) by default; RS256 when ``JWT_RSA_PRIVATE_KEY`` is set (Phase 43) — rotation deploys a new
# private key under a new ``JWT_KID`` and moves the old public key into ``JWT_RSA_PREVIOUS_PUBLIC_KEYS`` for the grace
# window (access-token lifetime + refresh lifetime); ``/.well-known/jwks.json`` publishes the public keys.
def _keys() -> dict[str, str]:
    return {settings.JWT_KID: settings.SECRET_KEY, **settings.JWT_PREVIOUS_KEYS}


def _rsa_public_keys() -> dict[str, str]:
    if not settings.JWT_RSA_PRIVATE_KEY:
        return {}
    from cryptography.hazmat.primitives import serialization

    priv = serialization.load_pem_private_key(settings.JWT_RSA_PRIVATE_KEY.encode(), password=None)
    pub = (
        priv.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return {settings.JWT_KID: pub, **settings.JWT_RSA_PREVIOUS_PUBLIC_KEYS}


def jwks() -> dict[str, Any]:
    """JWK set of the RS256 public keys (empty when the platform runs HS256)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

    def b64(n: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()

    keys = []
    for kid, pem in _rsa_public_keys().items():
        pub = serialization.load_pem_public_key(pem.encode())
        if isinstance(pub, RSAPublicKey):
            nums = pub.public_numbers()
            keys.append({"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": b64(nums.n), "e": b64(nums.e)})
    return {"keys": keys}


def signing_algorithm() -> str:
    return "RS256" if settings.JWT_RSA_PRIVATE_KEY else ALGORITHM


def _encode(claims: dict[str, Any], expires: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "iat": int(now.timestamp()), "exp": int((now + expires).timestamp())}
    if settings.JWT_RSA_PRIVATE_KEY:
        return str(jwt.encode(payload, settings.JWT_RSA_PRIVATE_KEY, algorithm="RS256", headers={"kid": settings.JWT_KID}))
    return str(jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM, headers={"kid": settings.JWT_KID}))


def create_access_token(
    sub: uuid.UUID | str,
    institution_id: uuid.UUID | str | None,
    is_super_admin: bool = False,
    jti: str | None = None,
    *,
    session_id: uuid.UUID | str | None = None,
    extra: dict[str, Any] | None = None,
    minutes: int | None = None,
) -> str:
    claims: dict[str, Any] = {
        "sub": str(sub),
        "type": "access",
        "inst": str(institution_id) if institution_id else None,
        "sa": is_super_admin,
        "jti": jti or uuid.uuid4().hex,
    }
    if session_id:
        claims["sid"] = str(session_id)
    if extra:
        claims.update(extra)
    return _encode(claims, timedelta(minutes=minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(sub: uuid.UUID | str, family: str, jti: str | None = None) -> str:
    """Refresh tokens rotate; ``family`` ties rotations together so reuse revokes the whole family."""
    return _encode(
        {"sub": str(sub), "type": "refresh", "family": family, "jti": jti or uuid.uuid4().hex},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_limited_token(sub: uuid.UUID | str, purpose: str, minutes: int, **extra: Any) -> str:
    """Short-lived single-purpose token (``type`` = purpose): e.g. ``mfa_setup`` handed out with 403 MFA_REQUIRED."""
    return _encode({"sub": str(sub), "type": purpose, "jti": uuid.uuid4().hex, **extra}, timedelta(minutes=minutes))


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid", settings.JWT_KID)
        if header.get("alg") == "RS256":
            key = _rsa_public_keys().get(kid)
            algorithms = ["RS256"]
        else:
            key = _keys().get(kid)
            algorithms = [ALGORITHM]
        if not key:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Unknown signing key")
        claims: dict[str, Any] = jwt.decode(token, key, algorithms=algorithms)
    except JWTError:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid or expired token") from None
    if claims.get("type") != expected_type:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, f"Expected a {expected_type} token")
    return claims


def token_ttl_seconds(claims: dict[str, Any]) -> int:
    """Seconds until ``exp`` (≥ 1) — used to blacklist a JTI for exactly its remaining lifetime."""
    return max(1, int(claims.get("exp", 0)) - int(time.time()))


# ---- TOTP MFA ------------------------------------------------------------------------------------------------
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=settings.APP_NAME)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def generate_recovery_codes(n: int = 10) -> list[str]:
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]


# ---- secret encryption (TOTP secrets, integration credentials) --------------------------------------------------
def _aes_key() -> bytes:
    raw = settings.INTEGRATION_ENCRYPTION_KEY
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except ValueError:
        pass
    return hashlib.sha256(raw.encode("utf-8")).digest()  # any string works; production sets base64 32 bytes


def encrypt_secret(plain: str) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(_aes_key()).encrypt(nonce, plain.encode("utf-8"), None)


def decrypt_secret(blob: bytes) -> str:
    data = bytes(blob)
    return AESGCM(_aes_key()).decrypt(data[:12], data[12:], None).decode("utf-8")


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
