"""``Idempotency-Key`` dependency — Prompts/00_PREREQUISITE_Project_Setup.md §3.15 (docs/Technical_Architecture.md §5).

Non-idempotent POSTs declare ``key: str | None = Depends(idempotency_key)`` and call ``await store(request, body)``
after success. A replay with the same key and payload returns the stored response (``IDEMPOTENT_REPLAY``); the same
key with a different payload is a ``409 CONFLICT``. Redis holds the record for 24 h and it is mirrored to
``idempotency_keys`` for audit.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client

TTL_SECONDS = 24 * 3600


async def idempotency_key(request: Request) -> str | None:
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    body = await request.body()
    digest = hashlib.sha256(body).hexdigest()
    user = getattr(request.state, "user_id", None) or "anon"
    redis_key = f"idem:{user}:{request.url.path}:{key}"
    stored = await redis_client.get(redis_key)
    if stored:
        data = json.loads(stored)
        if data["hash"] != digest:
            raise APIError(409, ErrorCode.CONFLICT, "Idempotency-Key reused with a different payload")
        # The api_error_handler turns this into the stored 200 response; clients unwrap error.details.response
        raise APIError(200, ErrorCode.IDEMPOTENT_REPLAY, "Replay", {"response": data["response"]})
    request.state.idem = (redis_key, digest, key)
    return key


async def store(
    request: Request, response_body: dict[str, Any], db: AsyncSession | None = None, status_code: int = 200
) -> None:
    """Persist the successful response for the request's Idempotency-Key (no-op when the header was absent)."""
    idem = getattr(request.state, "idem", None)
    if not idem:
        return
    redis_key, digest, key = idem
    await redis_client.set(redis_key, json.dumps({"hash": digest, "response": response_body}), ex=TTL_SECONDS)
    if db is not None:
        from app.models.platform import IdempotencyKey

        db.add(
            IdempotencyKey(
                institution_id=getattr(request.state, "institution_id", None) or None,
                user_id=getattr(request.state, "user_id", None) or None,
                idempotency_key=key,
                route=request.url.path,
                request_hash=digest,
                status="completed",
                response_code=status_code,
                response_body=response_body,
                expires_at=datetime.now(UTC) + timedelta(seconds=TTL_SECONDS),
            )
        )
        await db.flush()
