"""Issued-document register reads and stats — Prompts/26 §26.6 (register grid, my / ward documents) and
``stats_service`` (issued by type / month, request SLA compliance, certificate-fee revenue, pending pickups).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.enums.documents import DEFAULT_REQUEST_RULES
from app.models.documents import CertificateRequest, IssuedDocument
from app.models.fees import FeeInvoice
from app.schemas.documents import DocumentStatsOut, IssuedDocumentOut
from app.services.documents.common import DocumentsBase, forbidden


class IssuedService(DocumentsBase):
    async def outs(self, rows: list[IssuedDocument], *, detail: bool = False) -> list[IssuedDocumentOut]:
        if not rows:
            return []
        metas = await self.metas("doc", [d.id for d in rows])
        names = await self.person_names(
            [("staff" if d.person_type == "staff" else "student", d.person_id) for d in rows if d.person_id]
        )
        users = await self.user_names([d.issued_by for d in rows])
        office = self.office() or self.can("certificates", "view_all")
        out = []
        for d in rows:
            m = metas.get(str(d.id)) or {}
            out.append(
                IssuedDocumentOut(
                    id=d.id,
                    template_id=d.template_id,
                    template_version=m.get("template_version"),
                    template_type=d.template_type,
                    person_type=d.person_type,
                    person_id=d.person_id,
                    person_name=names.get(d.person_id) if d.person_id else None,
                    entity_type=d.entity_type,
                    entity_id=d.entity_id,
                    document_number=d.document_number,
                    serial_no=d.serial_no,
                    verification_token=d.verification_token if (office or detail) else None,
                    content_hash=d.content_hash,
                    watermark_text=d.watermark_text,
                    issued_by=d.issued_by,
                    issued_by_name=users.get(d.issued_by) if d.issued_by else None,
                    issued_at=d.issued_at,
                    revoked=d.revoked_at is not None,
                    revoked_at=d.revoked_at,
                    revoke_reason=d.revoke_reason,
                    superseded_by=uuid.UUID(m["superseded_by"]) if m.get("superseded_by") else None,
                    supersedes=uuid.UUID(m["supersedes"]) if m.get("supersedes") else None,
                    downloads=int(m.get("download_count") or 0),
                    job_id=d.job_id,
                    download_log=list(m.get("downloads") or [])[-50:] if detail and office else None,
                )
            )
        return out

    async def list_issued(
        self,
        *,
        template_type: str | None = None,
        person_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        revoked: bool | None = None,
        scope: str | None = None,
        q: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[IssuedDocumentOut]:
        await self.require_feature("documents.templates")
        if template_type and scope not in ("self", "mine", "wards"):
            limit_types = self.type_limit()
            if limit_types is not None and template_type not in limit_types:
                raise forbidden(f"{template_type} documents are outside your role")
        stmt = select(IssuedDocument).where(
            IssuedDocument.institution_id == self.inst, await self.issued_predicate(scope)
        )
        if template_type:
            stmt = stmt.where(IssuedDocument.template_type == template_type)
        if person_id:
            stmt = stmt.where(IssuedDocument.person_id == person_id)
        if entity_type:
            stmt = stmt.where(IssuedDocument.entity_type == entity_type)
        if date_from:
            stmt = stmt.where(IssuedDocument.issued_at >= date_from)
        if date_to:
            stmt = stmt.where(IssuedDocument.issued_at < date_to + timedelta(days=1))
        if revoked is not None:
            stmt = stmt.where(
                IssuedDocument.revoked_at.is_not(None) if revoked else IssuedDocument.revoked_at.is_(None)
            )
        if q:
            stmt = stmt.where(IssuedDocument.document_number.ilike(f"%{q}%") | (IssuedDocument.serial_no == q))
        rows = (
            await self.db.execute(stmt.order_by(IssuedDocument.issued_at.desc()).offset(offset).limit(min(limit, 1000)))
        ).scalars()
        return await self.outs(list(rows))

    async def get(self, did: uuid.UUID) -> IssuedDocumentOut:
        return (await self.outs([await self.visible_document(did)], detail=True))[0]

    async def stats(self) -> DocumentStatsOut:
        if not (self.can("certificates", "view_all") or self.office()):
            raise forbidden("certificates:view_all required")
        base = IssuedDocument.institution_id == self.inst
        by_type = {
            t: int(n)
            for t, n in (
                await self.db.execute(
                    select(IssuedDocument.template_type, func.count())
                    .where(base)
                    .group_by(IssuedDocument.template_type)
                )
            ).all()
        }
        month = func.to_char(IssuedDocument.issued_at, "YYYY-MM")
        by_month = {
            str(mo): int(n)
            for mo, n in (
                await self.db.execute(select(month, func.count()).where(base).group_by(month).order_by(month))
            ).all()
        }
        revoked = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(IssuedDocument).where(base, IssuedDocument.revoked_at.is_not(None))
                )
            ).scalar_one()
        )
        reqs = (
            (await self.db.execute(select(CertificateRequest).where(CertificateRequest.institution_id == self.inst)))
            .scalars()
            .all()
        )
        by_status: dict[str, int] = {}
        within = done = 0
        rules: dict[str, Any] = {**DEFAULT_REQUEST_RULES, **(await self.doc_setting("request_rules", {}) or {})}
        metas = await self.metas("req", [r.id for r in reqs])
        pickups = 0
        for r in reqs:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            m = metas.get(str(r.id)) or {}
            if m.get("stage") == "pickup_ready":
                pickups += 1
            if r.status in ("generated", "issued"):
                done += 1
                sla = int((rules.get(r.template_type) or {}).get("sla_days") or 3)
                if (r.updated_at - r.created_at) <= timedelta(days=sla):
                    within += 1
        revenue = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(FeeInvoice.paid_paise), 0)).where(
                        FeeInvoice.institution_id == self.inst, FeeInvoice.source_type == "certificate_request"
                    )
                )
            ).scalar_one()
        )
        return DocumentStatsOut(
            issued_by_type=by_type,
            issued_by_month=by_month,
            revoked=revoked,
            requests_by_status=by_status,
            sla_compliance_pct=round(within * 100 / done, 1) if done else None,
            fee_revenue_paise=revenue,
            pending_pickups=pickups,
        )
