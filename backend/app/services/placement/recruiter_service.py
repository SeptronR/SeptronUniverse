"""Recruiter portal — Prompts/28 §28.6 ``recruiter_service`` ({placement.recruiter_portal}).

A recruiter is scoped to the companies whose ``recruiter_user_ids`` contain them: they create / edit **draft** drives
(an officer publishes), see the applicants of their drives with **consented fields only**
(``placement.consented_fields`` ∩ the student's ``consent_share_profile`` — students without consent are excluded
entirely), schedule rounds, upload round results (``recorded_by`` = the recruiter), download a watermarked shortlist
(audited), submit offers that wait for officer confirmation and leave feedback. Every action is audited with the
company id; another company's drive is a 404.
"""

import io
import uuid
from typing import Any

from sqlalchemy import select

from app.enums.placement import CONSENTED_FIELDS
from app.models.placement import DriveApplication, PlacementDrive, StudentPlacementProfile
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.placement import (
    PlcBulkReport,
    PlcDriveCreate,
    PlcDriveOut,
    PlcDriveUpdate,
    PlcFeedbackIn,
    PlcFeedbackOut,
    PlcPendingOffer,
    PlcRoundIn,
    PlcRoundOut,
    PlcRoundResultsBulk,
    RecruiterApplicantOut,
    RecruiterDriveIn,
    RecruiterMe,
    RecruiterOfferIn,
)
from app.services.placement.common import PlacementBase, forbidden, not_found, now_utc, rule
from app.services.placement.drive_service import DriveService
from app.services.placement.offer_service import OfferService
from app.services.placement.profile_service import ProfileService


