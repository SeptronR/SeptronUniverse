"""Awards — Prompts/18 §18.6 ``award_service`` (features ``degrees.certificates`` / ``degrees.provisional`` /
``degrees.esign``).

1. ``award_batch`` (``degrees:award`` — or ``degrees:create`` for college admins, who only recommend): enrolments of
   a convocation (registered / attended — setting ``degrees.award_requires_registration``), a batch or a list whose
   latest eligibility check is eligible (overrides count) and which hold no live award of the type → ``recommended``
   rows with degree name / specialization from the programme + enrolment and CGPA / class from the latest published
   term result. ``dry_run`` returns the preview only.
2. ``approve`` (``degrees:award`` — registrar / VC): ``council_approved``; when ``governance.minutes`` is enabled a
   ``resolution_id`` is required (422 ``RESOLUTION_REQUIRED``).
3. ``issue`` (``degrees:issue`` **and** ``degrees:award`` — a college admin's ``issue`` alone is refused, the
   university issues): certificate number (sequence ``degree``, fallback ``DEG/{yyyy}/{n}``) + serial (sequence
   ``degree_serial``, fallback ``SN{yyyy}{n}``), PDF (platform default template until Phase 26), QR token in the
   internal credential registry, optional eSign (registry adapter ``esign`` → ``esign_ref``); enrolment →
   ``completed``, student → ``graduated``, event ``student.graduated`` (Phase 29 creates the alumni profile).
4. Provisional certificates: eligible enrolments without an issued award → PDF + ``pv`` QR (superseded once a degree
   is issued).
5. ``revoke`` (``degrees:manage``) → ``cancelled``, QR revoked, external credentials revoked, student back to
   ``active`` with the enrolment ``completed``; ``reissue`` → a new issued row (new serial / PDF / QR) with the
   corrections, the old row ``reissued`` with ``reissued_as`` in its QR payload.
6. Print batch (one PDF in serial order) and the statutory degree register (CSV).
"""

import csv
import io
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.files import build_key, storage
from app.models.academic import Program
from app.models.degrees import ConvocationRegistration, DegreeAwarded, DigitalCredential
from app.models.platform import Institution
from app.models.results import StudentTermResult
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.degree_scope import enrollment_predicate
from app.schemas.degrees import (
    ApproveRequest,
    AwardBatchPreview,
    AwardBatchRequest,
    AwardPreviewRow,
    DegreeAwardedResponse,
    IssueRequest,
    ProvisionalResponse,
    ReissueRequest,
    RevokeRequest,
)
from app.services.degrees.common import DegreeBase, full_name, now_utc, rule
from app.services.degrees.eligibility_service import EligibilityService

ENTITY = "degree_award"
LIVE = ("recommended", "council_approved", "issued")


async def _feature(inst: uuid.UUID, key: str) -> bool:
    try:
        return await is_enabled(inst, key)
    except KeyError:  # key of a later phase not registered yet
        return False


