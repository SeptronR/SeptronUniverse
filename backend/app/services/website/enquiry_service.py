"""Website enquiries — Prompts/40 §40.6 ``enquiry_service`` (``website.enquiry``).

Business rules
1. Public form: captcha (Phase 01 ``verify_captcha``), honeypot (``website`` field filled → stored as ``spam`` and
   answered 200 so bots learn nothing), per-IP limit ``website.enquiry_rate_limit`` (``5/10m``), spam score (links,
   disposable domains, all-caps) — score ≥ 3 → ``spam``.
2. A clean enquiry creates / links the Phase 08 CRM ``enquiries`` row (``source='web'``) when
   ``admissions.enquiry_crm`` is on, notifies admissions (``website.enquiry_received``) and acknowledges the enquirer
   (``website.enquiry_ack`` with the DPDP notice version, ``direct_contacts``).
3. Admin list (``website:view`` or ``admissions:create``): phone / e-mail masked without ``admissions:view_pii``;
   status changes / CRM link audited; status follows the CRM stage (consumer of ``enquiry.stage_changed``).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select, text

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.notifications.notify import notify_event
from app.core.rate_limit import check_rate, verify_captcha
from app.enums.website import DISPOSABLE_DOMAINS, STAGE_TO_STATUS
from app.models.website import WebsiteEnquiry
from app.schemas.website import PublicEnquiryIn, PublicEnquiryOut, WebsiteEnquiryOut
from app.services.website.common import WebsiteBase

DPDP_NOTICE_VERSION = "2026-01"


def parse_rate(spec: str | None) -> tuple[int, int]:
    m = re.match(r"^(\d+)/(\d+)([smh])$", spec or "")
    if not m:
        return 5, 600
    n, w, unit = int(m.group(1)), int(m.group(2)), m.group(3)
    return n, w * {"s": 1, "m": 60, "h": 3600}[unit]


def spam_score(body: PublicEnquiryIn) -> int:
    score = len(re.findall(r"https?://", body.message or "")) * 2
    if body.email and body.email.split("@")[-1].lower() in DISPOSABLE_DOMAINS:
        score += 2
    letters = [c for c in body.message if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8 and len(letters) > 20:
        score += 1
    return score


def _mask(v: str | None) -> str | None:
    if not v:
        return v
    return v[:2] + "•" * max(0, len(v) - 4) + v[-2:]


class EnquiryService(WebsiteBase):
    # ---- rule 1 / 2 -----------------------------------------------------------------------------------------------
    async def submit(self, body: PublicEnquiryIn, request: Request) -> PublicEnquiryOut:
        ip = request.client.host if request.client else "unknown"
        limit, window = parse_rate(await self.setting("enquiry_rate_limit"))
        await check_rate(f"site_enquiry:{self.inst}", ip, limit, window)
        await verify_captcha(body.captcha_token, ip)
        score = spam_score(body)
        status = "spam" if body.website or score >= 3 else "new"
        row = WebsiteEnquiry(
            institution_id=self.inst,
            name=body.name,
            email=body.email,
            phone=body.phone,
            subject=body.subject,
            message=body.message,
            source_page=body.source_page or request.headers.get("referer", "")[:200] or None,
            status=status,
        )
        self.db.add(row)
        await self.db.flush()
        await self.put_meta(
            f"enquiry:{row.id}",
            {
                "spam_score": score,
                "honeypot": bool(body.website),
                "dpdp": DPDP_NOTICE_VERSION,
                "host": request.headers.get("host"),
            },
        )
        reference = f"WEB-{str(row.id)[:8].upper()}"
        if status == "spam":
            return PublicEnquiryOut(reference=reference)
        if await is_enabled(self.inst, "admissions.enquiry_crm"):
            await self._link(row, body.program_interest)
        await notify_event(
            self.db,
            self.inst,
            "website.enquiry_received",
            audience={"roles": ["admissions_officer"]},
            context={
                "name": row.name,
                "subject": row.subject or "",
                "reference": reference,
                "route": "/admin/website/enquiries",
            },
        )
        contacts = [{"channel": "email", "to": row.email}] if row.email else []
        if row.phone:
            contacts.append({"channel": "sms", "to": row.phone})
        if contacts:
            await notify_event(
                self.db,
                self.inst,
                "website.enquiry_ack",
                audience={"direct_contacts": contacts},
                context={"name": row.name, "reference": reference, "dpdp_version": DPDP_NOTICE_VERSION},
                channels=[c["channel"] for c in contacts],
            )
        await self.emit("website.enquiry_received", {"id": str(row.id), "linked": bool(row.enquiry_id)}, row.id)
        return PublicEnquiryOut(reference=reference)

    async def _link(self, row: WebsiteEnquiry, program_interest: str | None) -> None:
        from app.schemas.admissions import EnquiryCreate
        from app.services.admissions.enquiry_service import EnquiryService as CrmService

        crm = await CrmService(self.db, None, self.request, institution_id=self.inst).create(
            EnquiryCreate(
                name=row.name,
                phone=row.phone,
                email=row.email,
                source="web",
                program_interest=[program_interest] if program_interest else None,
                note=" · ".join(
                    p for p in (row.subject, row.message, f"page: {row.source_page}" if row.source_page else None) if p
                )[:2000]
                or None,
            ),
            source="web",
        )
        row.enquiry_id = crm.id
        await self.db.flush()
        await self.emit("website.enquiry_linked", {"id": str(row.id), "enquiry_id": str(crm.id)}, row.id)

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    def _reader(self) -> None:
        if not (self.can("view") or (self.principal and self.principal.has("admissions", "create"))):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")

    async def list(self, status: str | None, q: str | None) -> list[WebsiteEnquiryOut]:
        self._reader()
        stmt = select(WebsiteEnquiry).where(WebsiteEnquiry.institution_id == self.inst)
        if status:
            stmt = stmt.where(WebsiteEnquiry.status == status)
        if q:
            stmt = stmt.where(WebsiteEnquiry.name.ilike(f"%{q}%") | WebsiteEnquiry.subject.ilike(f"%{q}%"))
        pii = bool(self.principal and self.principal.has("admissions", "view_pii"))
        out = []
        for r in (await self.db.execute(stmt.order_by(WebsiteEnquiry.created_at.desc()).limit(500))).scalars():
            o = WebsiteEnquiryOut.model_validate(r)
            o.spam_score = int((await self.meta(f"enquiry:{r.id}", {}) or {}).get("spam_score", 0))
            if not pii:
                o.phone, o.email = _mask(o.phone), _mask(o.email)
            out.append(o)
        return out

    async def _get(self, eid: uuid.UUID) -> WebsiteEnquiry:
        r = await self.db.get(WebsiteEnquiry, eid)
        if r is None or r.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enquiry not found")
        return r

    async def set_status(self, eid: uuid.UUID, status: str) -> WebsiteEnquiryOut:
        self._reader()
        r = await self._get(eid)
        old = r.status
        r.status = status
        await self.db.flush()
        await self.audit("enquiry_status", "website_enquiry", r.id, {"from": old, "to": status})
        await self.emit("website.enquiry_status_changed", {"id": str(r.id), "status": status}, r.id)
        return WebsiteEnquiryOut.model_validate(r)

    async def link_crm(self, eid: uuid.UUID) -> WebsiteEnquiryOut:
        self._reader()
        r = await self._get(eid)
        if r.enquiry_id is None:
            await self._link(r, None)
            await self.audit("enquiry_link", "website_enquiry", r.id, {"enquiry_id": str(r.enquiry_id)})
        return WebsiteEnquiryOut.model_validate(r)

    async def export(self) -> dict[str, Any]:
        self._reader()
        from app.core.jobs import enqueue

        job = await enqueue(self.db, self.principal, "website.enquiry_export", {}, queue="reports")
        return {"job_id": str(job.id)}


async def sync_stage(db: Any, institution_id: uuid.UUID, enquiry_id: str, stage: str) -> int:
    status = STAGE_TO_STATUS.get(stage)
    if not status:
        return 0
    res = await db.execute(
        text(
            "UPDATE website_enquiries SET status = :s WHERE institution_id = :i AND enquiry_id = :e AND status <> 'spam'"
        ),
        {"s": status, "i": institution_id, "e": enquiry_id},
    )
    return int(getattr(res, "rowcount", 0) or 0)
