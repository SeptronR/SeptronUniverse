"""Signed, time-limited, watermarked downloads — Prompts/26 §26.6 ``download_service``
({documents.watermark_signed_links}).

A link is ``/api/v1/documents/download/{signed}`` where ``signed`` is an HMAC-signed payload (``core.security``) naming
the document, the requesting user, the institution, the watermark text, the purpose and a nonce; default TTL 15 min
(setting ``documents.signed_link_ttl_minutes``). Downloading needs a signed-in caller who is the bound user (403
otherwise); an expired link answers 410, a used single-use link 410. Sensitive types (transcript, grade card) and any
link with watermark text are re-rendered from the stored template version with "Downloaded by <name> on <date>"; the
register's ``content_hash`` keeps referring to the unwatermarked original (legacy back-filled PDFs without a template
get the stamp as a trailing PDF comment, which also changes the hash). Downloads are counted in ``documents_meta``
``doc:<id>.downloads`` and audited (``documents.downloaded``).

With the feature off the endpoint degrades to the file service's plain signed URL (no watermark, no binding).
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.enums.documents import SENSITIVE_TYPES
from app.models.documents import DocumentTemplate, IssuedDocument
from app.schemas.documents import DocSignedLinkOut, DocSignedLinkRequest
from app.services.documents.common import DocumentsBase, forbidden, not_found
from app.services.documents.render_service import RenderService, pdf_bytes


def _sign(payload: dict[str, Any]) -> str:
    data = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode()
    sig = hmac.new(settings.SECRET_KEY.encode(), f"doc-link:{data}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{data}.{sig}"


def _unsign(token: str) -> dict[str, Any]:
    try:
        data, sig = token.rsplit(".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode(), f"doc-link:{data}".encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature")
        body: dict[str, Any] = json.loads(base64.urlsafe_b64decode(data.encode()))
    except (ValueError, json.JSONDecodeError):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown or tampered link") from None
    if int(body.get("exp", 0)) < int(time.time()):
        raise APIError(410, ErrorCode.RULE_VIOLATION, "The download link has expired", {"code": "LINK_EXPIRED"})
    return body


class DownloadService(DocumentsBase):
    async def signed_link(self, did: uuid.UUID, body: DocSignedLinkRequest) -> DocSignedLinkOut:
        d = await self.visible_document(did)
        ttl = int(body.ttl_minutes or await self.doc_setting("signed_link_ttl_minutes", 15))
        expires = datetime.now(UTC) + timedelta(minutes=ttl)
        if not await self.feature("documents.watermark_signed_links"):
            from app.core.files import get_storage

            return DocSignedLinkOut(
                url=get_storage().signed_url(d.pdf_url, ttl * 60), expires_at=expires, watermarked=False
            )
        if self.actor_id is None:
            raise forbidden("Sign in to create a download link")
        mark = body.watermark_text
        if mark is None and (d.template_type in SENSITIVE_TYPES or not self.office()):
            name = (await self.user_names([self.actor_id])).get(self.actor_id) or "user"
            mark = f"Downloaded by {name} on {(await self.today()).strftime('%d-%m-%Y')}"
            if body.purpose:
                mark += f" · {body.purpose}"
        token = _sign(
            {
                "d": str(d.id),
                "u": str(self.actor_id),
                "i": str(self.inst),
                "w": (mark or "")[:120],
                "p": (body.purpose or "")[:120],
                "n": secrets.token_hex(8),
                "s": 1 if body.single_use else 0,
                "exp": int(expires.timestamp()),
            }
        )
        return DocSignedLinkOut(url=f"/api/v1/documents/download/{token}", expires_at=expires, watermarked=bool(mark))

    async def download(self, token: str) -> tuple[bytes, str]:
        body = _unsign(token)
        if str(body.get("i")) != str(self.inst):
            raise not_found("Document")
        if self.actor_id is None or str(body.get("u")) != str(self.actor_id):
            raise forbidden("This link was issued to another user")
        doc = (
            await self.db.execute(
                select(IssuedDocument).where(
                    IssuedDocument.id == uuid.UUID(str(body["d"])), IssuedDocument.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if doc is None:
            raise not_found("Document")
        m = await self.meta("doc", doc.id)
        used = set(m.get("used_links") or [])
        if body.get("s") and body.get("n") in used:
            raise APIError(410, ErrorCode.RULE_VIOLATION, "The link was already used", {"code": "LINK_USED"})
        r = RenderService(self.db, self.principal, self.request, self.inst)
        mark = str(body.get("w") or "")
        data = await self.watermarked(r, doc, mark) if mark else await r.original_pdf(doc)
        log = list(m.get("downloads") or [])[-199:]
        log.append({"at": datetime.now(UTC).isoformat(), "by": str(self.actor_id), "purpose": body.get("p") or None})
        m["downloads"], m["download_count"] = log, int(m.get("download_count") or 0) + 1
        if body.get("s"):
            m["used_links"] = [*used, body.get("n")][-200:]
        await self.put_meta("doc", doc.id, m)
        await self._audit("download", "issued_document", doc.id, None, {"watermarked": bool(mark)})
        await self._emit("documents.downloaded", {"document_id": str(doc.id)}, "issued_document", doc.id)
        return data, f"{doc.document_number.replace('/', '-')}.pdf"

    async def watermarked(self, r: RenderService, d: IssuedDocument, mark: str) -> bytes:
        tpl = await self.db.get(DocumentTemplate, d.template_id) if d.template_id else None
        if tpl is None or not d.entity_type or not d.entity_id:
            original = await r.original_pdf(d)
            return original + f"\n% {mark}\n".encode("latin-1", "replace")
        m = await self.meta("doc", d.id)
        ctx, _, _ = await r.context(d.template_type, d.entity_type, d.entity_id, m.get("variables_override"))
        ctx["document"] = {
            "number": d.document_number,
            "serial_no": d.serial_no or "",
            "issued_on": d.issued_at.strftime("%d-%m-%Y"),
            "verify_url": f"/verify/{d.verification_token}",
        }
        from app.services.documents.render_service import qr_data_url

        ctx["document"]["qr"] = qr_data_url(ctx["document"]["verify_url"])
        ctx["watermark"] = mark
        return pdf_bytes(r.render_html(tpl, ctx), tpl.name, mark)
