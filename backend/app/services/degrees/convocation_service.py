"""Convocations — Prompts/18 §18.6 ``convocation_service`` (feature ``degrees.convocation``).

Events ``planned → registration_open → closed → completed`` (``CONVOCATION_FLOW``; ``closed`` may reopen). Registration
by the student / alumnus (or staff on behalf with ``degrees:convocation_manage``): the enrolment's latest eligibility
check must be eligible (or overridden), or an award must already exist — else 409 ``NOT_ELIGIBLE``; the deadline is
inclusive (409 ``DEADLINE_PASSED``). A fee creates a Phase 12 linkage invoice (``source_type='convocation_registration'``,
head type ``convocation``) and the registration waits as ``fee_pending`` until the ``convocation.fee_paid`` consumer
marks it ``registered``. The attendance QR is an HMAC of the registration id (``cv.<id>.<sig>``); scanning marks
``attended``. Reports: gowns (size counts), seating (in-person, by programme / registration number), attendance.
"""

import hashlib
import hmac
import uuid
from collections import Counter
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.enums.degrees import CONVOCATION_FLOW
from app.models.degrees import Convocation, ConvocationRegistration, DegreeAwarded
from app.models.fees import FeeInvoice
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.degree_scope import enrollment_predicate
from app.schemas.degrees import (
    AttendanceMark,
    ConvocationIn,
    ConvocationOut,
    ConvocationRegister,
    ConvocationRegistrationResponse,
    ConvocationStatusChange,
    ConvocationUpdate,
)
from app.services.degrees.common import DegreeBase, rule
from app.services.degrees.eligibility_service import EligibilityService

ENTITY = "convocation"


def attendance_token(reg_id: uuid.UUID) -> str:
    sig = hmac.new(settings.SECRET_KEY.encode(), f"cv:{reg_id}".encode(), hashlib.sha256).hexdigest()[:20]
    return f"cv.{reg_id.hex}.{sig}"


def parse_attendance_token(token: str) -> uuid.UUID | None:
    try:
        prefix, rid, sig = token.split(".")
        reg_id = uuid.UUID(rid)
    except ValueError:
        return None
    if prefix != "cv" or not hmac.compare_digest(attendance_token(reg_id), token):
        return None
    return reg_id


