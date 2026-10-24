"""Leaves, out-pass and gate — Prompts/20 §20.6 ``leave_service`` (features ``hostel.leave_outpass`` /
``hostel.gate_qr``).

* **create** (resident with an active allocation): duration ≤ ``LEAVE_MAX_HOURS`` per type, no overlapping active leave
  (409 ``OVERLAP``), out-pass / day leave blocked on exam days (409 ``EXAM_DAY``; medical exempt) when a date-sheet
  paper of the student's registrations falls inside the window; ``guardian_consent='pending'`` when the type is in
  ``hostel.guardian_otp_required_for`` or the student is a minor (``hostel.minor_requires_otp``), else
  ``not_required``; out-passes auto-approve when ``hostel.outpass_auto_approve`` and no consent is pending.
* **consent**: 6-digit OTP (Redis, 10 min, 3 attempts → 429 ``OTP_LOCKED``) by SMS to the primary guardian's phone, or
  the parent app's approve button (consented ward).
* **decide** (warden of the hostel): approve refused while consent is pending (409 ``CONSENT_PENDING``); approval sets a
  random ``qr_token``; the workflow ``hostel.leave`` mirrors the decision.
* **gate scan** (``hostel:gate`` — gate staff / warden of that hostel): ``out`` → ``out`` / ``actual_out_at``; ``in`` →
  ``returned`` or ``late_return`` beyond ``to_at + hostel.late_grace_minutes`` (``late_minutes``) with a fine per
  ``fine_configurations(applies_to='hostel')`` (flat amount per started hour, capped), an automatic disciplinary
  ``warning`` (``fine`` on repeat within 90 days) and a guardian notification; offline batches carry device times and
  are applied in time order (server wins).
* **absconding** (hourly Beat): ``out`` leaves ``hostel.absconding_after_hours`` past ``to_at`` → ``absconding`` with
  escalations; a later return or warden ``mark-returned`` → ``late_return`` (audited).
"""

import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.db.session import redis_client
from app.enums.hostel import ACTIVE_ALLOCATION, ACTIVE_LEAVE, LEAVE_MAX_HOURS
from app.models.fees import FineConfiguration
from app.models.hostel import Hostel, HostelAllocation, HostelDisciplinaryRecord, HostelLeave
from app.models.platform import WorkflowInstance
from app.models.students import Student, StudentGuardian, StudentProgramEnrollment
from app.schemas.hostel import (
    GateScanRequest,
    GateScanResponse,
    HostelLeaveCreate,
    HostelLeaveDecision,
    HostelLeaveResponse,
    MarkReturned,
)
from app.services.hostel.common import HostelBase, now_utc, resident_predicate, rule

ENTITY = "hostel_leave"
OTP_TTL = 600


