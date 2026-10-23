"""Public verification of ID cards — Prompts/07 §07.8 ``GET /verify/{token}`` (public; listed in ``PUBLIC_ROUTES``).

The signed token printed as the ID card's QR names the institution and the student; the answer is the holder's name,
registration number, programme and status (``valid=false`` with a message for an expired / tampered token or a
student who left). Phase 15: grade-card QR tokens (48 hex characters) answer the term summary, the result hash and
whether a revised card superseded it. Phase 16: transcript tokens (``tr`` + 48 hex) answer the holder, CGPA, credits, the
result hash and ``superseded`` after a later result version. Phase 26 replaces this with the unified verification endpoint over ``issued_documents``.
"""

from typing import Any

from fastapi import APIRouter

from app.schemas.common import Envelope
from app.schemas.post_result import TranscriptVerifyResponse
from app.schemas.results import ResultVerifyResponse
from app.schemas.students import VerifyResponse
from app.services.student_records_service import verify_token
from app.utils.response import ok

router = APIRouter(tags=["public"])


@router.get(
    "/verify/{token}",
    summary="Verify an ID card / grade card / transcript QR token (public)",
    response_model=Envelope[VerifyResponse | ResultVerifyResponse | TranscriptVerifyResponse],
)
async def verify(token: str) -> dict[str, Any]:
    from app.services.post_result.transcript_service import verify_transcript
    from app.services.results.grade_card_service import verify_grade_card

    transcript = await verify_transcript(token)
    if transcript is not None:
        return ok(transcript)

    card = await verify_grade_card(token)
    if card is not None:
        return ok(card)
    return ok(await verify_token(token))