class AwardService(DegreeBase):
    def require_issue_rights(self) -> None:
        if not (self.can("degrees", "issue") and self.can("degrees", "award")):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Degrees are issued by the university (degrees:issue + award)"
            )

    # ---- helpers ----------------------------------------------------------------------------------------------------
    async def _get(self, award_id: uuid.UUID, *, for_update: bool = False) -> DegreeAwarded:
        q = select(DegreeAwarded).where(
            DegreeAwarded.id == award_id,
            DegreeAwarded.institution_id == self.inst,
            enrollment_predicate(self.principal, DegreeAwarded.student_program_enrollment_id),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Award not found")
        return row

    async def _latest_term(self, enrollment_id: uuid.UUID) -> StudentTermResult | None:
        return (
            await self.db.execute(
                select(StudentTermResult)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .where(
                    StudentTermRecord.student_program_enrollment_id == enrollment_id,
                    StudentTermResult.status == "published",
                )
                .order_by(StudentTermRecord.term_number.desc(), StudentTermResult.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def outs(self, rows: list[DegreeAwarded]) -> list[DegreeAwardedResponse]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        creds = {
            (c.entity_id, c.channel): c
            for c in (
                await self.db.execute(
                    select(DigitalCredential).where(
                        DigitalCredential.entity_type == "degree",
                        DigitalCredential.entity_id.in_([r.id for r in rows] or [uuid.uuid4()]),
                    )
                )
            )
            .scalars()
            .all()
        }
        out = []
        for r in rows:
            internal = creds.get((r.id, "internal"))
            external = next((c for (eid, ch), c in creds.items() if eid == r.id and ch != "internal"), None)
            payload = (internal.payload or {}) if internal else {}
            out.append(
                DegreeAwardedResponse(
                    id=r.id,
                    enrollment=refs.get(r.student_program_enrollment_id) or {"id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                    award_type=r.award_type,
                    degree_name=r.degree_name,
                    specialization=r.specialization,
                    result_class=r.result_class,
                    cgpa=float(r.cgpa) if r.cgpa is not None else None,
                    date_of_award=r.date_of_award,
                    certificate_number=r.certificate_number,
                    serial_no=r.serial_no,
                    convocation_id=r.convocation_id,
                    pdf_url=r.pdf_url,
                    esign_ref=r.esign_ref,
                    status=r.status,
                    approval_resolution_id=r.approval_resolution_id,
                    verification_token=payload.get("token")
                    if r.status in ("issued", "cancelled", "reissued")
                    else None,
                    credential_status=external.status if external else None,
                    reissued_as=uuid.UUID(payload["reissued_as"]) if payload.get("reissued_as") else None,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
            )
        return out

    # ---- award batch ------------------------------------------------------------------------------------------------
    async def _candidates(self, body: AwardBatchRequest) -> list[StudentProgramEnrollment]:
        q = select(StudentProgramEnrollment).where(
            StudentProgramEnrollment.institution_id == self.inst,
            StudentProgramEnrollment.deleted_at.is_(None),
            enrollment_predicate(self.principal, StudentProgramEnrollment.id),
        )
        if body.convocation_id:
            statuses = ("registered", "attended")
            q = q.where(
                StudentProgramEnrollment.id.in_(
                    select(ConvocationRegistration.student_program_enrollment_id).where(
                        ConvocationRegistration.convocation_id == body.convocation_id,
                        ConvocationRegistration.status.in_(statuses),
                    )
                )
            )
        elif body.enrollment_ids:
            q = q.where(StudentProgramEnrollment.id.in_(body.enrollment_ids))
        elif body.batch_id:
            q = q.where(StudentProgramEnrollment.batch_id == body.batch_id)
        else:
            raise APIError(422, ErrorCode.VALIDATION, "convocation_id, batch_id or enrollment_ids is required")
        return list((await self.db.execute(q)).scalars().all())

    async def award_batch(self, body: AwardBatchRequest, *, dry_run: bool = False) -> AwardBatchPreview:  # noqa: C901
        if not (self.can("degrees", "award") or self.can("degrees", "create")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:award required")
        candidates = await self._candidates(body)
        need_reg = bool(await self.setting("degrees", "award_requires_registration")) and not body.convocation_id
        elig = EligibilityService(self.db, self.principal, self.request, self.inst)
        refs = await self.refs([e.id for e in candidates])
        programs = {
            p.id: p
            for p in (
                await self.db.execute(
                    select(Program).where(Program.id.in_({e.program_id for e in candidates} or {uuid.uuid4()}))
                )
            )
            .scalars()
            .all()
        }
        preview = AwardBatchPreview(dry_run=dry_run, eligible=0, skipped=0)
        today = await self.today()
        for e in candidates:
            program = programs[e.program_id]
            name = (
                program.degree_name
                if body.award_type == "degree"
                else f"{body.award_type.replace('_', ' ').title()} — {program.name}"
            )
            skip = None
            chk = await elig.latest(e.id)
            if chk is None:
                skip = "NO_ELIGIBILITY_CHECK"
            elif not chk.is_eligible:
                skip = "NOT_ELIGIBLE"
            elif (
                await self.db.execute(
                    select(DegreeAwarded.id).where(
                        DegreeAwarded.student_program_enrollment_id == e.id,
                        DegreeAwarded.award_type == body.award_type,
                        DegreeAwarded.status.in_(LIVE),
                    )
                )
            ).first():
                skip = "ALREADY_AWARDED"
            elif (
                need_reg
                and not (
                    await self.db.execute(
                        select(ConvocationRegistration.id).where(
                            ConvocationRegistration.student_program_enrollment_id == e.id,
                            ConvocationRegistration.status.in_(("registered", "attended")),
                        )
                    )
                ).first()
            ):
                skip = "NOT_REGISTERED"
            term = await self._latest_term(e.id)
            cgpa = term.cgpa if term and term.cgpa is not None else (chk.cgpa if chk else e.cgpa)
            row = AwardPreviewRow(
                enrollment=refs.get(e.id) or {"id": e.id},  # type: ignore[arg-type]
                degree_name=name[:120],
                result_class=term.result_class if term else None,
                cgpa=float(cgpa) if cgpa is not None else None,
                skip_reason=skip,
            )
            preview.rows.append(row)
            if skip:
                preview.skipped += 1
                continue
            preview.eligible += 1
            if dry_run:
                continue
            a = DegreeAwarded(
                institution_id=self.inst,
                student_program_enrollment_id=e.id,
                award_type=body.award_type,
                degree_name=name[:120],
                specialization=e.specialization or program.specialization,
                result_class=row.result_class,
                cgpa=cgpa,
                date_of_award=body.date_of_award or await self._convocation_date(body.convocation_id) or today,
                convocation_id=body.convocation_id,
                approval_resolution_id=body.resolution_id,
                status="recommended",
            )
            self.db.add(a)
            await self.db.flush()
            preview.created += 1
            await self._emit("degrees.recommended", {"award_id": str(a.id)}, ENTITY, a.id)
        if not dry_run:
            await self._audit(
                "award_batch",
                ENTITY,
                None,
                None,
                {"created": preview.created, "skipped": preview.skipped, **body.model_dump(mode="json")},
            )
        return preview

    async def _convocation_date(self, cid: uuid.UUID | None) -> date | None:
        if cid is None:
            return None
        from app.models.degrees import Convocation

        return (await self.db.execute(select(Convocation.held_on).where(Convocation.id == cid))).scalar_one_or_none()

    # ---- approve / issue --------------------------------------------------------------------------------------------
    async def approve(self, award_id: uuid.UUID, body: ApproveRequest) -> DegreeAwardedResponse:
        if not self.can("degrees", "award"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:award required")
        a = await self._get(award_id, for_update=True)
        if a.status != "recommended":
            raise rule(f"Award is {a.status}", "INVALID_TRANSITION")
        resolution = body.resolution_id or a.approval_resolution_id
        if resolution is None and await _feature(self.inst, "governance.minutes"):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "An Academic / Executive Council resolution is required",
                {"code": "RESOLUTION_REQUIRED"},
            )
        a.status, a.approved_by, a.approval_resolution_id = "council_approved", self.actor_id, resolution
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit(
            "award_approve", ENTITY, a.id, {"status": "recommended"}, {"status": a.status, "comment": body.comment}
        )
        await self._emit("degrees.approved", {"award_id": str(a.id)}, ENTITY, a.id)
        return (await self.outs([a]))[0]

    async def _numbers(self, college_id: uuid.UUID | None) -> tuple[str, str]:
        from app.services.sequence_service import SequenceService

        seq = SequenceService(self.db, self.principal, self.request, self.inst)
        year = now_utc().year
        total = (
            await self.db.execute(
                select(func.count())
                .select_from(DegreeAwarded)
                .where(DegreeAwarded.institution_id == self.inst, DegreeAwarded.certificate_number.is_not(None))
            )
        ).scalar_one()
        try:
            number = (await seq.next("degree", college_id)).rendered[:40]
        except APIError:
            number = f"DEG/{year}/{int(total) + 1:06d}"
        try:
            serial = (await seq.next("degree_serial", college_id)).rendered[:40]
        except APIError:
            serial = f"SN{year}{int(total) + 1:07d}"
        return number, serial

    async def _render(
        self, a: DegreeAwarded, token: str, holder: str | None = None, *, title: str | None = None
    ) -> str:
        from app.utils.pdf import simple_pdf

        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == a.student_program_enrollment_id)
            )
        ).scalar_one()
        st = (await self.db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
        inst = (await self.db.execute(select(Institution).where(Institution.id == self.inst))).scalar_one()
        label = title or a.award_type.replace("_", " ").upper()
        lines = [
            inst.name,
            "",
            f"{label} CERTIFICATE",
            "",
            "This is to certify that",
            holder or full_name(st) or "",
            f"Registration number {st.registration_number}",
            f"has been admitted to the {a.degree_name}" + (f" ({a.specialization})" if a.specialization else ""),
            f"with {a.result_class or 'pass'}" + (f" · CGPA {a.cgpa}" if a.cgpa is not None else ""),
            f"on {a.date_of_award.isoformat() if a.date_of_award else ''}.",
            "",
            f"Certificate No. {a.certificate_number or '—'}    Serial {a.serial_no or '—'}",
            f"Verify: /verify/{token}",
        ]
        if a.esign_ref:
            lines += ["", f"Digitally signed · eSign ref {a.esign_ref}"]
        key = build_key(
            self.inst, "degrees", f"{(a.certificate_number or a.id.hex).replace('/', '-')}-{a.id.hex[:8]}.pdf"
        )
        await storage.put(key, simple_pdf(lines, title=label.title()), "application/pdf")
        return key

    async def issue(self, award_id: uuid.UUID, body: IssueRequest) -> DegreeAwardedResponse:
        if not (self.can("degrees", "issue") and self.can("degrees", "award")):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Degrees are issued by the university (degrees:issue + award)"
            )
        a = await self._get(award_id, for_update=True)
        if a.status != "council_approved":
            raise rule(f"Only approved awards can be issued (award is {a.status})", "NOT_APPROVED")
        await self._issue(a, body.esign)
        return (await self.outs([a]))[0]

    async def _issue(self, a: DegreeAwarded, esign: bool, holder: str | None = None) -> None:
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment)
                .where(StudentProgramEnrollment.id == a.student_program_enrollment_id)
                .with_for_update()
            )
        ).scalar_one()
        a.certificate_number, a.serial_no = await self._numbers(e.college_id)
        qr = await self.register_qr(
            "degree",
            a.id,
            "dg",
            {
                "certificate_number": a.certificate_number,
                "serial_no": a.serial_no,
                **({"holder_name": holder} if holder else {}),
            },
        )
        if esign and await _feature(self.inst, "degrees.esign"):
            from app.integrations.registry import get_adapter

            res = await get_adapter("esign").sign_document(document=a.certificate_number, signer="registrar")
            a.esign_ref = str(res.get("reference") or "")[:120] or None
        a.pdf_url = await self._render(a, str((qr.payload or {})["token"]), holder)
        a.status = "issued"
        a.digital_credential_id = qr.id
        await self.db.flush()
        await self.db.refresh(a)
        st = (await self.db.execute(select(Student).where(Student.id == e.student_id).with_for_update())).scalar_one()
        old_status = st.status
        if a.award_type in ("degree", "honours", "pg_diploma", "phd"):
            e.status = "completed"
            st.status = "graduated"
        await self.db.flush()
        await self._audit(
            "award_issue",
            ENTITY,
            a.id,
            None,
            {"certificate_number": a.certificate_number, "serial_no": a.serial_no, "esign": bool(a.esign_ref)},
        )
        await self._emit("degrees.issued", {"award_id": str(a.id), "enrollment_id": str(e.id)}, ENTITY, a.id)
        if st.status == "graduated" and old_status != "graduated":
            await self._emit(
                "student.graduated",
                {"student_id": str(st.id), "enrollment_id": str(e.id), "award_id": str(a.id)},
                "student",
                st.id,
            )
        await self._notify(
            "degrees.awarded",
            [st.user_id],
            {"degree": a.degree_name, "number": a.certificate_number or ""},
            guardians=True,
        )

    async def issue_batch(
        self, award_ids: list[uuid.UUID] | None, convocation_id: uuid.UUID | None, esign: bool
    ) -> dict[str, int]:
        if not (self.can("degrees", "issue") and self.can("degrees", "award")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:issue + award required")
        q = select(DegreeAwarded).where(
            DegreeAwarded.institution_id == self.inst, DegreeAwarded.status == "council_approved"
        )
        if award_ids:
            q = q.where(DegreeAwarded.id.in_(award_ids))
        if convocation_id:
            q = q.where(DegreeAwarded.convocation_id == convocation_id)
        rows = list((await self.db.execute(q.order_by(DegreeAwarded.created_at).with_for_update())).scalars().all())
        for a in rows:
            await self._issue(a, esign)
        return {"issued": len(rows)}

    # ---- revoke / reissue -------------------------------------------------------------------------------------------
    async def revoke(self, award_id: uuid.UUID, body: RevokeRequest) -> DegreeAwardedResponse:
        if not self.can("degrees", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:manage required")
        a = await self._get(award_id, for_update=True)
        if a.status not in ("issued", "council_approved", "recommended"):
            raise rule(f"Award is {a.status}", "INVALID_TRANSITION")
        was_issued = a.status == "issued"
        old = a.status
        a.status = "cancelled"
        creds = (
            (
                await self.db.execute(
                    select(DigitalCredential).where(
                        DigitalCredential.entity_type == "degree", DigitalCredential.entity_id == a.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for c in creds:
            c.status = "revoked"
            c.payload = {**(c.payload or {}), "revoked_reason": body.reason, "revoked_at": now_utc().isoformat()}
        if was_issued:
            e = (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.id == a.student_program_enrollment_id
                    )
                )
            ).scalar_one()
            st = (await self.db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
            if st.status == "graduated":
                st.status = "active"
            e.status = "completed"
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit("award_revoke", ENTITY, a.id, {"status": old}, {"status": a.status, "reason": body.reason})
        await self._emit("degrees.revoked", {"award_id": str(a.id), "reason": body.reason}, ENTITY, a.id)
        for c in creds:
            if c.channel != "internal":
                await self._emit("credentials.revoked", {"credential_id": str(c.id)}, "digital_credential", c.id)
        return (await self.outs([a]))[0]

    async def reissue(self, award_id: uuid.UUID, body: ReissueRequest) -> DegreeAwardedResponse:
        if not (self.can("degrees", "manage") or (self.can("degrees", "issue") and self.can("degrees", "award"))):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:manage required")
        old = await self._get(award_id, for_update=True)
        if old.status != "issued":
            raise rule("Only issued awards can be reissued", "NOT_ISSUED")
        corr = dict(body.corrections or {})
        new = DegreeAwarded(
            institution_id=self.inst,
            student_program_enrollment_id=old.student_program_enrollment_id,
            award_type=old.award_type,
            degree_name=str(corr.get("degree_name") or old.degree_name)[:120],
            specialization=corr.get("specialization", old.specialization),
            result_class=corr.get("result_class", old.result_class),
            cgpa=old.cgpa,
            date_of_award=old.date_of_award,
            convocation_id=old.convocation_id,
            approval_resolution_id=old.approval_resolution_id,
            approved_by=old.approved_by,
            status="council_approved",
        )
        self.db.add(new)
        await self.db.flush()
        await self._issue(new, bool(old.esign_ref), holder=corr.get("holder_name"))
        old.status = "reissued"
        cred = await self.internal_credential("degree", old.id)
        if cred is not None:
            cred.payload = {**(cred.payload or {}), "reissued_as": str(new.id), "reissue_reason": body.reason}
        await self.db.flush()
        await self._audit(
            "award_reissue",
            ENTITY,
            old.id,
            {"status": "issued"},
            {"status": "reissued", "new": str(new.id), "reason": body.reason},
        )
        await self._emit("degrees.reissued", {"award_id": str(old.id), "new_award_id": str(new.id)}, ENTITY, old.id)
        return (await self.outs([new]))[0]

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def list_awards(
        self,
        batch_id: uuid.UUID | None,
        status: str | None,
        program_id: uuid.UUID | None,
        convocation_id: uuid.UUID | None = None,
    ) -> list[DegreeAwardedResponse]:
        q = (
            select(DegreeAwarded)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.id == DegreeAwarded.student_program_enrollment_id)
            .where(
                DegreeAwarded.institution_id == self.inst,
                enrollment_predicate(self.principal, DegreeAwarded.student_program_enrollment_id),
            )
        )
        if batch_id:
            q = q.where(StudentProgramEnrollment.batch_id == batch_id)
        if program_id:
            q = q.where(StudentProgramEnrollment.program_id == program_id)
        if status:
            q = q.where(DegreeAwarded.status == status)
        if convocation_id:
            q = q.where(DegreeAwarded.convocation_id == convocation_id)
        rows = list(
            (
                await self.db.execute(
                    q.order_by(DegreeAwarded.serial_no.nulls_last(), DegreeAwarded.created_at).limit(5000)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def get(self, award_id: uuid.UUID) -> DegreeAwardedResponse:
        return (await self.outs([await self._get(award_id)]))[0]

    async def me(self) -> list[DegreeAwardedResponse]:
        rows = list(
            (
                await self.db.execute(
                    select(DegreeAwarded).where(
                        DegreeAwarded.student_program_enrollment_id.in_(await self.mine() or [uuid.uuid4()])
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def certificate(self, award_id: uuid.UUID) -> bytes:
        a = await self._get(award_id)
        if a.status not in ("issued", "reissued", "cancelled") or not a.pdf_url:
            raise APIError(404, ErrorCode.NOT_FOUND, "Certificate not generated yet")
        return await storage.get(a.pdf_url)

    async def register_csv(self, batch_id: uuid.UUID | None = None) -> bytes:
        rows = await self.list_awards(batch_id, None, None)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "Serial",
                "Certificate no.",
                "Registration no.",
                "Name",
                "Programme",
                "Award",
                "Class",
                "CGPA",
                "Date",
                "Status",
            ]
        )
        for r in rows:
            if r.status == "recommended":
                continue
            w.writerow(
                [
                    r.serial_no,
                    r.certificate_number,
                    r.enrollment.registration_number,
                    r.enrollment.student_name,
                    r.enrollment.program_code,
                    r.degree_name,
                    r.result_class,
                    r.cgpa,
                    r.date_of_award,
                    r.status,
                ]
            )
        return buf.getvalue().encode()

    async def print_batch(self, award_ids: list[uuid.UUID] | None, convocation_id: uuid.UUID | None) -> dict[str, Any]:
        """One print file in serial order (the fallback PDF writer cannot merge pages — one page per certificate)."""
        from app.utils.pdf import simple_pdf

        rows = [
            r
            for r in await self.list_awards(None, "issued", None, convocation_id)
            if not award_ids or r.id in award_ids
        ]
        rows.sort(key=lambda r: r.serial_no or "")
        lines: list[str] = []
        for r in rows:
            lines += [
                f"Serial {r.serial_no} · {r.certificate_number}",
                f"{r.enrollment.student_name} ({r.enrollment.registration_number})",
                f"{r.degree_name} · {r.result_class or ''} · CGPA {r.cgpa or '—'} · {r.date_of_award}",
            ] + [""] * 57
        key = build_key(self.inst, "degrees", f"print-batch-{uuid.uuid4().hex[:8]}.pdf")
        await storage.put(key, simple_pdf(lines or ["Nothing to print"], title="Degree print batch"), "application/pdf")
        return {"result_url": key, "count": len(rows)}

    # ---- provisional ------------------------------------------------------------------------------------------------
    async def provisional(self, enrollment_id: uuid.UUID) -> ProvisionalResponse:
        if not self.can("degrees", "issue"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:issue required")
        e = await self.enrolment(enrollment_id)
        chk = await EligibilityService(self.db, self.principal, self.request, self.inst).latest(e.id)
        if chk is None or not chk.is_eligible:
            raise rule("Only eligible students receive a provisional certificate", "NOT_ELIGIBLE")
        issued = (
            await self.db.execute(
                select(DegreeAwarded.id).where(
                    DegreeAwarded.student_program_enrollment_id == e.id, DegreeAwarded.status == "issued"
                )
            )
        ).first()
        if issued:
            raise rule("The degree is already issued", "ALREADY_ISSUED")
        from app.utils.pdf import simple_pdf

        program = (await self.db.execute(select(Program).where(Program.id == e.program_id))).scalar_one()
        st = (await self.db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
        n = (
            await self.db.execute(
                select(func.count())
                .select_from(DigitalCredential)
                .where(
                    DigitalCredential.institution_id == self.inst,
                    DigitalCredential.entity_type == "provisional_certificate",
                )
            )
        ).scalar_one()
        number = f"PC/{now_utc():%Y}/{int(n) + 1:05d}"
        qr = await self.register_qr("provisional_certificate", e.id, "pv", {"document_number": number})
        token = str((qr.payload or {})["token"])
        lines = [
            "PROVISIONAL CERTIFICATE",
            "",
            f"{full_name(st)} ({st.registration_number}) has fulfilled the requirements of the {program.degree_name}",
            f"CGPA {chk.cgpa or '—'}. The degree will be conferred at the next convocation.",
            "",
            f"No. {number}",
            f"Verify: /verify/{token}",
        ]
        key = build_key(self.inst, "provisional", f"{number.replace('/', '-')}-{e.id.hex[:8]}.pdf")
        await storage.put(key, simple_pdf(lines, title="Provisional certificate"), "application/pdf")
        qr.payload = {**(qr.payload or {}), "pdf_url": key}
        await self.db.flush()
        await self._audit("provisional_issue", "provisional_certificate", e.id, None, {"document_number": number})
        await self._emit(
            "degrees.provisional_issued",
            {"enrollment_id": str(e.id), "number": number},
            "provisional_certificate",
            e.id,
        )
        return ProvisionalResponse(
            enrollment=await self.ref(e.id),
            document_number=number,
            pdf_url=key,
            verification_token=token,
            issued_at=now_utc(),
        )

    async def provisional_me(self) -> list[ProvisionalResponse]:
        out = []
        for eid in await self.mine():
            cred = await self.internal_credential("provisional_certificate", eid)
            if cred is None:
                continue
            p = cred.payload or {}
            issued = (
                await self.db.execute(
                    select(DegreeAwarded.id).where(
                        DegreeAwarded.student_program_enrollment_id == eid, DegreeAwarded.status == "issued"
                    )
                )
            ).first()
            out.append(
                ProvisionalResponse(
                    enrollment=await self.ref(eid),
                    document_number=str(p.get("document_number")),
                    pdf_url=p.get("pdf_url"),
                    verification_token=str(p.get("token")),
                    issued_at=cred.updated_at,
                    superseded=issued is not None,
                )
            )
        return out
