"""No-dues clearance — Prompts/12 §12.6 ``no_dues_service``.

A request per purpose (graduation / transfer / hostel_vacate / exit / transcript; also auto-created by the
``transfer.requested`` consumer) opens one sign-off per department configured for the purpose (setting
``fees.no_dues_departments``) and a ``no_dues.clearance`` workflow instance (parallel step) for the inboxes. Each
sign-off belongs to one office:

    accounts → fees:collect       library → library:manage     hostel → hostel:manage
    department / lab → the HOD of the student's department     sports → sports:manage
    transport → transport:manage  placement → placement:manage (no_dues:manage signs anything)

A signer outside the office → 403. ``accounts`` pre-fills the open fee balance. Any ``dues_pending`` → request
``blocked`` (``no_dues.blocked``); every sign-off ``cleared`` → ``cleared`` + certificate number (``certificate_no``
sequence; the Phase 26 document links later) + event ``no_dues.cleared``.
"""

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.fees import OPEN_INVOICE
from app.models.fees import FeeInvoice, NoDuesRequest, NoDuesSignoff
from app.models.platform import AuditLog, WorkflowInstance, WorkflowStep
from app.repositories.fee_repository import NoDuesRepository
from app.repositories.fee_scope import visibility
from app.schemas.no_dues import NoDuesCreate, NoDuesResponse, NoDuesSignoffOut, SignoffRequest
from app.services.fees.common import FeesBase, rupees, student_name
from app.utils.response import VisibilityMeta

WF = "no_dues.clearance"
ENTITY = "no_dues_request"
DEFAULT_DEPARTMENTS = {
    "graduation": ["accounts", "library", "hostel", "department", "lab", "sports"],
    "transfer": ["accounts", "library", "hostel", "department", "lab", "sports"],
    "exit": ["accounts", "library", "hostel", "department", "lab", "sports"],
    "hostel_vacate": ["accounts", "hostel"],
    "transcript": ["accounts", "library"],
}
OFFICE_PERMISSION = {
    "accounts": ("fees", "collect"),
    "library": ("library", "manage"),
    "hostel": ("hostel", "manage"),
    "sports": ("sports", "manage"),
    "transport": ("transport", "manage"),
    "placement": ("placement", "manage"),
}


