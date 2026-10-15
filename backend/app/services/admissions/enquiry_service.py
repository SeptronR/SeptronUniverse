"""Enquiry CRM — Prompts/08 §08.6 ``enquiry_service.py``.

Stages ``new → contacted → counselled → applied → admitted | lost``; ``assign`` hands the enquiry to a counsellor
(ownership ``assigned_to`` — the assignee must hold ``admissions`` access); notes are an append-only log
``[{at, by, text}]``; ``convert`` links an applicant and moves the stage to ``applied``. Public website enquiries
(``POST /public/enquiries``, captcha) create ``source='web'`` rows (Phase 40's ``website_enquiries`` will feed the same
path). Beat ``enquiries.follow_up_reminders`` (daily 09:00) notifies the assignee of due follow-ups. ``stats``: the
source → stage funnel over the caller's visible enquiries. Phone / e-mail are masked without ``admissions:view_pii``.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.authz.masking import mask_value
from app.core.errors import APIError, ErrorCode
from app.enums.admissions import EnquiryStage
from app.models.admissions import Applicant, Enquiry
from app.models.platform import User
from app.repositories.applicant_scope import may_view_pii
from app.repositories.enquiry_repository import EnquiryRepository
from app.schemas.admissions import (
    EnquiryAssign,
    EnquiryConvert,
    EnquiryCreate,
    EnquiryResponse,
    EnquiryStats,
    EnquiryUpdate,
    PublicEnquiryCreate,
)
from app.services.admissions.common import AdmissionsBase, utcnow
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

FUNNEL = [s.value for s in EnquiryStage if s != EnquiryStage.LOST]


class EnquiryService(AdmissionsBase):
    @property
    def repo(self) -> EnquiryRepository:
        return EnquiryRepository(self.db, self.principal, self.inst)

    async def _out(self, rows: list[Enquiry]) -> list[EnquiryResponse]:
        users = {
            u.id: u
            for u in (
                await self.db.execute(select(User).where(User.id.in_([r.assigned_to for r in rows if r.assigned_to])))
            )
            .scalars()
            .all()
        }
        apps = {
            a.id: a
            for a in (
                await self.db.execute(
                    select(Applicant).where(Applicant.id.in_([r.applicant_id for r in rows if r.applicant_id]))
                )
            )
            .scalars()
            .all()
        }
        pii = self.principal is None or may_view_pii(self.principal)
        out = []
        for r in rows:
            u = users.get(r.assigned_to) if r.assigned_to else None
            mine = r.assigned_to is not None and r.assigned_to == self.actor_id
            item = EnquiryResponse(
                id=r.id,
                college_id=r.college_id,
                source=r.source,
                name=r.name,
                phone=r.phone if pii or mine else mask_value(r.phone, "phone"),
                email=r.email if pii or mine else mask_value(r.email, "email"),
                program_interest=r.program_interest,
                stage=r.stage,
                assigned_to=r.assigned_to,
                assigned_name=(u.display_name or u.username) if u else None,
                follow_up_on=r.follow_up_on,
                notes=list(r.notes or []),
                applicant_id=r.applicant_id,
                application_number=apps[r.applicant_id].application_number if r.applicant_id in apps else None,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            out.append(item)
        return out

    async def list_page(self, params: PageParams, **filters: Any) -> tuple[list[EnquiryResponse], PaginationMeta]:
        stmt = self.repo.filtered(**filters).order_by(Enquiry.created_at.desc())
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list((await self.db.execute(stmt.offset(params.offset).limit(params.page_size))).scalars().all())
        return await self._out(rows), PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )

    def _note(self, text: str | None) -> dict[str, Any] | None:
        if not text:
            return None
        return {"at": utcnow().isoformat(), "by": str(self.actor_id) if self.actor_id else "public", "text": text}

    async def create(self, body: EnquiryCreate, *, source: str | None = None) -> EnquiryResponse:
        if body.assigned_to is not None:
            await self._check_assignee(body.assigned_to)
        note = self._note(body.note)
        row = Enquiry(
            institution_id=self.inst,
            college_id=body.college_id,
            source=source or body.source.value,
            name=body.name,
            phone=body.phone,
            email=str(body.email) if body.email else None,
            program_interest=body.program_interest,
            stage="new",
            assigned_to=body.assigned_to or (self.actor_id if self.principal is not None and source is None else None),
            follow_up_on=body.follow_up_on,
            notes=[note] if note else [],
        )
        self.db.add(row)
        await self.db.flush()
        await self._audit("create", "enquiry", row.id, None, {"source": row.source, "stage": row.stage})
        await self._emit("enquiry.created", {"enquiry_id": str(row.id), "source": row.source}, "enquiry", row.id)
        return (await self._out([row]))[0]

    async def public_create(self, body: PublicEnquiryCreate) -> dict[str, Any]:
        out = await self.create(
            EnquiryCreate(
                name=body.name,
                phone=body.phone,
                email=body.email,
                source="web",
                program_interest=body.program_interest,
                note=" · ".join(
                    p for p in (body.message, f"page: {body.source_page}" if body.source_page else None) if p
                )
                or None,
            ),
            source="web",
        )
        return {"id": out.id, "received": True}

    async def update(self, enquiry_id: uuid.UUID, body: EnquiryUpdate) -> EnquiryResponse:
        row = await self.repo.get(enquiry_id, for_update=True)
        old_stage = row.stage
        data = body.model_dump(exclude_unset=True, exclude={"note", "stage"}, mode="json")
        if "follow_up_on" in data and data["follow_up_on"]:
            data["follow_up_on"] = date.fromisoformat(data["follow_up_on"])
        for k, v in data.items():
            setattr(row, k, v)
        note = self._note(body.note)
        if note:
            row.notes = [*(row.notes or []), note]
        if body.stage is not None and body.stage.value != row.stage:
            row.stage = body.stage.value
        await self.db.flush()
        await self._audit(
            "update", "enquiry", row.id, {"stage": old_stage}, {"stage": row.stage, "fields": sorted(data)}
        )
        if row.stage != old_stage:
            await self._emit(
                "enquiry.stage_changed",
                {"enquiry_id": str(row.id), "from": old_stage, "to": row.stage},
                "enquiry",
                row.id,
            )
        return (await self._out([row]))[0]

    async def _check_assignee(self, user_id: uuid.UUID) -> User:
        from app.services.auth_service import load_principal

        user = (
            await self.db.execute(select(User).where(User.id == user_id, User.institution_id == self.inst))
        ).scalar_one_or_none()
        if user is None:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown user", {"field": "user_id"})
        p = await load_principal(self.db, user.id)
        if not (p.has("admissions", "create") or p.has("admissions", "manage")):
            raise APIError(422, ErrorCode.VALIDATION, "The user cannot work enquiries", {"field": "user_id"})
        return user

    async def assign(self, enquiry_id: uuid.UUID, body: EnquiryAssign) -> EnquiryResponse:
        row = await self.repo.get(enquiry_id, for_update=True)
        await self._check_assignee(body.user_id)
        old, row.assigned_to = row.assigned_to, body.user_id
        await self.db.flush()
        await self._audit(
            "assign", "enquiry", row.id, {"assigned_to": str(old) if old else None}, {"assigned_to": str(body.user_id)}
        )
        await self._notify("admissions.enquiry_assigned", [body.user_id], {"name": row.name, "enquiry_id": str(row.id)})
        return (await self._out([row]))[0]

    async def convert(self, enquiry_id: uuid.UUID, body: EnquiryConvert) -> EnquiryResponse:
        row = await self.repo.get(enquiry_id, for_update=True)
        applicant = None
        if body.applicant_id:
            applicant = await self.applicants.get_any(body.applicant_id)
        elif body.application_number:
            applicant = await self.applicants.by_number(body.application_number.upper())
        else:
            phone = "".join(ch for ch in (row.phone or "") if ch.isdigit() or ch == "+")
            if phone:
                applicant = (
                    await self.db.execute(
                        select(Applicant)
                        .where(Applicant.institution_id == self.inst, Applicant.contact["phone"].astext == phone)
                        .order_by(Applicant.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
        if applicant is None:
            raise APIError(422, ErrorCode.VALIDATION, "No matching applicant", {"field": "applicant_id"})
        old = row.stage
        row.applicant_id = applicant.id
        row.stage = "admitted" if applicant.status == "admitted" else "applied"
        await self.db.flush()
        await self._audit(
            "convert", "enquiry", row.id, {"stage": old}, {"stage": row.stage, "applicant_id": str(applicant.id)}
        )
        await self._emit(
            "enquiry.stage_changed", {"enquiry_id": str(row.id), "from": old, "to": row.stage}, "enquiry", row.id
        )
        return (await self._out([row]))[0]

    async def stats(self, scope: str | None = None) -> EnquiryStats:
        by_stage = await self.repo.grouped(Enquiry.stage, scope)
        by_source = await self.repo.grouped(Enquiry.source, scope)
        total = sum(by_stage.values())
        funnel = []
        for i, stage in enumerate(FUNNEL):
            reached = sum(by_stage.get(s, 0) for s in FUNNEL[i:])
            funnel.append({"stage": stage, "count": reached, "pct": round(reached * 100 / total, 1) if total else 0.0})
        return EnquiryStats(total=total, by_stage=by_stage, by_source=by_source, funnel=funnel)

    async def follow_up_reminders(self, today: date) -> int:
        n = 0
        for row in await self.repo.due_follow_ups(today):
            await self._notify(
                "admissions.enquiry_follow_up",
                [row.assigned_to],
                {
                    "name": row.name,
                    "enquiry_id": str(row.id),
                    "due": row.follow_up_on.isoformat() if row.follow_up_on else "",
                },
            )
            n += 1
        return n
