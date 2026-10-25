"""Public verification of ID cards — Prompts/07 §07.8 ``GET /verify/{token}`` (public; listed in ``PUBLIC_ROUTES``).

The signed token printed as the ID card's QR names the institution and the student; the answer is the holder's name,
registration number, programme and status (``valid=false`` with a message for an expired / tampered token or a
student who left). Phase 15: grade-card QR tokens (48 hex characters) answer the term summary, the result hash and
whether a revised card superseded it. Phase 16: transcript tokens (``tr`` + 48 hex) answer the holder, CGPA, credits, the
result hash and ``superseded`` after a later result version. Phase 18: degree (``dg``) and provisional (``pv``) tokens
resolve first through ``verification_service.verify_any`` (the single resolver); ``POST /verify/bulk`` serves
employers (captcha + rate limit). Phase 26: the unified register ``issued_documents`` answers first
(``verification_service.verify_unified`` — masked holder, hash, revoked / superseded, plus the older verifier's
``details``); ``POST /verify/hash`` checks an uploaded PDF against the registered ``content_hash``.
"""

from typing import Any

from fastapi import APIRouter, File, Request, UploadFile

from app.core.rate_limit import rate_limited, verify_captcha
from app.schemas.common import Envelope
from app.schemas.degrees import BulkVerifyRequest, DegreeVerifyResponse
from app.schemas.documents import DocHashVerifyOut, DocVerifyOut
from app.schemas.post_result import TranscriptVerifyResponse
from app.schemas.results import ResultVerifyResponse
from app.schemas.students import VerifyResponse
from app.utils.response import ok

router = APIRouter(tags=["public"])
AnyVerify = DocVerifyOut | DegreeVerifyResponse | VerifyResponse | ResultVerifyResponse | TranscriptVerifyResponse


@router.get(
    "/verify/{token}",
    summary="Verify any issued document's QR token (unified register; public)",
    response_model=Envelope[AnyVerify],
    dependencies=[rate_limited("verify_token", limit=60, window=60)],
)
async def verify(token: str) -> dict[str, Any]:
    from app.services.documents.verification_service import verify_unified

    return ok(await verify_unified(token))


@router.post(
    "/verify/hash",
    summary="Verify an uploaded PDF by its SHA-256 (public)",
    response_model=Envelope[DocHashVerifyOut],
    dependencies=[rate_limited("verify_hash", limit=20, window=60)],
)
async def verify_hash(file: UploadFile = File(...)) -> dict[str, Any]:
    from app.services.documents.verification_service import verify_hash as by_hash

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        from app.core.errors import APIError, ErrorCode

        raise APIError(422, ErrorCode.VALIDATION, "File exceeds 20 MB")
    return ok(await by_hash(data))


@router.post(
    "/verify/bulk",
    summary="Employer bulk verification (captcha, rate-limited)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=[rate_limited("verify_bulk", limit=10, window=60)],
)
async def verify_bulk(body: BulkVerifyRequest, request: Request) -> dict[str, Any]:
    from app.services.documents.verification_service import verify_unified

    await verify_captcha(
        body.captcha_token or request.headers.get("x-captcha-token"), request.client.host if request.client else None
    )
    out = []
    for token in body.tokens:
        res = await verify_unified(token.strip())
        if res is None:
            out.append({"token": token, "valid": False, "message": "Unknown token"})
            continue
        out.append({"token": token, **(res.model_dump(mode="json") if hasattr(res, "model_dump") else dict(res))})
    return ok(out)