class NoDuesService(FeesBase):
    audit_module = "no_dues"

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.requests = NoDuesRepository(self.db, self.principal, self.inst)

    # ---- ownership ------------------------------------------------------------------------------------------------------
    def owns(self, key: str, department_id: uuid.UUID | None) -> bool:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False) or p.has("no_dues", "manage"):
            return True
        if key in ("department", "lab"):
            depts = [sid for st, sid in getattr(p, "scopes", []) if st == "department"]
            return "hod" in (getattr(p, "roles", []) or []) and department_id in depts
        perm = OFFICE_PERMISSION.get(key)
        if perm is None:
            return False
        return bool(p.has(*perm))

    def my_keys(self) -> list[str]:
        keys = ["accounts", "library", "hostel", "department", "lab", "sports", "transport", "placement"]
        out = []
        for k in keys:
            if k in ("department", "lab"):
                if self.principal is not None and (
                    "hod" in (getattr(self.principal, "roles", []) or [])
                    or getattr(self.principal, "is_super_admin", False)
                ):
                    out.append(k)
            elif self.owns(k, None):
                out.append(k)
        return out

    # ---- responses ----------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[NoDuesRequest]) -> list[NoDuesResponse]:
        ids = [r.id for r in rows]
        signs: dict[uuid.UUID, list[NoDuesSignoff]] = {i: [] for i in ids}
        if ids:
            for s in (
                await self.db.execute(
                    select(NoDuesSignoff)
                    .where(NoDuesSignoff.request_id.in_(ids))
                    .order_by(NoDuesSignoff.department_key)
                )
            ).scalars():
                signs[s.request_id].append(s)
        certs: dict[Any, Any] = (
            dict(
                (  # type: ignore[arg-type]
                    await self.db.execute(
                        select(AuditLog.record_id, AuditLog.new_values).where(
                            AuditLog.record_type == ENTITY, AuditLog.action == "cleared", AuditLog.record_id.in_(ids)
                        )
                    )
                ).all()
            )
            if ids
            else {}
        )
        out = []
        for r in rows:
            enrol, st = await self.enrolment(r.student_program_enrollment_id)
            o = NoDuesResponse.model_validate(r)
            o.student_name, o.registration_number = student_name(st), st.registration_number
            o.certificate_number = (certs.get(r.id) or {}).get("certificate_number")
            o.signoffs = []
            for s in signs[r.id]:
                so = NoDuesSignoffOut.model_validate(s)
                so.can_sign = r.status in ("requested", "in_progress", "blocked") and self.owns(
                    s.department_key, enrol.department_id
                )
                o.signoffs.append(so)
            out.append(o)
        return out

    # ---- create -------------------------------------------------------------------------------------------------------
    async def create(self, body: NoDuesCreate, *, system: bool = False) -> NoDuesResponse:
        if system and body.enrollment_id or body.enrollment_id and self.can("no_dues", "manage"):
            enrol, st = await self.enrolment(body.enrollment_id)
        else:
            enrol, st = await self.my_enrollment(body.enrollment_id)
        purpose = str(body.purpose)
        live = (
            await self.db.execute(
                select(NoDuesRequest).where(
                    NoDuesRequest.student_program_enrollment_id == enrol.id,
                    NoDuesRequest.purpose == purpose,
                    NoDuesRequest.status.in_(("requested", "in_progress", "blocked")),
                )
            )
        ).scalar_one_or_none()
        if live is not None:
            if system:
                return (await self.outs([live]))[0]
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "A no-dues request for this purpose is already open",
                {"request_id": str(live.id)},
            )
        cfg = await self.setting("fees", "no_dues_departments") or {}
        depts = list(
            (cfg.get(purpose) if isinstance(cfg, dict) else None) or DEFAULT_DEPARTMENTS.get(purpose, ["accounts"])
        )
        r = NoDuesRequest(
            institution_id=self.inst, student_program_enrollment_id=enrol.id, purpose=purpose, status="in_progress"
        )
        self.db.add(r)
        await self.db.flush()
        dues = await self.fee_dues(enrol.id)
        for k in depts:
            s = NoDuesSignoff(
                institution_id=self.inst,
                request_id=r.id,
                department_key=k,
                status="pending",
                dues_paise=dues if k == "accounts" else 0,
            )
            self.db.add(s)
        await self.db.flush()
        with contextlib.suppress(APIError):
            await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF,
                entity_type=ENTITY,
                entity_id=r.id,
                started_by=self.actor_id,
                context={"department_id": str(enrol.department_id), "college_id": str(enrol.college_id)},
                title=f"No dues · {purpose} · {st.registration_number}",
            )
        await self._audit("create", ENTITY, r.id, None, {"purpose": purpose, "departments": depts})
        await self._emit(
            "no_dues.requested",
            {"request_id": str(r.id), "purpose": purpose, "student_program_enrollment_id": str(enrol.id)},
            ENTITY,
            r.id,
        )
        return (await self.outs([r]))[0]

    async def fee_dues(self, enrol_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0)).where(
                        FeeInvoice.student_program_enrollment_id == enrol_id, FeeInvoice.status.in_(tuple(OPEN_INVOICE))
                    )
                )
            ).scalar_one()
        )

    # ---- reads --------------------------------------------------------------------------------------------------------
    async def list_requests(
        self, scope: str | None, status: str | None = None, department_key: str | None = None
    ) -> tuple[list[NoDuesResponse], VisibilityMeta]:
        if scope == "department" and department_key is None:
            keys = self.my_keys()
            q = self.requests._base().where(
                NoDuesRequest.id.in_(select(NoDuesSignoff.request_id).where(NoDuesSignoff.department_key.in_(keys)))
            )
        elif department_key:
            q = self.requests._base().where(
                NoDuesRequest.id.in_(
                    select(NoDuesSignoff.request_id).where(NoDuesSignoff.department_key == department_key)
                )
            )
            if department_key in ("department", "lab") and not self.can("no_dues", "manage"):
                from app.models.students import StudentProgramEnrollment

                depts = [sid for st, sid in getattr(self.principal, "scopes", []) if st == "department"]
                q = q.where(
                    NoDuesRequest.student_program_enrollment_id.in_(
                        select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id.in_(depts))
                    )
                )
            elif department_key not in self.my_keys():
                q = self.requests.scoped(scope)
        else:
            q = self.requests.scoped(scope)
        if status:
            q = q.where(NoDuesRequest.status == status)
        rows = list((await self.db.execute(q.order_by(NoDuesRequest.requested_at.desc()).limit(500))).scalars().all())
        meta = visibility(self.principal, "no_dues")
        meta.scopes = sorted(set(meta.scopes) | ({"department"} if self.my_keys() else set()))
        return await self.outs(rows), meta

    async def get(self, rid: uuid.UUID) -> NoDuesResponse:
        r = await self._visible_or_owned(rid)
        return (await self.outs([r]))[0]

    async def _visible_or_owned(self, rid: uuid.UUID, for_update: bool = False) -> NoDuesRequest:
        try:
            return await self.requests.get_visible(rid, for_update=for_update)
        except APIError:
            q = select(NoDuesRequest).where(NoDuesRequest.id == rid, NoDuesRequest.institution_id == self.inst)
            if for_update:
                q = q.with_for_update()
            r = (await self.db.execute(q)).scalar_one_or_none()
            if r is None or not self.my_keys():
                raise
            return r

    async def mine(self) -> list[NoDuesResponse]:
        rows = list(
            (await self.db.execute(self.requests.scoped("self").order_by(NoDuesRequest.requested_at.desc())))
            .scalars()
            .all()
        )
        return await self.outs(rows)

    # ---- sign-off -----------------------------------------------------------------------------------------------------
    async def signoff(self, rid: uuid.UUID, body: SignoffRequest) -> NoDuesResponse:
        r = await self._visible_or_owned(rid, for_update=True)
        if r.status == "cleared":
            raise APIError(409, ErrorCode.CONFLICT, "The request is already cleared")
        enrol, st = await self.enrolment(r.student_program_enrollment_id)
        signs = (
            (await self.db.execute(select(NoDuesSignoff).where(NoDuesSignoff.request_id == r.id).with_for_update()))
            .scalars()
            .all()
        )
        key = body.department_key
        if key is None:
            mine = [s.department_key for s in signs if self.owns(s.department_key, enrol.department_id)]
            if len(mine) != 1:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "department_key is required",
                    {"field": "department_key", "options": mine},
                )
            key = mine[0]
        s = next((x for x in signs if x.department_key == key), None)
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"No {key} sign-off on this request")
        if not self.owns(key, enrol.department_id):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, f"You may not sign off for {key}", {"department_key": key})
        if key == "accounts" and body.status == "cleared":
            dues = await self.fee_dues(enrol.id)
            if dues > 0:
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    f"Fee dues of {rupees(dues)} are open",
                    {"code": "DUES_OPEN", "dues_paise": dues},
                )
        old = s.status
        s.status, s.dues_paise, s.remarks, s.signed_by, s.signed_at = (
            body.status,
            body.dues_paise if body.status == "dues_pending" else 0,
            body.remarks,
            self.actor_id,
            datetime.now(UTC),
        )
        await self.db.flush()
        await self._audit(
            "signoff",
            ENTITY,
            r.id,
            {"department_key": key, "status": old},
            {"department_key": key, "status": body.status, "dues_paise": s.dues_paise},
        )
        await self._emit(
            "no_dues.signoff", {"request_id": str(r.id), "department_key": key, "status": body.status}, ENTITY, r.id
        )
        await self._settle(r, list(signs), st)
        return (await self.outs([r]))[0]

    async def _settle(self, r: NoDuesRequest, signs: list[NoDuesSignoff], st: Any) -> None:
        statuses = {s.status for s in signs}
        if "dues_pending" in statuses:
            if r.status != "blocked":
                r.status = "blocked"
                await self.db.flush()
                await self._emit("no_dues.blocked", {"request_id": str(r.id)}, ENTITY, r.id)
                await self._notify(
                    "no_dues.blocked",
                    [st.user_id],
                    {
                        "purpose": r.purpose,
                        "departments": ", ".join(s.department_key for s in signs if s.status == "dues_pending"),
                    },
                )
            return
        if statuses == {"cleared"}:
            r.status, r.cleared_at = "cleared", datetime.now(UTC)
            number = await self.sequence("certificate_no", "NDC")
            await self.db.flush()
            await self._close_instance(r.id, "approved")
            await self._audit("cleared", ENTITY, r.id, None, {"certificate_number": number})
            await self._emit(
                "no_dues.cleared",
                {
                    "request_id": str(r.id),
                    "purpose": r.purpose,
                    "student_program_enrollment_id": str(r.student_program_enrollment_id),
                    "certificate_number": number,
                },
                ENTITY,
                r.id,
            )
            await self._notify("no_dues.cleared", [st.user_id], {"purpose": r.purpose, "certificate_no": number})
            return
        if r.status == "blocked":
            r.status = "in_progress"
            await self.db.flush()

    async def _close_instance(self, rid: uuid.UUID, status: str) -> None:
        inst = (
            await self.db.execute(
                select(WorkflowInstance)
                .where(
                    WorkflowInstance.entity_type == ENTITY,
                    WorkflowInstance.entity_id == rid,
                    WorkflowInstance.status.in_(("pending", "escalated")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if inst is None:
            return
        for step in (
            await self.db.execute(
                select(WorkflowStep).where(
                    WorkflowStep.instance_id == inst.id, WorkflowStep.status.in_(("pending", "escalated"))
                )
            )
        ).scalars():
            step.status = "skipped"
        inst.status, inst.closed_at = status, datetime.now(UTC)
        await self.db.flush()

    async def certificate_pdf(self, rid: uuid.UUID) -> tuple[bytes, str]:
        from app.utils.pdf import render_pdf

        o = await self.get(rid)
        if o.status != "cleared":
            raise APIError(409, ErrorCode.CONFLICT, "The request is not cleared yet")
        inst = await self.institution()
        lines = [
            inst.name,
            "NO DUES CERTIFICATE",
            f"Certificate: {o.certificate_number}",
            f"Student: {o.student_name} ({o.registration_number})",
            f"Purpose: {o.purpose}",
            f"Cleared on: {o.cleared_at.date().isoformat() if o.cleared_at else ''}",
            "",
        ]
        lines += [
            f"{s.department_key:12s} cleared {s.signed_at.date().isoformat() if s.signed_at else ''}"
            for s in o.signoffs
        ]
        html = "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>"
        return render_pdf(html, lines, title="No dues certificate"), str(o.certificate_number or "no-dues")


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    r = (await db.execute(select(NoDuesRequest).where(NoDuesRequest.id == entity_id))).scalar_one_or_none()
    return (f"No-dues clearance · {r.purpose} ({r.status})", "/admin/fees/no-dues") if r else (None, None)
