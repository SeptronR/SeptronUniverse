"""Public verification of ID cards — Prompts/07 §07.8 ``GET /verify/{token}`` (public; listed in ``PUBLIC_ROUTES``).

The signed token printed as the ID card's QR names the institution and the student; the answer is the holder's name,
registration number, programme and status (``valid=false`` with a message for an expired / tampered token or a
student who left). Phase 15: grade-card QR tokens (48 hex characters) answer the term summary, the result hash and
whether a revised card superseded it. Phase 16: transcript tokens (``tr`` + 48 hex) answer the holder, CGPA, credits, the
result hash and ``superseded`` after a later result version. Phase 18: degree (``dg``) and provisional (``pv``) tokens
resolve first through ``verification_service.verify_any`` (the single resolver); ``POST /verify/bulk`` serves
employers (captcha + rate limit). Phase 26 moves the registry to ``issued_documents``.
"""

from typing import Any

from fastapi import APIRouter, Request

from app.core.rate_limit import rate_limited, verify_captcha
from app.schemas.common import Envelope
from app.schemas.degrees import BulkVerifyRequest, DegreeVerifyResponse
from app.schemas.post_result import TranscriptVerifyResponse
from app.schemas.results import ResultVerifyResponse
from app.schemas.students import VerifyResponse
from app.utils.response import ok

router = APIRouter(tags=["public"])
AnyVerify = DegreeVerifyResponse | VerifyResponse | ResultVerifyResponse | TranscriptVerifyResponse


@router.get(
    "/verify/{token}",
    summary="Verify a degree / provisional / grade card / transcript / ID card QR token (public)",
    response_model=Envelope[AnyVerify],
    dependencies=[rate_limited("verify_token", limit=60, window=60)],
)
async def verify(token: str) -> dict[str, Any]:
    from app.services.degrees.verification_service import verify_any

    return ok(await verify_any(token))


@router.post(
    "/verify/bulk",
    summary="Employer bulk verification (captcha, rate-limited)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=[rate_limited("verify_bulk", limit=10, window=60)],
)
async def verify_bulk(body: BulkVerifyRequest, request: Request) -> dict[str, Any]:
    from app.services.degrees.verification_service import verify_any

    await verify_captcha(
        body.captcha_token or request.headers.get("x-captcha-token"), request.client.host if request.client else None
    )
    out = []
    for token in body.tokens:
        res = await verify_any(token.strip())
        out.append({"token": token, **(res.model_dump(mode="json") if hasattr(res, "model_dump") else dict(res))})
    return ok(out)
