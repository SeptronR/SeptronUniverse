"""Public verification of ID cards — Prompts/07 §07.8 ``GET /verify/{token}`` (public; listed in ``PUBLIC_ROUTES``).

The signed token printed as the ID card's QR names the institution and the student; the answer is the holder's name,
registration number, programme and status (``valid=false`` with a message for an expired / tampered token or a
student who left). Phase 26 replaces this with the unified verification endpoint over ``issued_documents``.
"""

from typing import Any

from fastapi import APIRouter

from app.schemas.common import Envelope
from app.schemas.students import VerifyResponse
from app.services.student_records_service import verify_token
from app.utils.response import ok

router = APIRouter(tags=["public"])


@router.get("/verify/{token}", summary="Verify an ID card QR token (public)", response_model=Envelope[VerifyResponse])
async def verify(token: str) -> dict[str, Any]:
    return ok(await verify_token(token))
