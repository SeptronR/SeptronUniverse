"""Self-service certificate requests — Prompts/26 §26.6 ``request_service`` ({documents.certificate_requests}).

1. **Create** (student / guardian on behalf of a ward / staff / alumni) for a type allowed by the request rules
   (``documents.request_rules`` merged over ``DEFAULT_REQUEST_RULES``: fee per copy, approver role, SLA days,
   ``requires_no_dues``, ``requires_status``, ``hold_types``, ``allowed_for``, ``allow_parent``, ``recommend_hod``,
   ``auto_generate``). Alumni prove identity with their registration number (the alumni user's linked student).
   A duplicate live request of the same type → 409. A fee (``fee × copies``) raises an invoice
   ``source_type='certificate_request'`` → ``fee_pending`` until ``fees.payment_received``; free types go straight on.
2. **Approval**: registrar types run the shipped ``certificates.request`` workflow (inbox); types whose approver is
   another role (HR for staff letters, COE for exam documents) are decided on the request page by a
   ``certificates:request_approve`` holder of that role (the per-type approver override of §26.6.2). An optional HOD
   ``recommend`` step comes first. TC / migration (``requires_no_dues``) auto-create ``no_dues_requests(purpose=
   'transfer')`` and wait (stage ``awaiting_no_dues``) until ``no_dues.cleared``. At approval, active holds of the
   rule's ``hold_types`` → 409 ``HOLD_<TYPE>`` (stage ``blocked``).
3. **Generate** (office, or automatically on approval when ``auto_generate``) → ``render()`` on the request entity →
   ``generated``; **issue**: digital (signed link + notification) → ``issued``; pickup → pickup notice (stage
   ``pickup_ready``), ``collected`` with the collector's name / signature → ``issued``; post → courier reference →
   ``issued``. **Reject** with reason; a paid invoice raises a refund request (Phase 12).

Request facts without columns (timeline, address, checks, stage, pickup, courier, recommendation, SLA reminders) live
in ``documents_meta`` ``req:<id>``.
"""

import contextlib
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_, select, text, true

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.documents import DEFAULT_REQUEST_RULES, REGISTERS
from app.models.documents import CertificateRequest, IssuedDocument
from app.models.fees import FeeInvoice, NoDuesRequest
from app.models.hr import Staff
from app.models.platform import WorkflowInstance
from app.models.students import Student, StudentHold, StudentProgramEnrollment
from app.schemas.documents import (
    CertReqCollected,
    CertReqCreate,
    CertReqDecision,
    CertReqGenerate,
    CertReqIssue,
    CertReqOut,
    CertReqTypeOut,
)
from app.services.documents.common import DocumentsBase, forbidden, not_found, now_utc, rule
from app.services.documents.defaults import TITLES
from app.services.facilities.common import dept_subquery, institution_scope, scope_ids

WF = "certificates.request"
ENTITY = "certificate_request"
LIVE = ("requested", "fee_pending", "approved", "generated")


