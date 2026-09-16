"""Redis fixed-window rate limiter + captcha hook — Prompts/00 §2 tree (docs/Technical_Architecture.md §11).

Usage on public routes: ``dependencies=[rate_limited("otp", limit=5, window=60)]``; ``verify_captcha(token)`` on
public forms when ``CAPTCHA_PROVIDER`` is not ``none``.
"""

from typing import Any

import httpx
from fastapi import Depends, Request

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    user = getattr(request.state, "user_id", None)
    return str(user) if user else ip


async def check_rate(bucket: str, identity: str, limit: int, window: int) -> None:
    """Fixed window: ``rl:{bucket}:{identity}`` counter with TTL = window; raise ``429 RATE_LIMITED`` when exceeded."""
    key = f"rl:{bucket}:{identity}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, window)
    if count > limit:
        ttl = await redis_client.ttl(key)
        raise APIError(429, ErrorCode.RATE_LIMITED, "Too many requests", {"retry_after": max(ttl, 1)})


def rate_limited(bucket: str, limit: int = 60, window: int = 60) -> Any:
    async def _dep(request: Request) -> None:
        await check_rate(bucket, _client_key(request), limit, window)

    return Depends(_dep)


CAPTCHA_VERIFY_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "recaptcha": "https://www.google.com/recaptcha/api/siteverify",
    "hcaptcha": "https://hcaptcha.com/siteverify",
}


async def verify_captcha(token: str | None, remote_ip: str | None = None) -> None:
    """Verify a captcha token with the configured provider; a no-op when ``CAPTCHA_PROVIDER=none``."""
    provider = settings.CAPTCHA_PROVIDER
    if provider == "none":
        return
    if not token:
        raise APIError(400, ErrorCode.VALIDATION, "Captcha token required", {"field": "captcha_token"})
    url = CAPTCHA_VERIFY_URLS.get(provider)
    if not url:
        raise APIError(500, ErrorCode.INTERNAL, f"Unknown captcha provider {provider!r}")
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.post(
            url, data={"secret": settings.CAPTCHA_SECRET, "response": token, "remoteip": remote_ip}
        )
    if not resp.json().get("success"):
        raise APIError(400, ErrorCode.VALIDATION, "Captcha verification failed", {"field": "captcha_token"})