class LeaveService(HostelBase):
    async def outs(self, rows: list[HostelLeave], *, show_qr: bool = False) -> list[HostelLeaveResponse]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        names: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(Hostel.id, Hostel.name).where(Hostel.id.in_({r.hostel_id for r in rows} or {uuid.uuid4()}))
                )
            ).all()
        )  # type: ignore[arg-type]
        mine = set(await self.mine()) if show_qr else set()
        return [
            HostelLeaveResponse(
                id=r.id,
                student=refs.get(r.student_program_enrollment_id) or {"enrollment_id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                hostel_id=r.hostel_id,
                hostel=names.get(r.hostel_id),
                leave_type=r.leave_type,
                from_at=r.from_at,
                to_at=r.to_at,
                destination=r.destination,
                reason=r.reason,
                guardian_consent=r.guardian_consent,
                status=r.status,
                qr_token=r.qr_token
                if r.student_program_enrollment_id in mine and r.status in ("approved", "out")
                else None,
                actual_out_at=r.actual_out_at,
                actual_return_at=r.actual_return_at,
                late_minutes=r.late_minutes,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def _get(self, leave_id: uuid.UUID, *, for_update: bool = False) -> HostelLeave:
        q = select(HostelLeave).where(
            HostelLeave.id == leave_id,
            HostelLeave.institution_id == self.inst,
            resident_predicate(self.principal, HostelLeave.student_program_enrollment_id, HostelLeave.hostel_id),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Leave not found")
        return row

    # ---- create ----------------------------------------------------------------------------------------------------
    async def _exam_day(self, enrol_id: uuid.UUID, start: datetime, end: datetime) -> bool:
        from app.models.exams import ExamPaper, ExamRegistration, ExamRegistrationItem

        hit = (
            await self.db.execute(
                select(ExamPaper.id)
                .join(ExamRegistrationItem, ExamRegistrationItem.exam_paper_id == ExamPaper.id)
                .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                .where(
                    ExamRegistration.student_program_enrollment_id == enrol_id,
                    ExamPaper.exam_date.is_not(None),
                    ExamPaper.exam_date >= start.date(),
                    ExamPaper.exam_date <= end.date(),
                    ExamRegistrationItem.status.in_(("registered", "appeared")),
                )
                .limit(1)
            )
        ).first()
        return hit is not None

    async def create(self, body: HostelLeaveCreate) -> HostelLeaveResponse:
        e = await self.my_enrolment()
        alloc = (
            await self.db.execute(
                select(HostelAllocation).where(
                    HostelAllocation.student_program_enrollment_id == e.id, HostelAllocation.status == "checked_in"
                )
            )
        ).scalar_one_or_none()
        if alloc is None:
            raise rule("Only checked-in residents can request leave", "NOT_RESIDENT")
        if body.to_at <= body.from_at:
            raise APIError(422, ErrorCode.VALIDATION, "to_at must follow from_at")
        hours = (body.to_at - body.from_at).total_seconds() / 3600
        if hours > LEAVE_MAX_HOURS[body.leave_type]:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"{body.leave_type} may last at most {LEAVE_MAX_HOURS[body.leave_type]} hours",
                {"code": "TOO_LONG"},
            )
        overlap = (
            await self.db.execute(
                select(HostelLeave.id).where(
                    HostelLeave.student_program_enrollment_id == e.id,
                    HostelLeave.status.in_(ACTIVE_LEAVE),
                    HostelLeave.from_at < body.to_at,
                    HostelLeave.to_at > body.from_at,
                )
            )
        ).first()
        if overlap:
            raise rule("An active leave overlaps these dates", "OVERLAP")
        if body.leave_type in ("out_pass", "day_leave") and await self._exam_day(e.id, body.from_at, body.to_at):
            raise rule("Out-passes are not allowed on exam days (medical leave excepted)", "EXAM_DAY")
        st = (await self.db.execute(select(Student).where(Student.id == e.student_id))).scalar_one()
        required = await self.setting("hostel", "guardian_otp_required_for")
        if required is None:
            required = (
                ["home_leave", "medical"]
                if await self.setting("hostel", "guardian_otp_required_for_home_leave") in (None, True)
                else []
            )
        minor = await self.setting("hostel", "minor_requires_otp") in (None, True) and not await self.is_adult(st.dob)
        consent = "pending" if body.leave_type in (required or []) or minor else "not_required"
        h = (await self.db.execute(select(Hostel).where(Hostel.id == alloc.hostel_id))).scalar_one()
        leave = HostelLeave(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            hostel_id=alloc.hostel_id,
            leave_type=body.leave_type,
            from_at=body.from_at,
            to_at=body.to_at,
            destination=body.destination,
            reason=body.reason,
            guardian_consent=consent,
            status="requested",
        )
        self.db.add(leave)
        await self.db.flush()
        try:
            async with self.db.begin_nested():
                inst = await workflow_engine.start(
                    self.db,
                    institution_id=self.inst,
                    key="hostel.leave",
                    entity_type=ENTITY,
                    entity_id=leave.id,
                    started_by=self.actor_id,
                    context={
                        "warden_user_id": str(await self.warden_user(h)) if h.warden_staff_id else None,
                        "college_id": str(h.college_id),
                    },
                    title=f"{body.leave_type.replace('_', ' ').title()} · {st.registration_number}",
                )
                leave.workflow_instance_id = inst.id
        except APIError:
            pass
        await self.db.flush()
        await self.db.refresh(leave)
        await self._emit("hostel.leave_requested", {"leave_id": str(leave.id), "consent": consent}, ENTITY, leave.id)
        if consent == "pending":
            await self._send_otp(leave, st)
        elif body.leave_type == "out_pass" and await self.setting("hostel", "outpass_auto_approve"):
            await self._approve(leave, None)
        return (await self.outs([leave], show_qr=True))[0]

    # ---- consent -----------------------------------------------------------------------------------------------------
    async def _primary_phone(self, st: Student) -> str | None:
        g = (
            await self.db.execute(
                select(StudentGuardian.phone)
                .where(StudentGuardian.student_id == st.id, StudentGuardian.phone.is_not(None))
                .order_by(StudentGuardian.is_primary.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return g

    async def _send_otp(self, leave: HostelLeave, st: Student) -> dict[str, Any]:
        phone = await self._primary_phone(st)
        if not phone:
            raise rule("No guardian phone on record — ask the parent to approve in the app", "NO_GUARDIAN_PHONE")
        code = f"{secrets.randbelow(10**6):06d}"
        await redis_client.set(f"hostel_otp:{leave.id}", code, ex=OTP_TTL)
        await redis_client.delete(f"hostel_otp_tries:{leave.id}")
        from app.services.auth_service import _send_task

        _send_task(
            "notifications.send_sms_otp",
            {"institution_id": str(self.inst), "destination": phone, "code": code, "ttl": OTP_TTL},
        )
        await self._audit("consent_otp_sent", ENTITY, leave.id, None, {"phone": phone[-4:].rjust(len(phone), "*")})
        return {"sent": True, "ttl_seconds": OTP_TTL, "phone": phone[-4:].rjust(len(phone), "*")}

    async def send_otp(self, leave_id: uuid.UUID) -> dict[str, Any]:
        leave = await self._get(leave_id, for_update=True)
        if leave.guardian_consent != "pending":
            raise rule("Guardian consent is not pending", "CONSENT_NOT_PENDING")
        st = (
            await self.db.execute(
                select(Student)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == leave.student_program_enrollment_id)
            )
        ).scalar_one()
        return await self._send_otp(leave, st)

    async def verify_otp(self, leave_id: uuid.UUID, otp: str) -> HostelLeaveResponse:
        leave = await self._get(leave_id, for_update=True)
        if leave.guardian_consent != "pending":
            raise rule("Guardian consent is not pending", "CONSENT_NOT_PENDING")
        tries_key = f"hostel_otp_tries:{leave.id}"
        tries = int(await redis_client.get(tries_key) or 0)
        if tries >= 3:
            raise APIError(
                429, ErrorCode.RATE_LIMITED, "Too many wrong codes — request a new OTP", {"code": "OTP_LOCKED"}
            )
        expected = await redis_client.get(f"hostel_otp:{leave.id}")
        expected = expected.decode() if isinstance(expected, bytes) else expected
        if not expected or not secrets.compare_digest(str(expected), otp.strip()):
            await redis_client.incr(tries_key)
            await redis_client.expire(tries_key, OTP_TTL)
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Wrong or expired code",
                {"code": "OTP_INVALID", "attempts_left": max(2 - tries, 0)},
            )
        await redis_client.delete(f"hostel_otp:{leave.id}")
        return await self._consent(leave, "otp")

    async def parent_approve(self, leave_id: uuid.UUID) -> HostelLeaveResponse:
        leave = await self._get(leave_id, for_update=True)
        wards = set(await self.mine(wards=True)) - set(await self.mine())
        if leave.student_program_enrollment_id not in wards:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only a consented guardian may approve")
        if leave.guardian_consent != "pending":
            raise rule("Guardian consent is not pending", "CONSENT_NOT_PENDING")
        return await self._consent(leave, "parent_app")

    async def _consent(self, leave: HostelLeave, via: str) -> HostelLeaveResponse:
        leave.guardian_consent = "otp_verified"
        await self.db.flush()
        await self.db.refresh(leave)
        await self._audit("consent_verified", ENTITY, leave.id, None, {"via": via})
        await self._emit("hostel.consent_verified", {"leave_id": str(leave.id), "via": via}, ENTITY, leave.id)
        if leave.leave_type == "out_pass" and await self.setting("hostel", "outpass_auto_approve"):
            await self._approve(leave, None)
        return (await self.outs([leave], show_qr=True))[0]

    # ---- decide ------------------------------------------------------------------------------------------------------
    async def _approve(self, leave: HostelLeave, remarks: str | None) -> None:  # noqa: ARG002 - remarks live on the audit row
        leave.status = "approved"
        leave.approved_by = self.actor_id
        leave.qr_token = "hl" + secrets.token_hex(24)
        await self.db.flush()
        await self._emit("hostel.leave_decided", {"leave_id": str(leave.id), "status": "approved"}, ENTITY, leave.id)
        uid = await self.student_user(leave.student_program_enrollment_id)
        await self._notify(
            "hostel.leave_decided",
            [uid],
            {
                "from_date": leave.from_at.date().isoformat(),
                "to_date": leave.to_at.date().isoformat(),
                "status": "approved",
            },
            guardians=True,
        )

    async def decide(self, leave_id: uuid.UUID, body: HostelLeaveDecision) -> HostelLeaveResponse:
        leave = await self._get(leave_id, for_update=True)
        await self.require_hostel(leave.hostel_id, "warden")
        if leave.status != "requested":
            raise rule(f"The leave is {leave.status}", "ALREADY_DECIDED")
        if body.action == "approve":
            if leave.guardian_consent == "pending":
                raise rule("Guardian consent is pending", "CONSENT_PENDING")
            await self._approve(leave, body.remarks)
        else:
            leave.status = "rejected"
            leave.approved_by = self.actor_id
            await self.db.flush()
            await self._emit(
                "hostel.leave_decided", {"leave_id": str(leave.id), "status": "rejected"}, ENTITY, leave.id
            )
            await self._notify(
                "hostel.leave_decided",
                [await self.student_user(leave.student_program_enrollment_id)],
                {
                    "from_date": leave.from_at.date().isoformat(),
                    "to_date": leave.to_at.date().isoformat(),
                    "status": "rejected",
                },
            )
        if leave.workflow_instance_id and self.principal is not None:
            try:
                async with self.db.begin_nested():
                    await workflow_engine.act(
                        self.db,
                        instance_id=leave.workflow_instance_id,
                        actor=self.principal,
                        decision="approve" if body.action == "approve" else "reject",
                        comment=body.remarks,
                    )
            except APIError:
                pass
        await self._audit(f"leave_{body.action}", ENTITY, leave.id, None, {"remarks": body.remarks})
        await self.db.refresh(leave)
        return (await self.outs([leave]))[0]

    async def cancel(self, leave_id: uuid.UUID) -> HostelLeaveResponse:
        leave = await self._get(leave_id, for_update=True)
        if leave.student_program_enrollment_id not in await self.mine():
            raise APIError(404, ErrorCode.NOT_FOUND, "Leave not found")
        if leave.status not in ("requested", "approved"):
            raise rule("Only leaves not yet used can be cancelled", "NOT_CANCELLABLE")
        leave.status, leave.qr_token = "rejected", None
        await self.db.flush()
        await self._audit("leave_cancel", ENTITY, leave.id, None, None)
        await self.db.refresh(leave)
        return (await self.outs([leave]))[0]

    # ---- gate ------------------------------------------------------------------------------------------------------------
    async def _late_fine(self, minutes: int) -> int:
        cfg = (
            (
                await self.db.execute(
                    select(FineConfiguration).where(
                        FineConfiguration.institution_id == self.inst,
                        FineConfiguration.applies_to == "hostel",
                        FineConfiguration.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )
        if cfg is None or minutes <= 0:
            return 0
        hours = -(-minutes // 60)
        amount = (
            hours * int(cfg.amount_paise or 0) if cfg.calc_type in ("flat", "per_day") else int(cfg.amount_paise or 0)
        )
        return min(amount, int(cfg.max_paise)) if cfg.max_paise else amount

    async def _returned(self, leave: HostelLeave, at: datetime, *, manual: str | None = None) -> int | None:
        grace = int(
            await self.setting("hostel", "late_grace_minutes")
            or await self.setting("hostel", "late_return_grace_minutes")
            or 30
        )
        late = int((at - leave.to_at).total_seconds() // 60) - grace
        leave.actual_return_at = at
        if late > 0 or leave.status == "absconding":
            leave.status, leave.late_minutes = "late_return", max(late, 0)
            await self._late_consequences(leave)
        else:
            leave.status, leave.late_minutes = "returned", 0
        leave.qr_token = None
        await self.db.flush()
        await self._emit(
            "hostel.returned",
            {"leave_id": str(leave.id), "late_minutes": leave.late_minutes, "manual": bool(manual)},
            ENTITY,
            leave.id,
        )
        return leave.late_minutes

    async def _late_consequences(self, leave: HostelLeave) -> None:
        minutes = int(leave.late_minutes or 0)
        fine = await self._late_fine(minutes)
        repeats = (
            await self.db.execute(
                select(func.count())
                .select_from(HostelLeave)
                .where(
                    HostelLeave.student_program_enrollment_id == leave.student_program_enrollment_id,
                    HostelLeave.status == "late_return",
                    HostelLeave.id != leave.id,
                    HostelLeave.actual_return_at >= now_utc() - timedelta(days=90),
                )
            )
        ).scalar_one()
        action = "fine" if repeats and fine else "warning"
        rec = HostelDisciplinaryRecord(
            institution_id=self.inst,
            student_program_enrollment_id=leave.student_program_enrollment_id,
            hostel_id=leave.hostel_id,
            incident_on=(leave.actual_return_at or now_utc()).date(),
            description=f"Late return by {minutes} minutes (leave {leave.leave_type})",
            action=action,
            fine_paise=fine if action == "fine" else None,
            decided_by=self.actor_id,
        )
        self.db.add(rec)
        await self.db.flush()
        if action == "fine" and fine:
            rec.fee_invoice_id = await self.invoice(
                leave.student_program_enrollment_id,
                "hostel_disciplinary",
                rec.id,
                [(f"Late return fine ({minutes} min)", fine, "FINE")],
                "Hostel late-return fine",
            )
        st = (
            await self.db.execute(
                select(Student)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == leave.student_program_enrollment_id)
            )
        ).scalar_one()
        await self._emit(
            "hostel.late_return", {"leave_id": str(leave.id), "minutes": minutes, "action": action}, ENTITY, leave.id
        )
        await self._notify(
            "hostel.late_return",
            await self.guardian_users(leave.student_program_enrollment_id),
            {
                "student_name": " ".join(x for x in (st.first_name, st.last_name) if x),
                "time": (leave.actual_return_at or now_utc()).isoformat(timespec="minutes"),
            },
        )

    async def gate_scan(self, body: GateScanRequest) -> GateScanResponse:
        self.require("gate", "warden")
        leave = (
            await self.db.execute(
                select(HostelLeave)
                .where(HostelLeave.institution_id == self.inst, HostelLeave.qr_token == body.qr_token.strip())
                .with_for_update()
            )
        ).scalar_one_or_none()
        if leave is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Unknown or used pass")
        if not await self.owns_hostel(leave.hostel_id):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "This pass belongs to another hostel")
        at = body.scanned_at or now_utc()
        student = await self.ref(leave.student_program_enrollment_id)
        if body.direction == "out":
            if leave.status != "approved":
                raise rule(f"The pass is {leave.status}", "PASS_NOT_VALID")
            if at < leave.from_at - timedelta(hours=1) or at > leave.to_at:
                raise rule("The pass is outside its validity window", "PASS_EXPIRED")
            leave.status, leave.actual_out_at = "out", at
            await self.db.flush()
            await self._emit("hostel.marked_out", {"leave_id": str(leave.id)}, ENTITY, leave.id)
            await self._notify(
                "hostel.marked_out",
                await self.guardian_users(leave.student_program_enrollment_id),
                {"student": student.name or "", "time": at.isoformat(timespec="minutes")},
            )
            await self.db.refresh(leave)
            return GateScanResponse(student=student, leave=(await self.outs([leave]))[0], result="marked_out")
        if leave.status not in ("out", "absconding"):
            raise rule(f"The pass is {leave.status}", "PASS_NOT_OUT")
        late = await self._returned(leave, at)
        await self.db.refresh(leave)
        return GateScanResponse(
            student=student, leave=(await self.outs([leave]))[0], result=leave.status, late_minutes=late
        )

    async def gate_batch(self, scans: list[GateScanRequest]) -> list[GateScanResponse]:
        out = []
        for s in sorted(scans, key=lambda x: x.scanned_at or now_utc()):
            try:
                async with self.db.begin_nested():
                    out.append(await self.gate_scan(s))
            except APIError as exc:
                out.append(GateScanResponse(result="error", message=exc.message))
        return out

    async def mark_returned(self, leave_id: uuid.UUID, body: MarkReturned) -> HostelLeaveResponse:
        leave = await self._get(leave_id, for_update=True)
        await self.require_hostel(leave.hostel_id, "warden")
        if leave.status not in ("out", "absconding", "approved"):
            raise rule(f"The leave is {leave.status}", "NOT_OUT")
        await self._returned(leave, body.returned_at or now_utc(), manual=body.remarks)
        await self._audit(
            "mark_returned", ENTITY, leave.id, None, {"remarks": body.remarks, "late_minutes": leave.late_minutes}
        )
        await self.db.refresh(leave)
        return (await self.outs([leave]))[0]

    # ---- lists ---------------------------------------------------------------------------------------------------------
    async def list_leaves(
        self, hostel_id: uuid.UUID | None, status: str | None, on: date | None
    ) -> list[HostelLeaveResponse]:
        q = select(HostelLeave).where(
            HostelLeave.institution_id == self.inst,
            resident_predicate(self.principal, HostelLeave.student_program_enrollment_id, HostelLeave.hostel_id),
        )
        if hostel_id:
            q = q.where(HostelLeave.hostel_id == hostel_id)
        if status:
            q = q.where(HostelLeave.status == status)
        if on:
            q = q.where(func.date(HostelLeave.from_at) <= on, func.date(HostelLeave.to_at) >= on)
        rows = list((await self.db.execute(q.order_by(HostelLeave.from_at.desc()).limit(3000))).scalars().all())
        return await self.outs(rows)

    async def me(self, *, wards: bool = False) -> list[HostelLeaveResponse]:
        ids = await self.mine(wards=wards)
        rows = list(
            (
                await self.db.execute(
                    select(HostelLeave)
                    .where(HostelLeave.student_program_enrollment_id.in_(ids or [uuid.uuid4()]))
                    .order_by(HostelLeave.from_at.desc())
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows, show_qr=not wards)

    async def late_list(self, hostel_id: uuid.UUID | None) -> list[HostelLeaveResponse]:
        self.require("gate", "warden")
        now = now_utc()
        q = select(HostelLeave).where(
            HostelLeave.institution_id == self.inst,
            or_(HostelLeave.status == "absconding", (HostelLeave.status == "out") & (HostelLeave.to_at < now)),
        )
        q = q.where(
            HostelLeave.hostel_id.in_(
                select(Hostel.id).where(Hostel.id == hostel_id) if hostel_id else select(Hostel.id)
            )
        ).where(resident_predicate(self.principal, HostelLeave.student_program_enrollment_id, HostelLeave.hostel_id))
        return await self.outs(list((await self.db.execute(q.order_by(HostelLeave.to_at))).scalars().all()))

    async def out_now(self, hostel_id: uuid.UUID | None) -> list[HostelLeaveResponse]:
        self.require("gate", "warden")
        q = select(HostelLeave).where(
            HostelLeave.institution_id == self.inst,
            HostelLeave.status.in_(("out", "absconding")),
            resident_predicate(self.principal, HostelLeave.student_program_enrollment_id, HostelLeave.hostel_id),
        )
        if hostel_id:
            q = q.where(HostelLeave.hostel_id == hostel_id)
        return await self.outs(list((await self.db.execute(q.order_by(HostelLeave.to_at))).scalars().all()))

    # ---- Beat ----------------------------------------------------------------------------------------------------------
    async def absconding_scan(self) -> int:
        hours = int(await self.setting("hostel", "absconding_after_hours") or 12)
        cutoff = now_utc() - timedelta(hours=hours)
        rows = (
            (
                await self.db.execute(
                    select(HostelLeave)
                    .where(
                        HostelLeave.institution_id == self.inst, HostelLeave.status == "out", HostelLeave.to_at < cutoff
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for leave in rows:
            leave.status = "absconding"
            h = (await self.db.execute(select(Hostel).where(Hostel.id == leave.hostel_id))).scalar_one()
            student = await self.ref(leave.student_program_enrollment_id)
            await self._emit("hostel.absconding", {"leave_id": str(leave.id)}, ENTITY, leave.id)
            await self._notify(
                "hostel.absconding",
                [await self.warden_user(h), *await self.guardian_users(leave.student_program_enrollment_id)],
                {"student": student.name or "", "hostel": h.name, "due": leave.to_at.isoformat(timespec="minutes")},
                audience={
                    "user_ids": [
                        str(u)
                        for u in [
                            await self.warden_user(h),
                            *await self.guardian_users(leave.student_program_enrollment_id),
                        ]
                        if u
                    ],
                    "roles": ["registrar"],
                },
            )
        await self.db.flush()
        return len(rows)

    async def return_reminders(self) -> int:
        now = now_utc()
        rows = (
            (
                await self.db.execute(
                    select(HostelLeave).where(
                        HostelLeave.institution_id == self.inst,
                        HostelLeave.status == "out",
                        HostelLeave.to_at > now,
                        HostelLeave.to_at <= now + timedelta(hours=2),
                    )
                )
            )
            .scalars()
            .all()
        )
        for leave in rows:
            await self._notify(
                "hostel.leave_decided",
                [await self.student_user(leave.student_program_enrollment_id)],
                {
                    "from_date": leave.from_at.date().isoformat(),
                    "to_date": leave.to_at.isoformat(timespec="minutes"),
                    "status": "due back soon",
                },
            )
        return len(rows)

    async def active_allocation_ids(self) -> Any:
        return select(HostelAllocation.id).where(HostelAllocation.status.in_(ACTIVE_ALLOCATION))


@workflow_engine.on("hostel.leave", "approved")
async def _leave_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    leave = (
        await db.execute(select(HostelLeave).where(HostelLeave.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    if leave is None or leave.status != "requested" or leave.guardian_consent == "pending":
        return
    await LeaveService(db, actor, institution_id=instance.institution_id)._approve(leave, None)


@workflow_engine.on("hostel.leave", "rejected")
async def _leave_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    leave = (await db.execute(select(HostelLeave).where(HostelLeave.id == instance.entity_id))).scalar_one_or_none()
    if leave is not None and leave.status == "requested":
        leave.status = "rejected"