class RequestService(DocumentsBase):
    # ---- rules ----------------------------------------------------------------------------------------------------------
    async def rules(self) -> dict[str, dict[str, Any]]:
        configured = await self.doc_setting("request_rules", {})
        out = {k: dict(v) for k, v in DEFAULT_REQUEST_RULES.items()}
        if isinstance(configured, dict):
            for k, v in configured.items():
                if isinstance(v, dict):
                    out[k] = {**out.get(k, {}), **v}
                elif v is None:
                    out.pop(k, None)
        return out

    async def rule_for(self, template_type: str) -> dict[str, Any]:
        r = (await self.rules()).get(template_type)
        if r is None:
            raise APIError(
                422, ErrorCode.VALIDATION, f"{template_type} cannot be requested", {"code": "NOT_REQUESTABLE"}
            )
        return r

    def approver_ok(self, rl: dict[str, Any]) -> bool:
        """The caller may decide requests governed by ``rl`` (approver role or registrar-like)."""
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return True
        if not (self.can("certificates", "request_approve") or self.can("certificates", "manage")):
            return False
        approver = str(rl.get("approver") or "registrar")
        roles = self.roles()
        return approver in roles or bool(roles & {"registrar", "institution_admin"})

    # ---- identity ---------------------------------------------------------------------------------------------------------
    async def alumni_student(self) -> Student | None:
        if self.actor_id is None:
            return None
        sid = (
            await self.db.execute(
                text("SELECT student_id FROM alumni_profiles WHERE user_id = :u AND institution_id = :i LIMIT 1"),
                {"u": self.actor_id, "i": self.inst},
            )
        ).scalar_one_or_none()
        if sid is None:
            return None
        return (await self.db.execute(select(Student).where(Student.id == sid))).scalar_one_or_none()

    async def alumni_verified(self) -> None:
        """Phase 29 requests bridge: an unverified alumni profile is refused (403 ``VERIFICATION_REQUIRED``)."""
        from app.services.alumni.stats_service import RequestsBridge

        await RequestsBridge(self.db, self.principal, self.request, self.inst).require_verified_alumni()

    async def resolve_person(self, body: CertReqCreate, rl: dict[str, Any]) -> tuple[str, uuid.UUID, str | None]:
        """``(person_type, person_id, on_behalf)``."""
        if body.person_id is not None:
            if body.person_id in await self.ward_ids():
                if not (rl.get("allow_parent") and await self.doc_setting("allow_parent_requests", False)):
                    raise forbidden("Guardian requests are not allowed for this certificate")
                return "student", body.person_id, "guardian"
            mine = await self.my_person_ids()
            if body.person_id not in mine:
                raise forbidden("You can request only for yourself or a consented ward")
        if body.person_type == "alumni":
            st = await self.alumni_student()
            if st is None:
                raise forbidden("Your account is not linked to an alumni record")
            if (
                not body.registration_number
                or body.registration_number.strip().upper() != (st.registration_number or "").upper()
            ):
                raise forbidden("Registration number does not match your alumni record")
            await self.alumni_verified()
            return "alumni", st.id, None
        if body.person_type in (None, "student"):
            st = await self.my_student()
            if st is not None:
                return "student", st.id, None
            if body.person_type == "student":
                raise rule("Your account is not linked to a student record", "NO_PERSON")
        sf = await self.my_staff()
        if sf is not None and body.person_type in (None, "staff"):
            return "staff", sf.id, None
        st = await self.alumni_student()
        if st is not None:
            await self.alumni_verified()
            return "alumni", st.id, None
        raise rule("Your account is not linked to a student, staff or alumni record", "NO_PERSON")

    async def enrolment(self, student_id: uuid.UUID) -> StudentProgramEnrollment | None:
        return (
            await self.db.execute(
                select(StudentProgramEnrollment)
                .where(StudentProgramEnrollment.student_id == student_id, StudentProgramEnrollment.deleted_at.is_(None))
                .order_by(StudentProgramEnrollment.admission_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # ---- types ----------------------------------------------------------------------------------------------------------
    async def types(self) -> list[CertReqTypeOut]:
        await self.require_feature("documents.certificate_requests")
        kinds: set[str] = set()
        if await self.my_student():
            kinds.add("student")
        if await self.my_staff():
            kinds.add("staff")
        if await self.alumni_student():
            kinds.add("alumni")
        if await self.ward_ids():
            kinds.add("guardian")
        out = []
        for t, rl in sorted((await self.rules()).items()):
            allowed_for = set(rl.get("allowed_for") or [])
            allowed = bool(kinds & allowed_for) or ("guardian" in kinds and bool(rl.get("allow_parent")))
            out.append(
                CertReqTypeOut(
                    template_type=t,
                    label=TITLES.get(t, t),
                    fee_paise=int(rl.get("fee_paise") or 0),
                    copies_fee_paise=int(rl.get("copies_fee_paise", rl.get("fee_paise") or 0) or 0),
                    sla_days=int(rl.get("sla_days") or 3),
                    approver=str(rl.get("approver") or "registrar"),
                    requires_no_dues=bool(rl.get("requires_no_dues")),
                    allowed=allowed,
                    reason=None if allowed else "Not available for your account",
                )
            )
        return out

    # ---- create ---------------------------------------------------------------------------------------------------------
    async def create(self, body: CertReqCreate) -> CertReqOut:
        await self.require_feature("documents.certificate_requests")
        if not (self.can("certificates", "self") or self.can("certificates", "manage")):
            raise forbidden("certificates:self required")
        rl = await self.rule_for(body.template_type)
        ptype, pid, on_behalf = await self.resolve_person(body, rl)
        if ptype not in (rl.get("allowed_for") or []) and not (on_behalf and rl.get("allow_parent")):
            raise forbidden(f"{body.template_type} cannot be requested by {ptype}")
        enrol = await self.enrolment(pid) if ptype in ("student", "alumni") else None
        need = rl.get("requires_status")
        if need and (enrol is None or enrol.status not in need):
            raise rule(
                f"{TITLES.get(body.template_type, body.template_type)} needs status {', '.join(need)}",
                "NOT_ELIGIBLE",
                422,
                current_status=enrol.status if enrol else None,
            )
        dup = (
            await self.db.execute(
                select(CertificateRequest.id).where(
                    CertificateRequest.institution_id == self.inst,
                    CertificateRequest.person_id == pid,
                    CertificateRequest.template_type == body.template_type,
                    CertificateRequest.status.in_(LIVE),
                )
            )
        ).first()
        if dup is not None:
            raise rule("An active request of this type already exists", "DUPLICATE_REQUEST", request_id=str(dup[0]))
        r = CertificateRequest(
            institution_id=self.inst,
            requester_user_id=self.actor_id,
            person_type=ptype,
            person_id=pid,
            template_type=body.template_type,
            purpose=body.purpose,
            copies=body.copies,
            delivery=body.delivery,
            status="requested",
        )
        self.db.add(r)
        await self.db.flush()
        m: dict[str, Any] = {"address": body.address, "on_behalf": on_behalf, "timeline": []}
        await self.put_meta("req", r.id, m)
        await self.timeline("req", r.id, "requested", copies=body.copies, delivery=body.delivery)
        fee = int(rl.get("fee_paise") or 0) + int(rl.get("copies_fee_paise", rl.get("fee_paise") or 0) or 0) * (
            body.copies - 1
        )
        if fee > 0 and ptype in ("student", "alumni") and await self.feature("fees.core"):
            r.fee_invoice_id = await self.invoice(r, enrol, fee)
            r.status = "fee_pending"
            await self.db.flush()
            await self.timeline("req", r.id, "fee_pending", fee_paise=fee)
            await self._emit("documents.request_fee_pending", {"request_id": str(r.id)}, ENTITY, r.id)
            await self._notify(
                "documents.fee_pending", [self.actor_id], {"type": TITLES.get(r.template_type), "amount": fee / 100}
            )
        else:
            await self.proceed(r, rl)
        await self._emit(
            "documents.request_created",
            {"request_id": str(r.id), "template_type": r.template_type, "person_type": ptype},
            ENTITY,
            r.id,
        )
        await self._notify("documents.request_received", [self.actor_id], {"type": TITLES.get(r.template_type)})
        return (await self.outs([r]))[0]

    async def invoice(self, r: CertificateRequest, enrol: StudentProgramEnrollment | None, fee: int) -> uuid.UUID:
        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        inv = await InvoiceService(self.db, None, self.request, self.inst).create_invoice(
            InvoiceCreate(
                payer_type="student",
                payer_id=r.person_id,
                enrollment_id=enrol.id if enrol else None,
                source_type="certificate_request",
                source_id=r.id,
                description=f"{TITLES.get(r.template_type, r.template_type)} × {r.copies}"[:255],
                items=[
                    InvoiceItemIn(
                        description=f"{TITLES.get(r.template_type, r.template_type)} ({r.copies})"[:200],
                        amount_paise=fee,
                        head_code="CERT",
                    )
                ],
                due_date=(await self.today()) + timedelta(days=15),
            )
        )
        return inv.id

    async def proceed(self, r: CertificateRequest, rl: dict[str, Any] | None = None) -> None:
        """After payment (or for free types): no-dues wait → HOD recommendation → approver."""
        rl = rl or await self.rule_for(r.template_type)
        r.status = "requested"
        m = await self.meta("req", r.id)
        if rl.get("requires_no_dues") and r.person_type in ("student", "alumni"):
            enrol = await self.enrolment(r.person_id)
            if enrol is not None and not await self.no_dues_cleared(enrol.id):
                await self.ensure_no_dues(enrol.id)
                m["stage"] = "awaiting_no_dues"
                await self.put_meta("req", r.id, m)
                await self.timeline("req", r.id, "awaiting_no_dues")
                await self.db.flush()
                return
        if rl.get("recommend_hod") and not m.get("recommended"):
            m["stage"] = "awaiting_recommendation"
            await self.put_meta("req", r.id, m)
            await self.db.flush()
            return
        m["stage"] = "awaiting_approval"
        await self.put_meta("req", r.id, m)
        if str(rl.get("approver") or "registrar") == "registrar" and r.workflow_instance_id is None:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF,
                entity_type=ENTITY,
                entity_id=r.id,
                started_by=r.requester_user_id,
                context={"template_type": r.template_type, "person_type": r.person_type},
                title=f"Certificate · {TITLES.get(r.template_type, r.template_type)}"[:200],
            )
            r.workflow_instance_id = wf.id
        else:
            await self._notify(
                "documents.request_received",
                [],
                {"type": TITLES.get(r.template_type)},
                audience={"roles": [str(rl.get("approver"))]},
            )
        await self.db.flush()

    async def no_dues_cleared(self, enrol_id: uuid.UUID) -> bool:
        return (
            await self.db.execute(
                select(NoDuesRequest.id).where(
                    NoDuesRequest.student_program_enrollment_id == enrol_id,
                    NoDuesRequest.purpose.in_(("transfer", "graduation", "exit")),
                    NoDuesRequest.status == "cleared",
                )
            )
        ).first() is not None

    async def ensure_no_dues(self, enrol_id: uuid.UUID) -> None:
        from app.schemas.no_dues import NoDuesCreate
        from app.services.fees.no_dues_service import NoDuesService

        if not await self.feature("fees.no_dues"):
            return
        await NoDuesService(self.db, None, self.request, self.inst).create(
            NoDuesCreate(purpose="transfer", enrollment_id=enrol_id), system=True
        )

    # ---- payment / no-dues consumers -----------------------------------------------------------------------------------
    async def on_paid(self, rid: uuid.UUID) -> None:
        r = (
            await self.db.execute(select(CertificateRequest).where(CertificateRequest.id == rid).with_for_update())
        ).scalar_one_or_none()
        if r is None or r.status != "fee_pending":
            return
        await self.timeline("req", r.id, "fee_paid")
        await self.proceed(r)

    async def on_no_dues_cleared(self, enrol_id: uuid.UUID) -> int:
        enrol = (
            await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enrol_id))
        ).scalar_one_or_none()
        if enrol is None:
            return 0
        n = 0
        for r in (
            await self.db.execute(
                select(CertificateRequest).where(
                    CertificateRequest.institution_id == self.inst,
                    CertificateRequest.person_id == enrol.student_id,
                    CertificateRequest.status == "requested",
                )
            )
        ).scalars():
            if (await self.meta("req", r.id)).get("stage") == "awaiting_no_dues":
                await self.timeline("req", r.id, "no_dues_cleared")
                await self.proceed(r)
                n += 1
        return n

    # ---- visibility -----------------------------------------------------------------------------------------------------
    async def predicate(self, scope: str | None = None) -> ColumnElement[bool]:
        p = self.principal
        limit = self.type_limit()
        type_ok: ColumnElement[bool] = CertificateRequest.template_type.in_(limit) if limit is not None else true()
        office = any(self.can("certificates", a) for a in ("view_all", "issue", "request_approve", "manage"))
        if scope in (None, "all") and office and (p is None or institution_scope(p)):
            return type_ok
        if getattr(p, "id", None) is None:
            return false()
        parts: list[ColumnElement[bool]] = []
        if scope in (None, "self", "mine"):
            parts.append(CertificateRequest.requester_user_id == p.id)
            mine = await self.my_person_ids()
            if mine:
                parts.append(CertificateRequest.person_id.in_(mine))
        if scope in (None, "wards"):
            wards = await self.ward_ids()
            if wards:
                parts.append(CertificateRequest.person_id.in_(wards))
        if scope in (None, "department") and office and (scope_ids(p, "department") or scope_ids(p, "faculty")):
            studs = select(StudentProgramEnrollment.student_id).where(
                StudentProgramEnrollment.department_id.in_(dept_subquery(p))
            )
            staff = select(Staff.id).where(Staff.department_id.in_(dept_subquery(p)))
            parts.append(
                and_(type_ok, or_(CertificateRequest.person_id.in_(studs), CertificateRequest.person_id.in_(staff)))
            )
        colleges = scope_ids(p, "college")
        if scope in (None, "college") and office and colleges:
            parts.append(
                and_(
                    type_ok,
                    or_(
                        CertificateRequest.person_id.in_(select(Student.id).where(Student.college_id.in_(colleges))),
                        CertificateRequest.person_id.in_(select(Staff.id).where(Staff.college_id.in_(colleges))),
                    ),
                )
            )
        return or_(*parts) if parts else false()

    def request_scopes(self) -> list[str]:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return ["all"]
        office = any(self.can("certificates", a) for a in ("view_all", "issue", "request_approve", "manage"))
        tabs = ["self"]
        if office and (scope_ids(p, "department") or scope_ids(p, "faculty")):
            tabs.append("department")
        if office and scope_ids(p, "college"):
            tabs.append("college")
        if office and institution_scope(p):
            tabs.append("all")
        return tabs

    async def row(self, rid: uuid.UUID, *, for_update: bool = False) -> CertificateRequest:
        stmt = select(CertificateRequest).where(
            CertificateRequest.id == rid, CertificateRequest.institution_id == self.inst, await self.predicate()
        )
        if for_update:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Request")
        return r

    async def list_requests(
        self,
        status: str | None = None,
        template_type: str | None = None,
        person_type: str | None = None,
        department_id: uuid.UUID | None = None,
        scope: str | None = None,
    ) -> list[CertReqOut]:
        await self.require_feature("documents.certificate_requests")
        stmt = select(CertificateRequest).where(
            CertificateRequest.institution_id == self.inst, await self.predicate(scope)
        )
        if status:
            stmt = stmt.where(CertificateRequest.status == status)
        if template_type:
            stmt = stmt.where(CertificateRequest.template_type == template_type)
        if person_type:
            stmt = stmt.where(CertificateRequest.person_type == person_type)
        if department_id:
            stmt = stmt.where(
                CertificateRequest.person_id.in_(
                    select(StudentProgramEnrollment.student_id).where(
                        StudentProgramEnrollment.department_id == department_id
                    )
                )
            )
        rows = (await self.db.execute(stmt.order_by(CertificateRequest.created_at.desc()).limit(500))).scalars().all()
        return await self.outs(list(rows))

    async def mine(self) -> list[CertReqOut]:
        return await self.list_requests(scope="self")

    async def wards(self) -> list[CertReqOut]:
        return await self.list_requests(scope="wards")

    async def get(self, rid: uuid.UUID) -> CertReqOut:
        await self.require_feature("documents.certificate_requests")
        return (await self.outs([await self.row(rid)]))[0]

    async def outs(self, rows: list[CertificateRequest]) -> list[CertReqOut]:
        if not rows:
            return []
        metas = await self.metas("req", [r.id for r in rows])
        names = await self.person_names(
            [("staff" if r.person_type == "staff" else "student", r.person_id) for r in rows]
        )
        users = await self.user_names([r.requester_user_id for r in rows])
        invs = {
            i.id: i
            for i in (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.id.in_([r.fee_invoice_id for r in rows if r.fee_invoice_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        docs = {
            d.id: d.document_number
            for d in (
                await self.db.execute(
                    select(IssuedDocument).where(
                        IssuedDocument.id.in_(
                            [r.issued_document_id for r in rows if r.issued_document_id] or [uuid.uuid4()]
                        )
                    )
                )
            ).scalars()
        }
        wfs = {
            w.id: w
            for w in (
                await self.db.execute(
                    select(WorkflowInstance).where(
                        WorkflowInstance.id.in_(
                            [r.workflow_instance_id for r in rows if r.workflow_instance_id] or [uuid.uuid4()]
                        )
                    )
                )
            ).scalars()
        }
        rules = await self.rules()
        today = await self.today()
        out = []
        for r in rows:
            m = metas.get(str(r.id)) or {}
            inv = invs.get(r.fee_invoice_id) if r.fee_invoice_id else None
            sla = int((rules.get(r.template_type) or {}).get("sla_days") or 3)
            due = r.created_at.date() + timedelta(days=sla)
            wf = wfs.get(r.workflow_instance_id) if r.workflow_instance_id else None
            out.append(
                CertReqOut(
                    id=r.id,
                    requester_user_id=r.requester_user_id,
                    requester_name=users.get(r.requester_user_id),
                    person_type=r.person_type,
                    person_id=r.person_id,
                    person_name=names.get(r.person_id),
                    template_type=r.template_type,
                    purpose=r.purpose,
                    copies=r.copies,
                    delivery=r.delivery,
                    status=r.status,
                    stage=m.get("stage"),
                    fee_invoice_id=r.fee_invoice_id,
                    fee_paise=int(inv.total_paise) if inv else 0,
                    fee_status=inv.status if inv else None,
                    workflow={"status": wf.status, "current_step": wf.current_step, "instance_id": str(wf.id)}
                    if wf
                    else None,
                    issued_document_id=r.issued_document_id,
                    document_number=docs.get(r.issued_document_id) if r.issued_document_id else None,
                    sla_due_on=due.isoformat(),
                    sla_breached=r.status in ("requested", "approved") and today > due,
                    checks=m.get("checks"),
                    pickup=m.get("pickup"),
                    courier_ref=m.get("courier_ref"),
                    address=m.get("address"),
                    timeline=list(m.get("timeline") or []),
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
            )
        return out

    # ---- decisions ------------------------------------------------------------------------------------------------------
    async def checks(self, r: CertificateRequest, rl: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"holds": [], "no_dues": None}
        if r.person_type in ("student", "alumni"):
            enrol = await self.enrolment(r.person_id)
            hold_types = list(rl.get("hold_types") or [])
            if enrol is not None and hold_types:
                holds = (
                    await self.db.execute(
                        select(StudentHold).where(
                            StudentHold.student_program_enrollment_id == enrol.id,
                            StudentHold.released_at.is_(None),
                            StudentHold.hold_type.in_(hold_types),
                        )
                    )
                ).scalars()
                out["holds"] = [{"hold_type": h.hold_type, "reason": h.reason} for h in holds]
            if rl.get("requires_no_dues") and enrol is not None:
                out["no_dues"] = "cleared" if await self.no_dues_cleared(enrol.id) else "pending"
        return out

    async def decide(self, rid: uuid.UUID, body: CertReqDecision, *, via_workflow: bool = False) -> CertReqOut:
        await self.require_feature("documents.certificate_requests")
        r = await self.row(rid, for_update=True) if not via_workflow else await self._raw(rid)
        rl = await self.rule_for(r.template_type)
        m = await self.meta("req", r.id)
        if body.action == "recommend":
            if (
                not (scope_ids(self.principal, "department") and self.can("certificates", "view_all"))
                and not via_workflow
            ):
                raise forbidden("Only the HOD recommends")
            if m.get("stage") != "awaiting_recommendation":
                raise rule("No recommendation is pending", "NOT_PENDING")
            m["recommended"] = {"by": str(self.actor_id), "remarks": body.remarks}
            await self.put_meta("req", r.id, m)
            await self.timeline("req", r.id, "recommended", remarks=body.remarks)
            await self.proceed(r, rl)
            return (await self.outs([r]))[0]
        if not via_workflow:
            if not self.approver_ok(rl):
                raise forbidden(f"{rl.get('approver')} approves {r.template_type} requests")
            self.require_writer()
        if r.status != "requested" or m.get("stage") in ("awaiting_no_dues", "awaiting_recommendation"):
            raise rule(
                "The request is not awaiting approval", "NOT_PENDING", stage=m.get("stage"), current_status=r.status
            )
        if body.action == "reject":
            await self.reject(r, body.remarks or "Rejected")
            if not via_workflow:
                await self.close_workflow(r.workflow_instance_id, "rejected")
            return (await self.outs([r]))[0]
        checks = await self.checks(r, rl)
        m = await self.meta("req", r.id)
        m["checks"] = checks
        if checks["holds"]:
            h = checks["holds"][0]["hold_type"]
            m["stage"] = "blocked"
            await self.put_meta("req", r.id, m)
            await self.timeline("req", r.id, "blocked", hold=h)
            raise rule(f"Blocked by an active {h} hold", f"HOLD_{h.upper()}", holds=checks["holds"])
        if checks.get("no_dues") == "pending":
            raise rule("No-dues clearance is pending", "NO_DUES_PENDING")
        r.status = "approved"
        m["stage"] = None
        await self.put_meta("req", r.id, m)
        await self.timeline("req", r.id, "approved", remarks=body.remarks)
        if not via_workflow:
            await self.close_workflow(r.workflow_instance_id, "approved")
        await self.db.flush()
        await self._emit("documents.request_approved", {"request_id": str(r.id)}, ENTITY, r.id)
        await self._notify("documents.approved", [r.requester_user_id], {"type": TITLES.get(r.template_type)})
        if rl.get("auto_generate"):
            await self.generate(r.id, CertReqGenerate(), _row=r)
        return (await self.outs([r]))[0]

    async def _raw(self, rid: uuid.UUID) -> CertificateRequest:
        r = (
            await self.db.execute(select(CertificateRequest).where(CertificateRequest.id == rid).with_for_update())
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Request")
        return r

    async def reject(self, r: CertificateRequest, reason: str) -> None:
        r.status = "rejected"
        m = await self.meta("req", r.id)
        m["stage"], m["reject_reason"] = "rejected", reason
        await self.put_meta("req", r.id, m)
        await self.timeline("req", r.id, "rejected", reason=reason)
        await self.db.flush()
        if r.fee_invoice_id:
            await self.refund(r, reason)
        await self._emit("documents.request_rejected", {"request_id": str(r.id), "reason": reason}, ENTITY, r.id)
        await self._notify(
            "documents.rejected", [r.requester_user_id], {"type": TITLES.get(r.template_type), "reason": reason}
        )

    async def refund(self, r: CertificateRequest, reason: str) -> None:
        from app.schemas.fees import RefundCreate
        from app.services.fees.refund_service import RefundService

        inv = (await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == r.fee_invoice_id))).scalar_one_or_none()
        if inv is None or int(inv.paid_paise or 0) <= 0:
            return
        try:
            async with self.db.begin_nested():
                await RefundService(self.db, None, self.request, self.inst).submit(
                    RefundCreate(
                        invoice_id=inv.id,
                        amount_paise=int(inv.paid_paise),
                        reason=f"Certificate request rejected: {reason}"[:2000],
                    )
                )
            await self.timeline("req", r.id, "refund_requested", amount_paise=int(inv.paid_paise))
        except APIError as exc:
            await self.timeline("req", r.id, "refund_failed", error=exc.message)

    async def cancel(self, rid: uuid.UUID) -> CertReqOut:
        await self.require_feature("documents.certificate_requests")
        r = await self.row(rid, for_update=True)
        if r.requester_user_id != self.actor_id:
            raise forbidden("Only the requester cancels")
        if r.status not in ("requested", "fee_pending"):
            raise rule("Only requests awaiting approval can be cancelled", "NOT_CANCELLABLE")
        r.status = "rejected"
        m = await self.meta("req", r.id)
        m["stage"] = "cancelled"
        await self.put_meta("req", r.id, m)
        await self.timeline("req", r.id, "cancelled")
        await self.close_workflow(r.workflow_instance_id)
        if r.fee_invoice_id:
            await self.refund(r, "cancelled by requester")
        await self.db.flush()
        return (await self.outs([r]))[0]

    # ---- generate / issue -----------------------------------------------------------------------------------------------
    async def generate(
        self, rid: uuid.UUID, body: CertReqGenerate, *, _row: CertificateRequest | None = None
    ) -> CertReqOut:
        from app.services.documents.render_service import RenderService

        r = _row or await self.row(rid, for_update=True)
        if _row is None:
            if not self.office():
                raise forbidden("certificates:issue required")
            self.require_writer()
            self.require_type(r.template_type)
        if r.status not in ("approved", "generated"):
            raise rule("Approve the request before generating", "NOT_APPROVED")
        res = await RenderService(self.db, self.principal, self.request, self.inst).render(
            r.template_type,
            ENTITY,
            r.id,
            template_id=body.template_id,
            register=r.template_type if r.template_type in REGISTERS else None,
            variables_override={"purpose": r.purpose or ""},
        )
        r.issued_document_id, r.status = res.issued_document_id, "generated"
        await self.db.flush()
        await self.timeline("req", r.id, "generated", document_number=res.document_number)
        await self._emit(
            "documents.request_generated",
            {"request_id": str(r.id), "document_id": str(res.issued_document_id)},
            ENTITY,
            r.id,
        )
        return (await self.outs([r]))[0]

    async def issue(self, rid: uuid.UUID, body: CertReqIssue) -> CertReqOut:
        await self.require_feature("documents.certificate_requests")
        if not self.office():
            raise forbidden("certificates:issue required")
        self.require_writer()
        r = await self.row(rid, for_update=True)
        self.require_type(r.template_type)
        if r.status != "generated":
            raise rule("Generate the document before issuing", "NOT_GENERATED")
        m = await self.meta("req", r.id)
        if r.delivery == "pickup":
            m["stage"] = "pickup_ready"
            m["pickup"] = {
                "on": body.pickup_on or (await self.today() + timedelta(days=1)).isoformat(),
                "note": body.delivery_note,
            }
            await self.put_meta("req", r.id, m)
            await self.timeline("req", r.id, "pickup_ready", on=m["pickup"]["on"])
            await self._notify(
                "documents.pickup_ready",
                [r.requester_user_id],
                {"type": TITLES.get(r.template_type), "on": m["pickup"]["on"]},
            )
            return (await self.outs([r]))[0]
        if r.delivery == "post":
            if not body.courier_ref:
                raise APIError(422, ErrorCode.VALIDATION, "courier_ref is required for postal delivery")
            m["courier_ref"] = body.courier_ref
            await self.put_meta("req", r.id, m)
        await self._issued(r, body.delivery_note)
        return (await self.outs([r]))[0]

    async def _issued(self, r: CertificateRequest, note: str | None) -> None:
        r.status = "issued"
        m = await self.meta("req", r.id)
        m["stage"] = "issued"
        await self.put_meta("req", r.id, m)
        await self.timeline("req", r.id, "issued", delivery=r.delivery, note=note)
        await self.db.flush()
        await self._emit(
            "documents.request_issued",
            {"request_id": str(r.id), "document_id": str(r.issued_document_id), "delivery": r.delivery},
            ENTITY,
            r.id,
        )
        await self._notify(
            "documents.ready",
            [r.requester_user_id],
            {"type": TITLES.get(r.template_type), "delivery": r.delivery, "request_id": str(r.id)},
        )

    async def collected(self, rid: uuid.UUID, body: CertReqCollected) -> CertReqOut:
        if not self.office():
            raise forbidden("certificates:issue required")
        self.require_writer()
        r = await self.row(rid, for_update=True)
        m = await self.meta("req", r.id)
        if r.status != "generated" or m.get("stage") != "pickup_ready":
            raise rule("The document is not ready for pickup", "NOT_READY")
        m["collected"] = {
            "by": body.collected_by,
            "signature_url": body.signature_url,
            "at": now_utc().isoformat(),
            "recorded_by": str(self.actor_id),
        }
        await self.put_meta("req", r.id, m)
        await self._emit("documents.request_collected", {"request_id": str(r.id)}, ENTITY, r.id)
        await self._issued(r, f"collected by {body.collected_by}")
        return (await self.outs([r]))[0]

    # ---- Beat -----------------------------------------------------------------------------------------------------------
    async def sla_scan(self) -> int:
        rules = await self.rules()
        today = await self.today()
        n = 0
        for r in (
            await self.db.execute(
                select(CertificateRequest).where(
                    CertificateRequest.institution_id == self.inst,
                    CertificateRequest.status.in_(("requested", "approved")),
                )
            )
        ).scalars():
            rl = rules.get(r.template_type) or {}
            if r.created_at.date() + timedelta(days=int(rl.get("sla_days") or 3)) >= today:
                continue
            m = await self.meta("req", r.id)
            if m.get("sla_reminded") == today.isoformat():
                continue
            m["sla_reminded"] = today.isoformat()
            await self.put_meta("req", r.id, m)
            await self._notify(
                "documents.request_received",
                [],
                {"type": TITLES.get(r.template_type), "overdue": True},
                audience={"roles": [str(rl.get("approver") or "registrar")]},
            )
            n += 1
        return n

    async def pickup_reminders(self) -> int:
        n = 0
        for r in (
            await self.db.execute(
                select(CertificateRequest).where(
                    CertificateRequest.institution_id == self.inst, CertificateRequest.status == "generated"
                )
            )
        ).scalars():
            m = await self.meta("req", r.id)
            if m.get("stage") == "pickup_ready":
                await self._notify(
                    "documents.pickup_ready",
                    [r.requester_user_id],
                    {"type": TITLES.get(r.template_type), "on": (m.get("pickup") or {}).get("on")},
                )
                n += 1
        return n


@workflow_engine.on(WF, "approved")
async def _wf_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = RequestService(db, actor, institution_id=instance.institution_id)
    r = (
        await db.execute(select(CertificateRequest).where(CertificateRequest.id == instance.entity_id))
    ).scalar_one_or_none()
    if r is not None and r.status == "requested":
        # blocked by a hold / pending no-dues — the request page shows why
        with contextlib.suppress(APIError):
            await svc.decide(r.id, CertReqDecision(action="approve"), via_workflow=True)


@workflow_engine.on(WF, "rejected")
async def _wf_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = RequestService(db, actor, institution_id=instance.institution_id)
    r = (
        await db.execute(select(CertificateRequest).where(CertificateRequest.id == instance.entity_id))
    ).scalar_one_or_none()
    if r is not None and r.status == "requested":
        await svc.reject(r, "Rejected in the approvals inbox")
