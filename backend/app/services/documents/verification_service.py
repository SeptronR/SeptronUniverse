"""Unified public verification — Prompts/26 §26.6 ``verification_service``.

``verify_document(token)`` looks the token up in ``issued_documents`` (platform session — the tenant is the row's)
and answers validity, type, number, issue date, masked holder (initials + masked registration number), institution,
``content_hash`` and revoked / superseded state. Back-filled rows keep their original tokens, so the per-phase QR
codes (ID cards, hall tickets, grade cards, transcripts, degrees) resolve here first; the older verifiers still add
their type-specific ``details`` (and their own revocation state) when they recognise the token. Tokens unknown to the
register fall through to those verifiers unchanged.

``verify_hash(pdf)`` hashes an uploaded PDF against ``content_hash`` — a watermarked download never matches (the
answer hints at that). The verification log (``documents_meta`` ``verifylog:<yyyy-mm-dd>``: counts per type and
outcome, no PII) is for audit; the public setting ``documents.verify_shows_pdf`` adds a short-lived signed URL.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from app.models.documents import IssuedDocument
from app.models.platform import Institution
from app.schemas.documents import DocHashVerifyOut, DocVerifyOut
from app.services.documents.common import mask_holder


async def _holder(db: Any, d: IssuedDocument) -> str | None:
    from app.models.hr import Staff
    from app.models.students import Student

    if d.person_id is None:
        return None
    if d.person_type == "staff":
        s = (await db.execute(select(Staff).where(Staff.id == d.person_id))).scalar_one_or_none()
        return mask_holder(" ".join(x for x in (s.first_name, s.last_name) if x), s.employee_id) if s else None
    st = (await db.execute(select(Student).where(Student.id == d.person_id))).scalar_one_or_none()
    return mask_holder(st.full_name, st.registration_number) if st else None


async def _meta(db: Any, d: IssuedDocument) -> dict[str, Any]:
    v = (
        await db.execute(
            text(
                "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                "AND category = 'documents_meta' AND key = :k"
            ),
            {"i": d.institution_id, "k": f"doc:{d.id}"},
        )
    ).scalar_one_or_none()
    if isinstance(v, str):
        v = json.loads(v)
    return v if isinstance(v, dict) else {}


async def _log(db: Any, institution_id: Any, template_type: str | None, outcome: str) -> None:
    """Counts per day × type × outcome (no tokens, no holders)."""
    day = datetime.now(UTC).date().isoformat()
    key = f"verifylog:{day}"
    row = (
        await db.execute(
            text(
                "SELECT id, value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                "AND category = 'documents_meta' AND key = :k"
            ),
            {"i": institution_id, "k": key},
        )
    ).first()
    value: dict[str, Any] = (json.loads(row[1]) if isinstance(row[1], str) else dict(row[1] or {})) if row else {}
    k = f"{template_type or 'unknown'}:{outcome}"
    value[k] = int(value.get(k) or 0) + 1
    if row:
        await db.execute(
            text("UPDATE institution_settings SET value = CAST(:v AS jsonb) WHERE id = :id"),
            {"v": json.dumps(value), "id": row[0]},
        )
    else:
        await db.execute(
            text(
                "INSERT INTO institution_settings (institution_id, college_id, category, key, value, value_type) "
                "VALUES (:i, NULL, 'documents_meta', :k, CAST(:v AS jsonb), 'json')"
            ),
            {"i": institution_id, "k": key, "v": json.dumps(value)},
        )


async def describe(db: Any, d: IssuedDocument) -> DocVerifyOut:
    inst = (await db.execute(select(Institution.name).where(Institution.id == d.institution_id))).scalar_one_or_none()
    m = await _meta(db, d)
    revoked = d.revoked_at is not None
    superseded = None
    if m.get("superseded_by"):
        nd = (
            await db.execute(select(IssuedDocument.document_number).where(IssuedDocument.id == m["superseded_by"]))
        ).scalar_one_or_none()
        superseded = nd or str(m["superseded_by"])
    reason = d.revoke_reason
    return DocVerifyOut(
        valid=not revoked,
        template_type=d.template_type,
        document_number=d.document_number,
        issued_at=d.issued_at,
        holder_masked=await _holder(db, d),
        institution=inst,
        revoked=revoked,
        revoke_reason=reason,
        content_hash=d.content_hash,
        superseded_by=superseded,
        message="Revoked" if revoked else "Valid document",
    )


async def verify_document(token: str) -> DocVerifyOut | None:
    """``None`` when the token is not in the register (callers fall through to the per-phase verifiers)."""
    from app.db.session import PlatformSessionLocal

    if not token or len(token) > 64:
        return None
    async with PlatformSessionLocal() as db:
        d = (
            await db.execute(select(IssuedDocument).where(IssuedDocument.verification_token == token))
        ).scalar_one_or_none()
        if d is None:
            return None
        out = await describe(db, d)
        try:
            shows = (
                await db.execute(
                    text(
                        "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                        "AND category = 'documents' AND key = 'verify_shows_pdf'"
                    ),
                    {"i": d.institution_id},
                )
            ).scalar_one_or_none()
            if shows in (True, "true") and not out.revoked:
                from app.core.files import get_storage

                out.pdf_url = get_storage().signed_url(d.pdf_url, 300)
            await _log(db, d.institution_id, d.template_type, "revoked" if out.revoked else "valid")
            await db.commit()
        except Exception:  # noqa: BLE001 - the log / pdf link never blocks a verification answer
            await db.rollback()
        return out


async def verify_hash(data: bytes) -> DocHashVerifyOut:
    from app.db.session import PlatformSessionLocal

    digest = hashlib.sha256(data).hexdigest()
    async with PlatformSessionLocal() as db:
        d = (
            await db.execute(select(IssuedDocument).where(IssuedDocument.content_hash == digest).limit(1))
        ).scalar_one_or_none()
        if d is None:
            hint = (
                "This looks like a watermarked download — verify the QR token instead, or ask the institution for the "
                "original."
                if b"Downloaded by" in data
                else "No issued document has this exact file hash."
            )
            return DocHashVerifyOut(valid=False, hint=hint)
        inst = (
            await db.execute(select(Institution.name).where(Institution.id == d.institution_id))
        ).scalar_one_or_none()
        try:
            await _log(db, d.institution_id, d.template_type, "hash_match")
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
        return DocHashVerifyOut(
            valid=d.revoked_at is None,
            document_number=d.document_number,
            template_type=d.template_type,
            institution=inst,
            revoked=d.revoked_at is not None,
            hint="Revoked by the institution" if d.revoked_at else None,
        )


async def verify_unified(token: str) -> Any:
    """``GET /verify/{token}``: the register first (with the legacy verifier's details), else the legacy chain."""
    from app.services.degrees.verification_service import verify_any

    doc = await verify_document(token)
    legacy: Any = None
    try:
        legacy = await verify_any(token)
    except Exception:  # noqa: BLE001 - legacy verifiers raise for tokens they do not know
        legacy = None
    if doc is None:
        return legacy
    if legacy is not None:
        details = legacy.model_dump(mode="json") if hasattr(legacy, "model_dump") else dict(legacy)
        doc.details = details
        if details.get("valid") is False and not doc.revoked:
            doc.valid = False
            doc.message = details.get("message") or "Superseded or withdrawn"
        if details.get("superseded") and not doc.superseded_by:
            doc.superseded_by = str(details.get("superseded"))
    return doc