class RecruiterService(PlacementBase):
    def _require(self) -> None:
        if not self.can("placement", "recruiter"):
            raise forbidden("placement:recruiter required")

    @property
    def drives_svc(self) -> DriveService:
        return DriveService(self.db, self.principal, self.request, self.inst)

    async def _own(self, did: uuid.UUID) -> PlacementDrive:
        self._require()
        companies = await self.my_company_ids()
        d = (
            await self.db.execute(
                select(PlacementDrive).where(
                    PlacementDrive.id == did,
                    PlacementDrive.institution_id == self.inst,
                    PlacementDrive.company_id.in_(companies or [uuid.uuid4()]),
                )
            )
        ).scalar_one_or_none()
        if d is None:
            raise not_found("Drive")
        return d

    async def _audit_r(self, action: str, d: PlacementDrive, extra: dict[str, Any] | None = None) -> None:
        await self._audit(action, "placement_drive", d.id, None, {"company_id": str(d.company_id), **(extra or {})})

    async def me(self) -> RecruiterMe:
        self._require()
        from app.services.placement.company_service import CompanyService

        ids = await self.my_company_ids()
        companies = [
            c
            for c in await CompanyService(self.db, self.principal, self.request, self.inst).list_companies(
                None, None, None
            )
            if c.id in ids
        ]
        return RecruiterMe(user_id=self.actor_id or uuid.uuid4(), companies=companies)

    async def list_drives(self) -> list[PlcDriveOut]:
        self._require()
        companies = await self.my_company_ids()
        rows = list(
            (
                await self.db.execute(
                    select(PlacementDrive)
                    .where(PlacementDrive.company_id.in_(companies or [uuid.uuid4()]))
                    .order_by(PlacementDrive.created_at.desc())
                )
            ).scalars()
        )
        return await self.drives_svc.outs(rows)

    async def create_drive(self, body: RecruiterDriveIn) -> PlcDriveOut:
        self._require()
        companies = await self.my_company_ids()
        cid = body.company_id or (companies[0] if len(companies) == 1 else None)
        if cid is None or cid not in companies:
            raise rule("Choose one of your companies", "COMPANY_REQUIRED", status=422)
        data = body.model_dump(exclude={"company_id"})
        out = await self.drives_svc.create(PlcDriveCreate(company_id=cid, **data), recruiter=True)
        await self._audit("recruiter_create_drive", "placement_drive", out.id, None, {"company_id": str(cid)})
        return out

    async def update_drive(self, did: uuid.UUID, body: RecruiterDriveIn) -> PlcDriveOut:
        d = await self._own(did)
        data = body.model_dump(exclude={"company_id"}, exclude_unset=True)
        out = await self.drives_svc.update(d.id, PlcDriveUpdate(**data), recruiter=True)
        await self._audit_r("recruiter_update_drive", d)
        return out

    async def applicants(self, did: uuid.UUID) -> list[RecruiterApplicantOut]:
        d = await self._own(did)
        fields = await self.setting("placement", "consented_fields")
        allowed = set(fields if isinstance(fields, list) else CONSENTED_FIELDS)
        rows = (
            await self.db.execute(
                select(DriveApplication, StudentPlacementProfile, Student, StudentProgramEnrollment)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == DriveApplication.student_program_enrollment_id,
                )
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .join(
                    StudentPlacementProfile,
                    StudentPlacementProfile.student_program_enrollment_id
                    == DriveApplication.student_program_enrollment_id,
                )
                .where(
                    DriveApplication.drive_id == d.id,
                    DriveApplication.status.not_in(("withdrawn", "ineligible")),
                    StudentPlacementProfile.consent_share_profile.is_(True),
                )
                .order_by(DriveApplication.applied_at)
            )
        ).all()
        programs = await self._program_codes([e.program_id for _, _, _, e in rows])
        ach = await ProfileService(self.db, self.principal, self.request, self.inst).achievements(
            [e.id for _, _, _, e in rows]
        )
        apps_full = {a.id: a for a in await self.drives_svc.app_outs([a for a, _, _, _ in rows], rounds=True)}
        out = []
        for a, prof, s, e in rows:
            snap = a.eligibility_snapshot or {}
            full: dict[str, Any] = {
                "name": s.full_name,
                "registration_number": s.registration_number,
                "program": programs.get(e.program_id),
                "cgpa": snap.get("cgpa"),
                "backlogs": {"active": snap.get("active_backlogs"), "history": snap.get("history_backlogs")},
                "resume": a.resume_url or prof.resume_url,
                "skills": list(prof.skills or []),
                "achievements": ach.get(e.id, []),
                "email": s.email,
                "phone": s.phone,
            }
            out.append(
                RecruiterApplicantOut(
                    application_id=a.id,
                    status=a.status,
                    fields={k: v for k, v in full.items() if k in allowed or k == "registration_number"},
                    rounds=apps_full[a.id].rounds if a.id in apps_full else [],
                )
            )
        await self._audit_r("recruiter_view_applicants", d, {"rows": len(out)})
        return out

    async def _program_codes(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        from app.models.academic import Program

        if not ids:
            return {}
        rows = await self.db.execute(select(Program.id, Program.code).where(Program.id.in_(list(set(ids)))))
        return {r[0]: r[1] for r in rows.all()}

    async def shortlist_xlsx(self, did: uuid.UUID) -> tuple[bytes, str]:
        from openpyxl import Workbook

        d = await self._own(did)
        rows = await self.applicants(did)
        wb = Workbook()
        ws = wb.active
        ws.title = "Shortlist"
        who = await self.user_display([self.actor_id])
        stamp = f"CONFIDENTIAL — downloaded by {who.get(self.actor_id) if self.actor_id else None or self.actor_id} at {now_utc():%Y-%m-%d %H:%M} UTC"
        ws.append([stamp])
        keys: list[str] = sorted({k for r in rows for k in r.fields})
        ws.append(["application_id", "status", *keys])
        for r in rows:
            ws.append([str(r.application_id), r.status, *[_cell(r.fields.get(k)) for k in keys]])
        ws.append([stamp])
        buf = io.BytesIO()
        wb.save(buf)
        await self._audit_r("recruiter_shortlist_download", d, {"rows": len(rows), "watermark": stamp})
        return buf.getvalue(), f"shortlist-{d.id}.xlsx"

    async def add_round(self, did: uuid.UUID, body: PlcRoundIn) -> PlcRoundOut:
        d = await self._own(did)
        out = await self.drives_svc.add_round(d.id, body, recruiter=True)
        await self._audit_r("recruiter_add_round", d, {"round_no": body.round_no})
        return out

    async def round_results(self, rid: uuid.UUID, body: PlcRoundResultsBulk) -> PlcBulkReport:
        from app.models.placement import DriveRound

        r = (await self.db.execute(select(DriveRound).where(DriveRound.id == rid))).scalar_one_or_none()
        if r is None:
            raise not_found("Round")
        d = await self._own(r.drive_id)
        out = await self.drives_svc.round_results(rid, body, recruiter=True)
        await self._audit_r("recruiter_round_results", d, {"round_id": str(rid), "rows": out.succeeded})
        return out

    async def submit_offer(self, did: uuid.UUID, body: RecruiterOfferIn) -> PlcPendingOffer:
        d = await self._own(did)
        out = await OfferService(self.db, self.principal, self.request, self.inst).submit_pending(d.id, body)
        await self._audit_r("recruiter_submit_offer", d, {"application_id": str(body.application_id)})
        return out

    async def feedback(self, did: uuid.UUID, body: PlcFeedbackIn) -> PlcFeedbackOut:
        d = await self._own(did)
        return await OfferService(self.db, self.principal, self.request, self.inst).feedback(d.id, body)


def _cell(v: Any) -> Any:
    if isinstance(v, list | dict):
        return str(v)
    return v
