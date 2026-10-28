"""Google service-account OAuth (JWT bearer grant) for FCM / Meet / Workspace providers — Prompts/41 §41.6."""

import json
import time

import jwt

from app.integrations.base import IntegrationFailed

TOKEN_URL = "https://oauth2.googleapis.com/token"


async def service_account_token(sa_json: str, scope: str, subject: str = "") -> str:
    import httpx

    try:
        sa = json.loads(sa_json)
    except ValueError as exc:
        raise IntegrationFailed("google", "BAD_CREDENTIALS", "Service account JSON is invalid") from exc
    now = int(time.time())
    claims = {"iss": sa["client_email"], "scope": scope, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}
    if subject:
        claims["sub"] = subject
    assertion = jwt.encode(claims, sa["private_key"], algorithm="RS256")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        )
    if r.status_code != 200:
        raise IntegrationFailed("google", f"HTTP_{r.status_code}", "Google token exchange failed")
    return str(r.json()["access_token"])