class ConvocationService(DegreeBase):
    def require_manage(self) -> None:
        if not (self.can("degrees", "convocation_manage") or self.can("degrees", "manage")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:convocation_manage required")

    async def _get(self, cid: uuid.UUID, *, for_update: bool = False) -> Convocation:
        q = select(Convocation).where(Convocation.id == cid, Convocation.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Convocation not found")
        return row

    async def _out(self, c: Convocation) -> ConvocationOut:
        counts: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(ConvocationRegistration.status, func.count())
                    .where(ConvocationRegistration.convocation_id == c.id)
                    .group_by(ConvocationRegistration.status)
                )
            ).all()
        )
        absentia = (
            await self.db.execute(
                select(func.count())
                .select_from(ConvocationRegistration)
                .where(ConvocationRegistration.convocation_id == c.id, ConvocationRegistration.mode == "absentia")
            )
        ).scalar_one()
        return ConvocationOut(
            id=c.id,
            name=c.name,
            held_on=c.held_on,
            venue=c.venue,
            registration_deadline=c.registration_deadline,
            fee_paise=c.fee_paise,
            status=c.status,
            counts={
                **{str(k): int(v) for k, v in counts.items()},
                "absentia": int(absentia),
                "total": sum(counts.values()),
            },
            created_at=c.created_at,
        )

    async def list_convocations(self) -> list[ConvocationOut]:
        rows = (
            (
                await self.db.execute(
                    select(Convocation)
                    .where(Convocation.institution_id == self.inst)
                    .order_by(Convocation.held_on.desc().nulls_last())
                )
            )
            .scalars()
            .all()
        )
        return [await self._out(c) for c in rows]

    async def get(self, cid: uuid.UUID) -> ConvocationOut:
        return await self._out(await self._get(cid))

    async def create(self, body: ConvocationIn) -> ConvocationOut:
        self.require_manage()
        c = Convocation(institution_id=self.inst, **body.model_dump())
        self.db.add(c)
        await self.db.flush()
        await self.db.refresh(c)
        await self._audit("convocation_create", ENTITY, c.id, None, body.model_dump(mode="json"))
        return await self._out(c)

    async def update(self, cid: uuid.UUID, body: ConvocationUpdate) -> ConvocationOut:
        self.require_manage()
        c = await self._get(cid, for_update=True)
        if c.status == "completed":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Completed convocations are closed")
        data = body.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(c, k, v)
        await self.db.flush()
        await self.db.refresh(c)
        await self._audit("convocation_update", ENTITY, c.id, None, body.model_dump(mode="json", exclude_unset=True))
        return await self._out(c)

    async def change_status(self, cid: uuid.UUID, body: ConvocationStatusChange) -> ConvocationOut:
        self.require_manage()
        c = await self._get(cid, for_update=True)
        if body.status not in CONVOCATION_FLOW.get(c.status, ()):
            raise rule(f"Cannot move a {c.status} convocation to {body.status}", "INVALID_TRANSITION")
        old = c.status
        c.status = body.status
        await self.db.flush()
        await self.db.refresh(c)
        await self._audit("convocation_status", ENTITY, c.id, {"status": old}, {"status": c.status})
        if body.status == "registration_open":
            await self._emit("convocation.registration_open", {"convocation_id": str(c.id)}, ENTITY, c.id)
            await self._notify(
                "convocation.registration_open",
                [],
                {"name": c.name, "deadline": c.registration_deadline.isoformat() if c.registration_deadline else "—"},
                audience={"roles": ["student", "alumni"]},
            )
        elif body.status == "closed":
            await self._emit("convocation.registration_closed", {"convocation_id": str(c.id)}, ENTITY, c.id)
        return await self._out(c)

    # ---- registration --------------------------------------------------------------------------------------------------
    async def eligible_for(self, enrollment_id: uuid.UUID) -> bool:
        chk = await EligibilityService(self.db, self.principal, self.request, self.inst).latest(enrollment_id)
        if chk is not None and chk.is_eligible:
            return True
        return (
            await self.db.execute(
                select(DegreeAwarded.id).where(
                    DegreeAwarded.student_program_enrollment_id == enrollment_id,
                    DegreeAwarded.status.in_(("recommended", "council_approved", "issued")),
                )
            )
        ).first() is not None

    async def register(self, cid: uuid.UUID, body: ConvocationRegister) -> ConvocationRegistrationResponse:
        c = await self._get(cid, for_update=True)
        if c.status != "registration_open":
            raise rule("Registration is not open", "REGISTRATION_CLOSED", current=c.status)
        today = await self.today()
        if c.registration_deadline and today > c.registration_deadline:
            raise rule("The registration deadline has passed", "DEADLINE_PASSED")
        if body.enrollment_id:
            if body.enrollment_id not in await self.mine():
                self.require_manage()
            e = await self.enrolment(body.enrollment_id)
        else:
            own = await self.mine()
            if not own:
                raise APIError(404, ErrorCode.NOT_FOUND, "No enrolment of yours to register")
            e = await self.enrolment(own[0])
        if not await self.eligible_for(e.id):
            raise rule("Not eligible for the degree yet", "NOT_ELIGIBLE")
        existing = (
            await self.db.execute(
                select(ConvocationRegistration).where(
                    ConvocationRegistration.convocation_id == c.id,
                    ConvocationRegistration.student_program_enrollment_id == e.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise rule(
                "Already registered for this convocation", "ALREADY_REGISTERED", registration_id=str(existing.id)
            )
        reg = ConvocationRegistration(
            institution_id=self.inst,
            convocation_id=c.id,
            student_program_enrollment_id=e.id,
            mode=body.mode,
            gown_size=body.gown_size if body.mode == "in_person" else None,
            guests=body.guests if body.mode == "in_person" else 0,
            status="fee_pending" if c.fee_paise > 0 else "registered",
        )
        self.db.add(reg)
        await self.db.flush()
        if c.fee_paise > 0:
            from app.services.fees.invoice_service import InvoiceService

            inv = await InvoiceService(self.db, None, self.request, self.inst).link(
                "convocation_registration",
                reg.id,
                c.fee_paise,
                e.id,
                f"Convocation fee — {c.name}"[:200],
                head_type="convocation",
            )
            reg.fee_invoice_id = inv.id
        await self.db.flush()
        await self.db.refresh(reg)
        await self._audit(
            "convocation_register", "convocation_registration", reg.id, None, body.model_dump(mode="json")
        )
        await self._emit(
            "convocation.registered", {"registration_id": str(reg.id), "convocation_id": str(c.id)}, ENTITY, c.id
        )
        return (await self.reg_outs([reg]))[0]

    async def on_paid(self, reg_id: uuid.UUID) -> None:
        reg = (
            await self.db.execute(
                select(ConvocationRegistration).where(ConvocationRegistration.id == reg_id).with_for_update()
            )
        ).scalar_one_or_none()
        if reg is None or reg.status != "fee_pending":
            return
        reg.status = "registered"
        await self.db.flush()
        await self._audit(
            "convocation_fee_paid",
            "convocation_registration",
            reg.id,
            {"status": "fee_pending"},
            {"status": "registered"},
        )

    async def reg_outs(self, rows: list[ConvocationRegistration]) -> list[ConvocationRegistrationResponse]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        names: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(Convocation.id, Convocation.name).where(
                        Convocation.id.in_({r.convocation_id for r in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        fees: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(FeeInvoice.id, FeeInvoice.status).where(
                        FeeInvoice.id.in_({r.fee_invoice_id for r in rows if r.fee_invoice_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        return [
            ConvocationRegistrationResponse(
                id=r.id,
                convocation_id=r.convocation_id,
                convocation=names.get(r.convocation_id),
                enrollment=refs.get(r.student_program_enrollment_id) or {"id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                mode=r.mode,
                gown_size=r.gown_size,
                guests=r.guests,
                status=r.status,
                fee_invoice_id=r.fee_invoice_id,
                fee_status=fees.get(r.fee_invoice_id) if r.fee_invoice_id else None,
                attendance_token=attendance_token(r.id)
                if r.mode == "in_person" and r.status in ("registered", "attended")
                else None,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def registrations(self, cid: uuid.UUID, status: str | None = None) -> list[ConvocationRegistrationResponse]:
        await self._get(cid)
        q = select(ConvocationRegistration).where(
            ConvocationRegistration.convocation_id == cid,
            enrollment_predicate(self.principal, ConvocationRegistration.student_program_enrollment_id),
        )
        if status:
            q = q.where(ConvocationRegistration.status == status)
        rows = list((await self.db.execute(q.order_by(ConvocationRegistration.created_at))).scalars().all())
        out = await self.reg_outs(rows)
        return sorted(out, key=lambda r: (r.enrollment.program_code or "", r.enrollment.registration_number or ""))

    async def mine_registrations(self) -> list[ConvocationRegistrationResponse]:
        rows = list(
            (
                await self.db.execute(
                    select(ConvocationRegistration).where(
                        ConvocationRegistration.student_program_enrollment_id.in_(await self.mine() or [uuid.uuid4()])
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.reg_outs(rows)

    async def mark_attendance(self, cid: uuid.UUID, body: AttendanceMark) -> ConvocationRegistrationResponse:
        self.require_manage()
        rid = parse_attendance_token(body.token) if body.token else body.registration_id
        if rid is None:
            raise APIError(422, ErrorCode.VALIDATION, "Invalid attendance QR", {"code": "BAD_TOKEN"})
        reg = (
            await self.db.execute(
                select(ConvocationRegistration)
                .where(ConvocationRegistration.id == rid, ConvocationRegistration.convocation_id == cid)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if reg is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Registration not found for this convocation")
        if reg.status not in ("registered", "attended"):
            raise rule(f"Registration is {reg.status}", "NOT_REGISTERED")
        reg.status = "attended"
        await self.db.flush()
        await self.db.refresh(reg)
        return (await self.reg_outs([reg]))[0]

    async def report(self, cid: uuid.UUID, kind: str) -> list[dict[str, Any]]:
        regs = await self.registrations(cid)
        if kind == "gowns":
            sizes = Counter(
                r.gown_size or "—" for r in regs if r.mode == "in_person" and r.status in ("registered", "attended")
            )
            return [{"gown_size": k, "count": v} for k, v in sorted(sizes.items())]
        if kind == "seating":
            seats = [r for r in regs if r.mode == "in_person" and r.status in ("registered", "attended")]
            return [
                {
                    "seat": i + 1,
                    "registration_number": r.enrollment.registration_number,
                    "name": r.enrollment.student_name,
                    "program": r.enrollment.program_code,
                    "guests": r.guests or 0,
                }
                for i, r in enumerate(seats)
            ]
        if kind == "attendance":
            return [
                {
                    "registration_number": r.enrollment.registration_number,
                    "name": r.enrollment.student_name,
                    "mode": r.mode,
                    "status": r.status,
                }
                for r in regs
            ]
        raise APIError(422, ErrorCode.VALIDATION, "report must be gowns, seating or attendance")

    async def reminders(self) -> int:
        """Daily while registration is open: remind eligible students who have not registered."""
        today = await self.today()
        convs = (
            (
                await self.db.execute(
                    select(Convocation).where(
                        Convocation.institution_id == self.inst, Convocation.status == "registration_open"
                    )
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for c in convs:
            if c.registration_deadline and (c.registration_deadline - today).days not in (7, 3, 1):
                continue
            registered = select(ConvocationRegistration.student_program_enrollment_id).where(
                ConvocationRegistration.convocation_id == c.id
            )
            users = (
                (
                    await self.db.execute(
                        select(Student.user_id)
                        .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                        .join(
                            DegreeAwarded,
                            DegreeAwarded.student_program_enrollment_id == StudentProgramEnrollment.id,
                            isouter=True,
                        )
                        .where(
                            StudentProgramEnrollment.institution_id == self.inst,
                            StudentProgramEnrollment.id.notin_(registered),
                            DegreeAwarded.status.in_(("recommended", "council_approved", "issued")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            await self._notify(
                "convocation.registration_open",
                list(users),
                {"name": c.name, "deadline": c.registration_deadline.isoformat() if c.registration_deadline else "—"},
            )
            n += len(users)
        return n
