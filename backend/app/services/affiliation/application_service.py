"""Affiliation applications — Prompts/34 §34.6 ``application_service`` {affiliation.core, affiliation.inspections,
affiliation.fees}.

Lifecycle (``affiliation_applications.status``):

``draft`` (college prepares; a scrutiny return puts it back here with the missing documents) → ``submit`` (checklist
complete, else 422 ``MISSING_DOCUMENTS``; fees computed from ``affiliation_fee_schedules`` → Phase 12 invoice
``payer_type='college'``, ``source_type='affiliation_application'``) → ``submitted`` → payment (``fees.payment_received``
consumer; no fee / fees off → at once) → ``fee_paid`` (workflow ``affiliation.application`` started; registrar
scrutiny) → ``scrutiny`` proceed → ``scrutiny`` (inspection required) or ``compliance_pending`` (no inspection) →
``inspection_scheduled`` → report → ``inspected`` (open deficiencies) / ``compliance_pending`` → deficiencies responded
/ closed (critical left → ``reinspect`` → ``inspection_scheduled`` round 2) → ``compliance_pending`` → decision
``approved | conditional | rejected`` (``affiliation:decide`` — VC; a council resolution when ``governance.minutes`` is on
and the type requires one, else 422 ``RESOLUTION_REQUIRED``) → affiliation order (``order:{yyyy}``, Phase 26
``affiliation_order``) and programme approvals. ``withdraw`` before a decision (after → 409 ``INVALID_TRANSITION``).

With ``affiliation.inspections`` off the decision-only variant applies: the VC decides from ``fee_paid`` / ``scrutiny``.
Inspection is required for ``new | program_addition | intake_increase | autonomy`` and for ``renewal | extension`` when
the college's last inspection is older than ``affiliation.inspection_required_years``.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.enums.affiliation import (
    CHECKLIST_ITEMS,
    COUNCIL_TYPES,
    DECIDED_STATUSES,
    FEES_BY_TYPE,
    INSPECTION_TYPES,
    OPEN_STATUSES,
)
from app.models.academic import Program
from app.models.affiliation import AffiliationApplication, AffiliationFeeSchedule, AffiliationProgramApproval
from app.models.hr import Staff
from app.models.platform import College, Department
from app.schemas.affiliation import (
    ApplicationAction,
    ApplicationCreate,
    ApplicationOut,
    ApplicationProgram,
    ApplicationUpdate,
    Checklist,
    ChecklistItem,
    DecisionIn,
    DecisionOut,
    Deficiency,
    DeficiencyClose,
    DeficiencyResponse,
    FeeComputePreview,
    FeeLine,
    InspectionOut,
    InspectionReportIn,
    InspectionRow,
    InspectionSchedule,
    ReinspectRequest,
    ScrutinyDecision,
)
from app.services.affiliation.common import AffiliationBase, forbidden, is_auditor, not_found, now_utc, rule
from app.services.documents.render_service import register_resolver

ENTITY = "affiliation_application"
WF_KEY = "affiliation.application"
FEE_LABELS = {
    "affiliation": "Affiliation fee",
    "continuation": "Continuation of affiliation fee",
    "inspection": "Inspection fee",
    "intake_increase": "Intake increase fee",
    "exam_processing_per_student": "Examination processing fee",
    "recognition": "Recognition fee",
}


class ApplicationService(AffiliationBase):
    # ---- rows / visibility --------------------------------------------------------------------------------------------
    async def _row(self, aid: uuid.UUID, *, lock: bool = False) -> AffiliationApplication:
        stmt = select(AffiliationApplication).where(
            AffiliationApplication.id == aid, AffiliationApplication.institution_id == self.inst
        )
        if lock:
            stmt = stmt.with_for_update()
        a = (await self.db.execute(stmt)).scalar_one_or_none()
        if a is None:
            raise not_found("Application")
        return a

    def _committee_staff(self, a: AffiliationApplication) -> list[str]:
        return [str(s) for s in ((a.inspection_committee or {}).get("staff_ids") or [])]

    async def is_inspector(self, a: AffiliationApplication) -> bool:
        p = self.principal
        if p is None or not p.has("affiliation", "inspect"):
            return False
        sid = await self.my_staff_id()
        return sid is not None and str(sid) in self._committee_staff(a)

    async def can_see(self, a: AffiliationApplication) -> bool:
        if self.system() or self.office_reader():
            return True
        if a.college_id in self.my_college_ids():
            return True
        if await self.is_inspector(a):
            return True
        units = await self.unit_program_ids()
        if units:
            ids = {str(x) for x in units}
            if any(str(p.get("program_id")) in ids for p in a.programs or []):
                return True
            if a.college_id in await self.unit_college_ids():
                return True
        return False

    async def visible(self, aid: uuid.UUID, *, lock: bool = False) -> AffiliationApplication:
        a = await self._row(aid, lock=lock)
        if not await self.can_see(a):
            raise not_found("Application")
        return a

    def require_office(self) -> None:
        self.require_writer()
        if not self.office():
            raise forbidden("affiliation:manage (affiliation office) required")

    def require_college(self, a: AffiliationApplication, action: str = "apply") -> None:
        self.require_writer()
        if not (self.office() or self.college_writer(a.college_id, action)):
            raise forbidden("Only the applying college's administrators may do this")

    # ---- output -------------------------------------------------------------------------------------------------------
    async def checklist_for(self, a: AffiliationApplication) -> Checklist:
        lists = await self.aff_setting("document_checklists") or {}
        keys = [str(k) for k in (lists.get(a.application_type) or [])]
        docs = a.documents or {}
        items = [
            ChecklistItem(
                key=k,
                label=CHECKLIST_ITEMS.get(k, k.replace("_", " ").title()),
                file_url=docs.get(k),
                provided=bool(docs.get(k)),
            )
            for k in keys
        ]
        missing = [i.key for i in items if not i.provided]
        meta = await self.meta("app", a.id)
        for k in meta.get("missing_documents") or []:
            if k not in missing and k not in (meta.get("resolved_documents") or []):
                missing.append(str(k))
        return Checklist(application_type=a.application_type, items=items, complete=not missing, missing=missing)

    async def outs(self, rows: list[AffiliationApplication]) -> list[ApplicationOut]:
        if not rows:
            return []
        colleges = await self.colleges_map([a.college_id for a in rows])
        years = await self.years_map([a.academic_year_id for a in rows])
        metas = await self.metas("app", [a.id for a in rows])
        from app.models.fees import FeeInvoice
        from app.models.platform import WorkflowInstance

        inv_ids = [a.fee_invoice_id for a in rows if a.fee_invoice_id]
        invoices = (
            {i.id: i for i in (await self.db.execute(select(FeeInvoice).where(FeeInvoice.id.in_(inv_ids)))).scalars()}
            if inv_ids
            else {}
        )
        wf_ids = [a.workflow_instance_id for a in rows if a.workflow_instance_id]
        wfs = (
            {
                w.id: w
                for w in (
                    await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id.in_(wf_ids)))
                ).scalars()
            }
            if wf_ids
            else {}
        )
        out = []
        for a in rows:
            m = metas.get(str(a.id)) or {}
            c = colleges.get(a.college_id)
            y = years.get(a.academic_year_id)
            inv = invoices.get(a.fee_invoice_id) if a.fee_invoice_id else None
            wf = wfs.get(a.workflow_instance_id) if a.workflow_instance_id else None
            chk = await self.checklist_for(a)
            com = a.inspection_committee or {}
            insp = None
            if com or a.inspection_on or m.get("inspection_required") is not None:
                insp = InspectionOut(
                    committee=com or None,
                    inspection_on=a.inspection_on,
                    mode=com.get("mode"),
                    report_url=a.inspection_report_url,
                    recommendation=m.get("recommendation"),
                    rounds=int(m.get("rounds") or 0),
                    required=bool(m.get("inspection_required", True)),
                )
            dec = m.get("decision")
            out.append(
                ApplicationOut(
                    id=a.id,
                    number=m.get("number"),
                    college_id=a.college_id,
                    college_code=c.code if c else None,
                    college_name=c.name if c else None,
                    academic_year_id=a.academic_year_id,
                    academic_year=y.name if y else None,
                    application_type=a.application_type,
                    status=a.status,
                    programs=[ApplicationProgram(**p) for p in a.programs or []],
                    documents={k: str(v) for k, v in (a.documents or {}).items()},
                    remarks=m.get("remarks"),
                    checklist_complete=chk.complete,
                    missing_documents=chk.missing,
                    fee_invoice_id=a.fee_invoice_id,
                    fee_status=inv.status if inv else m.get("fee_status"),
                    fee_total_paise=inv.total_paise if inv else m.get("fee_total_paise"),
                    workflow_instance_id=a.workflow_instance_id,
                    workflow_state=f"{wf.status}:{wf.current_step}" if wf else None,
                    inspection=insp,
                    deficiencies=[Deficiency(**d) for d in a.deficiencies or []],
                    decision=DecisionOut(**dec) if dec else None,
                    order_no=a.order_no,
                    order_url=a.order_url,
                    timeline=list(m.get("timeline") or []),
                    created_at=a.created_at,
                    updated_at=a.updated_at,
                )
            )
        return out

    async def get(self, aid: uuid.UUID) -> ApplicationOut:
        return (await self.outs([await self.visible(aid)]))[0]

    async def list_applications(
        self,
        college_id: uuid.UUID | None,
        year_id: uuid.UUID | None,
        application_type: str | None,
        status: str | None,
        scope: str | None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[ApplicationOut], int]:
        stmt = select(AffiliationApplication).where(AffiliationApplication.institution_id == self.inst)
        if scope == "college" or not (self.system() or self.office_reader()):
            mine = self.my_college_ids()
            units = await self.unit_college_ids() if scope != "college" else []
            sid = await self.my_staff_id()
            conds: list[Any] = []
            if mine or units:
                conds.append(AffiliationApplication.college_id.in_(list({*mine, *units})))
            if (
                sid is not None
                and scope != "college"
                and self.principal is not None
                and self.principal.has("affiliation", "inspect")
            ):
                conds.append(AffiliationApplication.inspection_committee["staff_ids"].contains([str(sid)]))
            if not conds:
                return [], 0
            stmt = stmt.where(or_(*conds))
        if college_id:
            stmt = stmt.where(AffiliationApplication.college_id == college_id)
        if year_id:
            stmt = stmt.where(AffiliationApplication.academic_year_id == year_id)
        if application_type:
            stmt = stmt.where(AffiliationApplication.application_type == application_type)
        if status:
            stmt = stmt.where(AffiliationApplication.status == status)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(AffiliationApplication.created_at.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            ).scalars()
        )
        return await self.outs(rows), int(total)

    # ---- create / edit ------------------------------------------------------------------------------------------------
    async def _normalise_programs(
        self, c: College, app_type: str, year_id: uuid.UUID, programs: list[ApplicationProgram]
    ) -> list[dict[str, Any]]:
        if app_type in ("intake_increase", "program_addition", "program_closure") and not programs:
            raise APIError(
                422, ErrorCode.VALIDATION, f"A {app_type} application names its programmes", {"field": "programs"}
            )
        pmap = await self.programs_map([p.program_id for p in programs if p.program_id])
        out = []
        for i, p in enumerate(programs):
            row = p.model_dump(mode="json")
            if p.program_id:
                prog = pmap.get(p.program_id)
                if prog is None or prog.college_id != c.id:
                    raise APIError(
                        422,
                        ErrorCode.VALIDATION,
                        f"Programme {i + 1} does not belong to {c.code}",
                        {"field": f"programs.{i}"},
                    )
                row["program_code"], row["program_name"] = prog.code, prog.name
                prev = (
                    await self.db.execute(
                        select(AffiliationProgramApproval)
                        .where(
                            AffiliationProgramApproval.college_id == c.id,
                            AffiliationProgramApproval.program_id == prog.id,
                            AffiliationProgramApproval.approval_status != "withdrawn",
                        )
                        .order_by(AffiliationProgramApproval.valid_to.desc().nullslast())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                row["current_intake"] = int(prev.sanctioned_intake) if prev else prog.sanctioned_intake
                if (
                    app_type == "intake_increase"
                    and p.requested_intake is not None
                    and row["current_intake"]
                    and p.requested_intake <= int(row["current_intake"])
                ):
                    raise APIError(
                        422,
                        ErrorCode.VALIDATION,
                        f"{prog.code}: requested intake must exceed the current {row['current_intake']}",
                        {"field": f"programs.{i}.requested_intake"},
                    )
            elif p.new is not None:
                if app_type not in ("new", "program_addition"):
                    raise APIError(
                        422, ErrorCode.VALIDATION, "New programmes belong to new / program_addition applications"
                    )
                row["program_code"], row["program_name"] = p.new.code, p.new.name
                row["requested_intake"] = p.requested_intake or p.new.intake
            else:
                raise APIError(422, ErrorCode.VALIDATION, f"Programme {i + 1}: program_id or new is required")
            out.append(row)
        return out

    async def create(self, body: ApplicationCreate) -> ApplicationOut:
        self.require_writer()
        c = await self.college(body.college_id)
        if not (self.office() or self.college_writer(c.id, "apply")):
            raise forbidden("affiliation:apply for the college required")
        await self.year(body.academic_year_id)
        if body.application_type == "autonomy" and c.college_type == "autonomous":
            raise rule("The college is already autonomous", "ALREADY_AUTONOMOUS")
        dup = (
            await self.db.execute(
                select(AffiliationApplication.id).where(
                    AffiliationApplication.institution_id == self.inst,
                    AffiliationApplication.college_id == c.id,
                    AffiliationApplication.academic_year_id == body.academic_year_id,
                    AffiliationApplication.application_type == body.application_type,
                    AffiliationApplication.status.in_(list(OPEN_STATUSES)),
                )
            )
        ).first()
        if dup and body.application_type not in ("intake_increase", "program_addition", "program_closure"):
            raise rule("An open application of this type exists for the year", "DUPLICATE_APPLICATION")
        programs = await self._normalise_programs(c, body.application_type, body.academic_year_id, body.programs)
        a = AffiliationApplication(
            institution_id=self.inst,
            college_id=c.id,
            academic_year_id=body.academic_year_id,
            application_type=str(body.application_type),
            programs=programs,
            documents=dict(body.documents),
            status="draft",
        )
        self.db.add(a)
        await self.db.flush()
        number = await self.sequence("affil", "AFF")
        meta = {"number": number, "remarks": body.remarks}
        if body.reference_application_id:
            meta["reference_application_id"] = str(body.reference_application_id)
        await self.put_meta("app", a.id, meta)
        await self.timeline("app", a.id, "created", application_type=a.application_type)
        await self._audit("create", ENTITY, a.id, None, {"number": number, "type": a.application_type})
        await self._emit(
            "affiliation.application_created",
            {"application_id": str(a.id), "college_id": str(c.id), "type": a.application_type},
            ENTITY,
            a.id,
        )
        return (await self.outs([a]))[0]

    async def update(self, aid: uuid.UUID, body: ApplicationUpdate) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_college(a)
        if a.status != "draft":
            raise rule(f"A {a.status} application cannot be edited", "INVALID_TRANSITION")
        c = await self.college(a.college_id)
        if body.programs is not None:
            a.programs = await self._normalise_programs(c, a.application_type, a.academic_year_id, body.programs)
        meta = await self.meta("app", a.id)
        if body.documents is not None:
            docs = dict(a.documents or {})
            for k, v in body.documents.items():
                if v:
                    docs[k] = v
                    if k in (meta.get("missing_documents") or []):
                        meta.setdefault("resolved_documents", []).append(k)
                else:
                    docs.pop(k, None)
            a.documents = docs
        if body.remarks is not None:
            meta["remarks"] = body.remarks
        await self.put_meta("app", a.id, meta)
        await self.db.flush()
        await self.timeline("app", a.id, "updated")
        return (await self.outs([a]))[0]

    async def checklist(self, aid: uuid.UUID) -> Checklist:
        return await self.checklist_for(await self.visible(aid))

    # ---- fees ---------------------------------------------------------------------------------------------------------
    async def last_inspection(self, college_id: uuid.UUID) -> date | None:
        v = (await self.meta("college", college_id)).get("last_inspection_on")
        return date.fromisoformat(v) if v else None

    async def inspection_required(self, a: AffiliationApplication) -> bool:
        if a.application_type in INSPECTION_TYPES:
            return True
        if a.application_type in ("renewal", "extension"):
            last = await self.last_inspection(a.college_id)
            years = await self.aff_int("inspection_required_years")
            today = await self.today()
            return last is None or (today - last).days > 365 * years
        return False

    async def fee_lines(self, a: AffiliationApplication) -> tuple[list[FeeLine], bool]:
        needs_inspection = await self.inspection_required(a)
        schedules = {
            s.fee_type: s
            for s in (
                await self.db.execute(
                    select(AffiliationFeeSchedule).where(
                        AffiliationFeeSchedule.institution_id == self.inst,
                        AffiliationFeeSchedule.academic_year_id == a.academic_year_id,
                    )
                )
            ).scalars()
        }
        types = list(FEES_BY_TYPE.get(a.application_type, ()))
        if needs_inspection and await self.soft_feature("affiliation.inspections"):
            types.append("inspection")
        progs = a.programs or []
        lines: list[FeeLine] = []
        for t in types:
            s = schedules.get(t)
            if s is None:
                continue
            if s.per_unit == "per_program":
                units = max(1, len(progs))
            elif s.per_unit == "per_student":
                if a.application_type == "intake_increase":
                    units = sum(
                        max(0, int(p.get("requested_intake") or 0) - int(p.get("current_intake") or 0)) for p in progs
                    )
                else:
                    units = sum(int(p.get("requested_intake") or 0) for p in progs)
            else:
                units = 1
            lines.append(
                FeeLine(
                    fee_type=t,
                    per_unit=s.per_unit,
                    units=units,
                    rate_paise=int(s.amount_paise),
                    amount_paise=int(s.amount_paise) * units,
                    label=FEE_LABELS.get(t, t),
                )
            )
        return [ln for ln in lines if ln.amount_paise > 0], needs_inspection

    async def fee_preview(self, aid: uuid.UUID) -> FeeComputePreview:
        a = await self.visible(aid)
        lines, needs = await self.fee_lines(a)
        return FeeComputePreview(
            application_id=a.id,
            lines=lines,
            total_paise=sum(ln.amount_paise for ln in lines),
            inspection_required=needs,
        )

    async def _invoice(
        self, a: AffiliationApplication, lines: list[FeeLine], label: str, *, multiple: bool = False
    ) -> uuid.UUID | None:
        if not lines:
            return None
        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        meta = await self.meta("app", a.id)
        days = await self.aff_int("deficiency_compliance_days")
        try:
            async with self.db.begin_nested():
                inv = await InvoiceService(self.db, None, None, self.inst).create_invoice(
                    InvoiceCreate(
                        payer_type="college",
                        payer_id=a.college_id,
                        source_type="affiliation_application",
                        source_id=a.id,
                        description=f"{label} · {meta.get('number') or a.id}"[:200],
                        items=[
                            InvoiceItemIn(
                                description=f"{ln.label} ({ln.units} × Rs. {ln.rate_paise // 100})"[:200],
                                amount_paise=ln.amount_paise,
                                head_code="AFFIL",
                            )
                            for ln in lines
                        ],
                        due_date=(await self.today()) + timedelta(days=days),
                        allow_multiple=multiple,
                    ),
                    notify=False,
                )
                inv.college_id = a.college_id
                await self.db.flush()
        except Exception:  # noqa: BLE001 - fees module refused (no head / feature off): recorded as pending
            return None
        return inv.id

    # ---- submit / withdraw --------------------------------------------------------------------------------------------
    async def action(self, aid: uuid.UUID, body: ApplicationAction) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_college(a)
        if body.action == "withdraw":
            if a.status not in OPEN_STATUSES:
                raise rule(f"A {a.status} application cannot be withdrawn", "INVALID_TRANSITION")
            old = a.status
            a.status = "withdrawn"
            await self.close_workflow(a.workflow_instance_id)
            await self.db.flush()
            await self.timeline("app", a.id, "withdrawn", remarks=body.remarks)
            await self._audit("withdraw", ENTITY, a.id, {"status": old}, {"status": a.status})
            await self._emit("affiliation.withdrawn", {"application_id": str(a.id)}, ENTITY, a.id)
            return (await self.outs([a]))[0]
        if a.status != "draft":
            raise rule(f"A {a.status} application cannot be submitted", "INVALID_TRANSITION")
        chk = await self.checklist_for(a)
        if not chk.complete:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The document checklist is incomplete",
                {"code": "MISSING_DOCUMENTS", "missing": chk.missing},
            )
        meta = await self.meta("app", a.id)
        meta.pop("missing_documents", None)
        meta.pop("resolved_documents", None)
        resubmission = bool(meta.get("returned"))
        meta["returned"] = False
        if body.remarks:
            meta["remarks"] = body.remarks
        await self.put_meta("app", a.id, meta)
        if resubmission:
            a.status = "fee_paid" if meta.get("fee_settled") else "submitted"
            await self.db.flush()
            await self.timeline("app", a.id, "resubmitted")
            await self._advance_after_payment(a, resubmitted=True)
        else:
            lines, needs = await self.fee_lines(a)
            total = sum(ln.amount_paise for ln in lines)
            meta = await self.meta("app", a.id)
            meta.update(
                {
                    "inspection_required": needs,
                    "fee_lines": [ln.model_dump() for ln in lines],
                    "fee_total_paise": total,
                }
            )
            await self.put_meta("app", a.id, meta)
            a.status = "submitted"
            inv = None
            if total and await self.soft_feature("affiliation.fees"):
                inv = await self._invoice(a, lines, "Affiliation application fee")
                a.fee_invoice_id = inv
            await self.db.flush()
            await self.timeline("app", a.id, "submitted", fee_total_paise=total, invoice_id=str(inv) if inv else None)
            await self._emit(
                "affiliation.application_submitted",
                {"application_id": str(a.id), "college_id": str(a.college_id), "fee_total_paise": total},
                ENTITY,
                a.id,
            )
            c = await self.college(a.college_id)
            if inv is not None:
                await self.notify_college(
                    c, "affiliation.fee_due", {"number": meta.get("number"), "amount": f"{total / 100:.2f}"}
                )
            else:
                await self._mark_paid(a)
            await self._notify(
                "affiliation.application_submitted",
                await self.office_users(),
                {"college": c.name, "number": meta.get("number"), "type": a.application_type},
            )
        return (await self.outs([a]))[0]

    async def _mark_paid(self, a: AffiliationApplication) -> None:
        meta = await self.meta("app", a.id)
        meta["fee_settled"] = True
        await self.put_meta("app", a.id, meta)
        a.status = "fee_paid"
        await self.db.flush()
        await self.timeline("app", a.id, "fee_paid")
        await self._emit("affiliation.fee_paid", {"application_id": str(a.id)}, ENTITY, a.id)
        await self._advance_after_payment(a)

    async def _advance_after_payment(self, a: AffiliationApplication, *, resubmitted: bool = False) -> None:
        if a.workflow_instance_id is None:
            meta = await self.meta("app", a.id)
            council = a.application_type in COUNCIL_TYPES and await self.soft_feature("governance.minutes")
            ctx = {
                "number": meta.get("number"),
                "college_id": str(a.college_id),
                "application_type": a.application_type,
                "inspection_required": bool(meta.get("inspection_required"))
                and await self.soft_feature("affiliation.inspections"),
                "council_required": a.application_type == "autonomy" and council,
            }
            if ctx["council_required"]:
                ctx["ac_user"] = await self._council_user("academic_council")
                ctx["ec_user"] = await self._council_user("executive_council")
            a.workflow_instance_id = await self.start_workflow(
                WF_KEY, ENTITY, a.id, f"Affiliation {a.application_type} · {meta.get('number')}", ctx
            )
            await self.db.flush()
        if a.status == "fee_paid":
            await self._notify(
                "affiliation.scrutiny",
                await self.office_users(),
                {"number": (await self.meta("app", a.id)).get("number"), "resubmitted": resubmitted},
            )

    async def _council_user(self, committee_type: str) -> str | None:
        c = await self.committee_by_type(committee_type)
        if c is not None and c.secretary_staff_id:
            u = await self.staff_user(c.secretary_staff_id)
            if u:
                return str(u)
        users = await self.role_users("registrar")
        return str(users[0]) if users else None

    async def on_payment(self, application_id: uuid.UUID, invoice_status: str | None) -> None:
        a = (
            await self.db.execute(
                select(AffiliationApplication).where(AffiliationApplication.id == application_id).with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            return
        if invoice_status not in (None, "paid"):
            await self.timeline("app", a.id, "fee_part_paid", invoice_status=invoice_status)
            return
        if a.status == "submitted":
            await self._mark_paid(a)
        else:
            await self.timeline("app", a.id, "fee_received")

    # ---- workflow helpers ---------------------------------------------------------------------------------------------
    async def _wf_context(self, a: AffiliationApplication, **updates: Any) -> None:
        if a.workflow_instance_id is None:
            return
        from app.models.platform import WorkflowInstance

        wf = (
            await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id == a.workflow_instance_id))
        ).scalar_one_or_none()
        if wf is not None:
            wf.context = {**(wf.context or {}), **dict(updates.items())}
            await self.db.flush()

    async def _wf_act(self, a: AffiliationApplication, approve: bool, comment: str | None) -> None:
        if a.workflow_instance_id is None:
            return
        try:
            async with self.db.begin_nested():
                await self.acted_on_workflow(str(a.workflow_instance_id), approve, comment)
        except APIError:
            pass  # the caller is not the step's approver (office acting directly): the record decides

    # ---- scrutiny -----------------------------------------------------------------------------------------------------
    async def scrutiny(self, aid: uuid.UUID, body: ScrutinyDecision) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_office()
        if a.status not in ("fee_paid", "submitted"):
            raise rule(f"A {a.status} application is not awaiting scrutiny", "INVALID_TRANSITION")
        meta = await self.meta("app", a.id)
        trail = list(meta.get("scrutiny") or [])
        trail.append(
            {
                "action": body.action,
                "remarks": body.remarks,
                "missing_documents": body.missing_documents,
                "by": str(self.actor_id) if self.actor_id else None,
                "at": now_utc().isoformat(),
            }
        )
        meta["scrutiny"] = trail
        c = await self.college(a.college_id)
        if body.action == "return":
            meta["returned"] = True
            meta["missing_documents"] = list(body.missing_documents)
            meta["resolved_documents"] = []
            docs = dict(a.documents or {})
            for k in body.missing_documents:
                docs.pop(k, None)
            a.documents = docs
            a.status = "draft"
            await self.put_meta("app", a.id, meta)
            await self.db.flush()
            await self.timeline("app", a.id, "scrutiny_returned", missing=body.missing_documents)
            await self._emit("affiliation.scrutiny_returned", {"application_id": str(a.id)}, ENTITY, a.id)
            await self.notify_college(
                c,
                "affiliation.deficiency",
                {"number": meta.get("number"), "items": ", ".join(body.missing_documents) or (body.remarks or "")},
            )
            return (await self.outs([a]))[0]
        if a.status == "submitted":
            raise rule("The application fee is not paid yet", "FEE_PENDING")
        needs = bool(meta.get("inspection_required")) and await self.soft_feature("affiliation.inspections")
        a.status = "scrutiny" if needs else "compliance_pending"
        await self.put_meta("app", a.id, meta)
        await self.db.flush()
        await self._wf_act(a, True, body.remarks or "Scrutiny cleared")
        await self.timeline("app", a.id, "scrutiny_cleared", inspection_required=needs)
        return (await self.outs([a]))[0]

    # ---- inspection ---------------------------------------------------------------------------------------------------
    async def _committee_staff_ids(self, body: InspectionSchedule) -> list[uuid.UUID]:
        ids = list(dict.fromkeys(body.committee.staff_ids))
        if body.committee.committee_id is not None:
            from app.models.governance import Committee, CommitteeMember

            cm = (
                await self.db.execute(
                    select(Committee).where(
                        Committee.id == body.committee.committee_id, Committee.institution_id == self.inst
                    )
                )
            ).scalar_one_or_none()
            if cm is None:
                raise not_found("Committee")
            today = await self.today()
            for sid in (
                await self.db.execute(
                    select(CommitteeMember.staff_id).where(
                        CommitteeMember.committee_id == cm.id,
                        CommitteeMember.staff_id.is_not(None),
                        or_(CommitteeMember.to_on.is_(None), CommitteeMember.to_on >= today),
                    )
                )
            ).scalars():
                if sid is not None and sid not in ids:
                    ids.append(sid)
        if not ids:
            raise APIError(422, ErrorCode.VALIDATION, "The inspection committee needs at least one staff member")
        found = set(
            (
                await self.db.execute(select(Staff.id).where(Staff.id.in_(ids), Staff.institution_id == self.inst))
            ).scalars()
        )
        missing = [str(i) for i in ids if i not in found]
        if missing:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown staff on the committee", {"staff_ids": missing})
        return ids

    async def schedule_inspection(self, aid: uuid.UUID, body: InspectionSchedule) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_office()
        if a.status not in ("scrutiny", "inspected"):
            raise rule(f"A {a.status} application cannot be scheduled for inspection", "INVALID_TRANSITION")
        if body.inspection_on < await self.today():
            raise APIError(422, ErrorCode.VALIDATION, "The inspection date is in the past", {"field": "inspection_on"})
        ids = await self._committee_staff_ids(body)
        convenor = body.committee.convenor_staff_id or ids[0]
        meta = await self.meta("app", a.id)
        rnd = int(meta.get("rounds") or 0) + 1
        a.inspection_committee = {
            "staff_ids": [str(i) for i in ids],
            "external": [e.model_dump() for e in body.committee.external],
            "committee_id": str(body.committee.committee_id) if body.committee.committee_id else None,
            "convenor_staff_id": str(convenor),
            "mode": body.mode,
            "round": rnd,
        }
        a.inspection_on = body.inspection_on
        a.status = "inspection_scheduled"
        meta["rounds"] = rnd
        await self.put_meta("app", a.id, meta)
        await self.db.flush()
        convenor_user = await self.staff_user(convenor)
        await self._wf_context(a, inspector=str(convenor_user) if convenor_user else None)
        await self.timeline("app", a.id, "inspection_scheduled", on=body.inspection_on.isoformat(), round=rnd)
        await self._emit(
            "affiliation.inspection_scheduled",
            {
                "application_id": str(a.id),
                "college_id": str(a.college_id),
                "inspection_on": body.inspection_on.isoformat(),
                "staff_ids": [str(i) for i in ids],
                "round": rnd,
            },
            ENTITY,
            a.id,
        )
        c = await self.college(a.college_id)
        ctx = {"number": meta.get("number"), "on": body.inspection_on.isoformat(), "mode": body.mode}
        await self.notify_college(c, "affiliation.inspection_scheduled", ctx)
        await self._notify(
            "affiliation.inspection_scheduled", [await self.staff_user(s) for s in ids], {"college": c.name, **ctx}
        )
        return (await self.outs([a]))[0]

    async def inspection_report(self, aid: uuid.UUID, body: InspectionReportIn) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_writer()
        if not (self.office() or await self.is_inspector(a)):
            raise forbidden("Only the assigned inspection committee may upload the report")
        if a.status != "inspection_scheduled":
            raise rule(f"A {a.status} application has no pending inspection", "INVALID_TRANSITION")
        meta = await self.meta("app", a.id)
        rnd = int(meta.get("rounds") or 1)
        days = await self.aff_int("deficiency_compliance_days")
        today = await self.today()
        defs = list(a.deficiencies or [])
        new_defs = []
        for i, f in enumerate([f for f in body.findings if f.is_deficiency], start=1):
            new_defs.append(
                {
                    "id": f"D{rnd}-{i}",
                    "area": f.area,
                    "observation": f.observation,
                    "severity": f.severity,
                    "status": "open",
                    "due_on": (today + timedelta(days=days)).isoformat(),
                    "round": rnd,
                }
            )
        defs.extend(new_defs)
        a.deficiencies = defs
        a.inspection_report_url = body.report_url
        reports = list(meta.get("reports") or [])
        reports.append(
            {
                "round": rnd,
                "report_url": body.report_url,
                "findings": [f.model_dump() for f in body.findings],
                "recommendation": body.recommendation,
                "by": str(self.actor_id) if self.actor_id else None,
                "at": now_utc().isoformat(),
            }
        )
        meta["reports"] = reports
        meta["recommendation"] = body.recommendation
        open_defs = [d for d in defs if d.get("status") != "closed"]
        a.status = "inspected" if open_defs else "compliance_pending"
        await self.put_meta("app", a.id, meta)
        cmeta = await self.meta("college", a.college_id)
        cmeta["last_inspection_on"] = (a.inspection_on or today).isoformat()
        await self.put_meta("college", a.college_id, cmeta)
        await self.db.flush()
        await self._wf_act(a, True, f"Inspection report round {rnd}: {body.recommendation}")
        await self.timeline("app", a.id, "inspected", round=rnd, deficiencies=len(new_defs))
        await self._emit(
            "affiliation.inspected",
            {"application_id": str(a.id), "round": rnd, "deficiencies": len(new_defs)},
            ENTITY,
            a.id,
        )
        await self.render_doc("inspection_report", ENTITY, a.id, {"round": rnd}, allow_multiple=True)
        if new_defs:
            doc = await self.render_doc("deficiency_notice", ENTITY, a.id, {"round": rnd}, allow_multiple=True)
            meta = await self.meta("app", a.id)
            meta.setdefault("notices", []).append(
                {"round": rnd, "issued_document_id": str(doc.issued_document_id) if doc else None}
            )
            await self.put_meta("app", a.id, meta)
            await self._emit(
                "affiliation.deficiency_issued",
                {
                    "application_id": str(a.id),
                    "count": len(new_defs),
                    "critical": sum(d["severity"] == "critical" for d in new_defs),
                },
                ENTITY,
                a.id,
            )
            c = await self.college(a.college_id)
            await self.notify_college(
                c,
                "affiliation.deficiency",
                {"number": meta.get("number"), "items": "; ".join(str(d["area"]) for d in new_defs)[:400]},
            )
        return (await self.outs([a]))[0]

    def _deficiency(self, a: AffiliationApplication, did: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        defs = [dict(d) for d in a.deficiencies or []]
        for d in defs:
            if d.get("id") == did:
                return defs, d
        raise not_found("Deficiency")

    async def respond_deficiency(self, aid: uuid.UUID, did: str, body: DeficiencyResponse) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_college(a)
        if a.status != "inspected":
            raise rule(f"A {a.status} application has no open deficiencies", "INVALID_TRANSITION")
        defs, d = self._deficiency(a, did)
        if d.get("status") == "closed":
            raise rule("The deficiency is already closed", "ALREADY_CLOSED")
        d.update(
            {
                "status": "responded",
                "response_text": body.response_text,
                "evidence_url": body.evidence_url,
                "responded_at": now_utc().isoformat(),
            }
        )
        a.deficiencies = defs
        await self.db.flush()
        await self.timeline("app", a.id, "deficiency_responded", deficiency=did)
        await self._notify(
            "affiliation.deficiency",
            await self.office_users(),
            {"number": (await self.meta("app", a.id)).get("number"), "items": f"response to {did}"},
        )
        return (await self.outs([a]))[0]

    async def close_deficiency(self, aid: uuid.UUID, did: str, body: DeficiencyClose) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_office()
        if a.status != "inspected":
            raise rule(f"A {a.status} application has no open deficiencies", "INVALID_TRANSITION")
        defs, d = self._deficiency(a, did)
        if body.accept:
            d.update(
                {
                    "status": "closed",
                    "closed_by": str(self.actor_id) if self.actor_id else None,
                    "closed_at": now_utc().isoformat(),
                }
            )
        else:
            d.update(
                {
                    "status": "open",
                    "response_text": (d.get("response_text") or "") + f" [returned: {body.remarks or ''}]",
                }
            )
        a.deficiencies = defs
        if all(x.get("status") == "closed" for x in defs):
            a.status = "compliance_pending"
        await self.db.flush()
        await self.timeline("app", a.id, "deficiency_closed" if body.accept else "deficiency_reopened", deficiency=did)
        if body.accept:
            await self._emit(
                "affiliation.deficiency_closed", {"application_id": str(a.id), "deficiency_id": did}, ENTITY, a.id
            )
        return (await self.outs([a]))[0]

    async def reinspect(self, aid: uuid.UUID, body: ReinspectRequest) -> ApplicationOut:
        a = await self.visible(aid, lock=True)
        self.require_office()
        if a.status not in ("inspected", "compliance_pending"):
            raise rule(f"A {a.status} application cannot be re-inspected", "INVALID_TRANSITION")
        meta = await self.meta("app", a.id)
        rnd = int(meta.get("rounds") or 1) + 1
        meta["rounds"] = rnd
        com = dict(a.inspection_committee or {})
        com["round"] = rnd
        a.inspection_committee = com
        if body.inspection_on:
            a.inspection_on = body.inspection_on
        a.status = "inspection_scheduled"
        await self.put_meta("app", a.id, meta)
        await self.db.flush()
        if await self.soft_feature("affiliation.fees"):
            lines = [ln for ln in (await self.fee_lines(a))[0] if ln.fee_type == "inspection"]
            inv = await self._invoice(a, lines, f"Re-inspection fee (round {rnd})", multiple=True)
            if inv:
                meta = await self.meta("app", a.id)
                meta.setdefault("extra_invoices", []).append(str(inv))
                await self.put_meta("app", a.id, meta)
        await self.timeline("app", a.id, "reinspection", round=rnd, remarks=body.remarks)
        c = await self.college(a.college_id)
        ctx = {
            "number": meta.get("number"),
            "on": (a.inspection_on or await self.today()).isoformat(),
            "mode": com.get("mode") or "physical",
        }
        await self.notify_college(c, "affiliation.inspection_scheduled", ctx)
        await self._emit("affiliation.inspection_scheduled", {"application_id": str(a.id), "round": rnd}, ENTITY, a.id)
        return (await self.outs([a]))[0]

    async def inspections(
        self, date_from: date | None, date_to: date | None, *, mine: bool = False
    ) -> list[InspectionRow]:
        stmt = select(AffiliationApplication).where(
            AffiliationApplication.institution_id == self.inst, AffiliationApplication.inspection_on.is_not(None)
        )
        if mine or not (self.system() or self.office_reader()):
            sid = await self.my_staff_id()
            if sid is None:
                return []
            stmt = stmt.where(AffiliationApplication.inspection_committee["staff_ids"].contains([str(sid)]))
        if date_from:
            stmt = stmt.where(AffiliationApplication.inspection_on >= date_from)
        if date_to:
            stmt = stmt.where(AffiliationApplication.inspection_on <= date_to)
        rows = list((await self.db.execute(stmt.order_by(AffiliationApplication.inspection_on))).scalars())
        colleges = await self.colleges_map([a.college_id for a in rows])
        metas = await self.metas("app", [a.id for a in rows])
        out = []
        for a in rows:
            m = metas.get(str(a.id)) or {}
            reports = m.get("reports") or []
            rnd = int(m.get("rounds") or 0)
            out.append(
                InspectionRow(
                    application_id=a.id,
                    number=m.get("number"),
                    college_id=a.college_id,
                    college_name=colleges[a.college_id].name if a.college_id in colleges else None,
                    application_type=a.application_type,
                    status=a.status,
                    inspection_on=a.inspection_on,
                    mode=(a.inspection_committee or {}).get("mode"),
                    committee=a.inspection_committee,
                    report_submitted=any(int(r.get("round") or 0) == rnd for r in reports),
                    open_deficiencies=sum(1 for d in a.deficiencies or [] if d.get("status") != "closed"),
                )
            )
        return out

    # ---- decision -----------------------------------------------------------------------------------------------------
    async def _resolution(
        self, a: AffiliationApplication, rid: uuid.UUID | None
    ) -> tuple[uuid.UUID | None, str | None]:
        council_needed = a.application_type in COUNCIL_TYPES and await self.soft_feature("governance.minutes")
        if rid is None:
            if council_needed:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "An Academic / Executive Council resolution is required",
                    {"code": "RESOLUTION_REQUIRED"},
                )
            return None, None
        from app.models.governance import Resolution
        from app.schemas.governance import ResolutionLink
        from app.services.governance.resolution_service import ResolutionService

        r = (
            await self.db.execute(
                select(Resolution).where(Resolution.id == rid, Resolution.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise APIError(422, ErrorCode.VALIDATION, "Resolution not found", {"code": "RESOLUTION_NOT_FOUND"})
        if r.status not in ("passed", "implemented"):
            raise rule("Only passed resolutions can be cited", "NOT_PASSED", 422)
        meta = await self.meta("app", a.id)
        await ResolutionService(self.db, self.principal, self.request, self.inst).apply_link(
            r,
            ResolutionLink(
                entity_type=ENTITY, entity_id=a.id, label=f"Affiliation {a.application_type} {meta.get('number') or ''}"
            ),
        )
        return r.id, r.number

    async def _new_program(self, c: College, p: dict[str, Any]) -> Program:
        new = p.get("new") or {}
        dept_id = new.get("department_id")
        if not dept_id:
            dept_id = (
                await self.db.execute(
                    select(Department.id).where(Department.college_id == c.id, Department.deleted_at.is_(None)).limit(1)
                )
            ).scalar_one_or_none()
        if dept_id is None:
            raise rule(f"{c.code} has no department to host {new.get('code')}", "NO_DEPARTMENT", 422)
        existing = (
            await self.db.execute(
                select(Program).where(
                    Program.institution_id == self.inst, Program.college_id == c.id, Program.code == new.get("code")
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        prog = Program(
            institution_id=self.inst,
            college_id=c.id,
            department_id=uuid.UUID(str(dept_id)),
            code=str(new.get("code"))[:30],
            name=str(new.get("name"))[:200],
            degree_name=str(new.get("degree_name") or new.get("code"))[:80],
            level=str(new.get("level") or "ug")[:20],
            duration_years=new.get("duration_years") or 4,
            total_terms=int(new.get("total_terms") or 8),
            sanctioned_intake=p.get("requested_intake") or new.get("intake"),
            lateral_intake=p.get("lateral_intake") or 0,
            approving_body="university",
            exam_authority="autonomous_college" if c.college_type == "autonomous" else "university",
            status="active",
        )
        self.db.add(prog)
        await self.db.flush()
        await self._emit(
            "affiliation.program_created",
            {"program_id": str(prog.id), "college_id": str(c.id), "code": prog.code},
            "program",
            prog.id,
        )
        return prog

    async def upsert_approval(
        self,
        c: College,
        program_id: uuid.UUID,
        year_id: uuid.UUID,
        *,
        sanctioned: int,
        lateral: int,
        status: str,
        order_no: str | None,
        valid_from: date | None,
        valid_to: date | None,
        conditions: dict[str, Any] | None,
    ) -> AffiliationProgramApproval:
        row = (
            await self.db.execute(
                select(AffiliationProgramApproval)
                .where(
                    AffiliationProgramApproval.college_id == c.id,
                    AffiliationProgramApproval.program_id == program_id,
                    AffiliationProgramApproval.academic_year_id == year_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            row = AffiliationProgramApproval(
                institution_id=self.inst, college_id=c.id, program_id=program_id, academic_year_id=year_id
            )
            self.db.add(row)
        row.sanctioned_intake, row.lateral_intake, row.approval_status = sanctioned, lateral, status
        row.order_no, row.valid_from, row.valid_to, row.conditions = order_no, valid_from, valid_to, conditions
        await self.db.flush()
        return row

    async def decide(self, aid: uuid.UUID, body: DecisionIn) -> ApplicationOut:  # noqa: C901, PLR0912, PLR0915
        a = await self.visible(aid, lock=True)
        self.require_writer()
        if not self.decider():
            raise forbidden("affiliation:decide required")
        if a.status in DECIDED_STATUSES or a.status == "withdrawn":
            raise rule(f"The application is already {a.status}", "INVALID_TRANSITION")
        allowed = {"compliance_pending"}
        if not await self.soft_feature("affiliation.inspections"):
            allowed |= {"fee_paid", "scrutiny"}
        if a.status not in allowed:
            raise rule(f"A {a.status} application is not ready for a decision", "NOT_READY", current=a.status)
        if (
            body.decision != "rejected"
            and a.application_type != "program_closure"
            and not body.programs
            and (a.programs or [])
        ):
            raise APIError(
                422, ErrorCode.VALIDATION, "Per-programme intake and validity are required", {"field": "programs"}
            )
        rid, rnum = await self._resolution(a, body.resolution_id)
        c = await self.college(a.college_id, lock=True)
        meta = await self.meta("app", a.id)
        order_date = body.order_date or await self.today()
        order_no = await self.sequence("order", "ORD")
        validity = await self.aff_setting("order_validity_years") or {}
        a.status = body.decision
        a.decided_by = self.actor_id
        a.order_no = order_no
        approvals: list[str] = []
        if body.decision != "rejected":
            year = await self.year(a.academic_year_id)
            by_code = {str(p.get("program_code")): p for p in a.programs or []}
            for i, dp in enumerate(body.programs):
                pid = dp.program_id
                if pid is None and dp.new_code:
                    src = by_code.get(dp.new_code)
                    if src is None or not src.get("new"):
                        raise APIError(422, ErrorCode.VALIDATION, f"Programme {dp.new_code} is not in the application")
                    pid = (await self._new_program(c, src)).id
                if pid is None:
                    raise APIError(422, ErrorCode.VALIDATION, f"programs.{i}: program_id or new_code is required")
                prog = (await self.programs_map([pid])).get(pid)
                if prog is None or prog.college_id != c.id:
                    raise APIError(422, ErrorCode.VALIDATION, f"programs.{i}: programme of another college")
                years = int(validity.get(str(dp.approval_status), validity.get("provisional", 1)) or 1)
                vf = dp.valid_from or year.start_date
                vt = dp.valid_to or (vf.replace(year=vf.year + years) - timedelta(days=1))
                st = (
                    "conditional"
                    if body.decision == "conditional" and dp.approval_status != "withdrawn"
                    else str(dp.approval_status)
                )
                row = await self.upsert_approval(
                    c,
                    pid,
                    a.academic_year_id,
                    sanctioned=dp.sanctioned_intake,
                    lateral=dp.lateral_intake,
                    status=st,
                    order_no=order_no,
                    valid_from=vf,
                    valid_to=vt,
                    conditions={"items": body.conditions, "application_id": str(a.id)}
                    if body.conditions
                    else {"application_id": str(a.id)},
                )
                approvals.append(str(row.id))
                if prog.sanctioned_intake != dp.sanctioned_intake or (prog.lateral_intake or 0) != dp.lateral_intake:
                    prog.sanctioned_intake, prog.lateral_intake = dp.sanctioned_intake, dp.lateral_intake
            if a.application_type == "program_closure":
                for p in a.programs or []:
                    if not p.get("program_id"):
                        continue
                    pid = uuid.UUID(str(p["program_id"]))
                    prev = (
                        await self.db.execute(
                            select(AffiliationProgramApproval)
                            .where(
                                AffiliationProgramApproval.college_id == c.id,
                                AffiliationProgramApproval.program_id == pid,
                            )
                            .order_by(AffiliationProgramApproval.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    row = await self.upsert_approval(
                        c,
                        pid,
                        a.academic_year_id,
                        sanctioned=int(prev.sanctioned_intake) if prev else 0,
                        lateral=int(prev.lateral_intake or 0) if prev else 0,
                        status="withdrawn",
                        order_no=order_no,
                        valid_from=order_date,
                        valid_to=None,
                        conditions={"closure": True, "application_id": str(a.id), "items": body.conditions},
                    )
                    approvals.append(str(row.id))
                    prog = (await self.programs_map([pid])).get(pid)
                    if prog is not None:
                        prog.status = "closed"
                    await self._emit(
                        "affiliation.program_withdrawn",
                        {"program_id": str(pid), "college_id": str(c.id), "closure": True},
                        "program",
                        pid,
                    )
            if a.application_type == "new":
                if not c.affiliated_since:
                    c.affiliated_since = order_date
                if not c.affiliation_number:
                    c.affiliation_number = order_no[:40]
                if c.college_type == "constituent":
                    c.college_type = "affiliated"
            if a.application_type == "autonomy":
                from app.services.affiliation.college_registry_service import CollegeRegistryService

                await CollegeRegistryService(self.db, self.principal, self.request, self.inst).transition_type(
                    c, "autonomous", a.academic_year_id, f"autonomy order {order_no}"
                )
        decision = {
            "decision": body.decision,
            "conditions": body.conditions,
            "resolution_id": str(rid) if rid else None,
            "resolution_number": rnum,
            "order_no": order_no,
            "order_date": order_date.isoformat(),
            "decided_by": str(self.actor_id) if self.actor_id else None,
        }
        meta["decision"] = decision
        meta["approvals"] = approvals
        if body.remarks:
            meta["decision_remarks"] = body.remarks
        await self.put_meta("app", a.id, meta)
        await self.db.flush()
        doc = await self.render_doc("affiliation_order", ENTITY, a.id, None, allow_multiple=True)
        a.order_url = (
            doc.pdf_url if doc and doc.pdf_url else None
        ) or f"/api/v1/affiliation/applications/{a.id}/order.pdf"
        meta = await self.meta("app", a.id)
        meta["decision"] = {
            **decision,
            "order_url": a.order_url,
            "issued_document_id": str(doc.issued_document_id) if doc else None,
        }
        await self.put_meta("app", a.id, meta)
        await self.db.flush()
        await self._wf_act(a, body.decision != "rejected", f"Decision: {body.decision}")
        await self.close_workflow(a.workflow_instance_id, "approved" if body.decision != "rejected" else "rejected")
        await self.timeline("app", a.id, "decided", decision=body.decision, order_no=order_no)
        await self._audit("decide", ENTITY, a.id, None, {"decision": body.decision, "order_no": order_no})
        payload = {
            "application_id": str(a.id),
            "college_id": str(c.id),
            "type": a.application_type,
            "decision": body.decision,
            "order_no": order_no,
            "resolution_id": str(rid) if rid else None,
        }
        await self._emit("affiliation.decided", payload, ENTITY, a.id)
        await self._emit("affiliation.order_issued", payload, ENTITY, a.id)
        for ap in approvals:
            await self._emit(
                "affiliation.program_approved",
                {"approval_id": ap, "college_id": str(c.id)},
                "affiliation_program_approval",
                uuid.UUID(ap),
            )
        await self.notify_college(
            c, "affiliation.decision", {"number": meta.get("number"), "decision": body.decision, "order_no": order_no}
        )
        return (await self.outs([a]))[0]

    async def order_lines(self, aid: uuid.UUID) -> tuple[str, list[str]]:
        a = await self.visible(aid)
        if a.status not in DECIDED_STATUSES:
            raise rule("No order has been issued yet", "NO_ORDER", 404)
        ctx = await order_context(self, a)
        lines = [
            f"Order No. {ctx['order']['number']}  ·  Date {ctx['order']['date']}",
            f"To: The Principal, {ctx['college']['name']} ({ctx['college']['code']})",
            f"Subject: {ctx['application']['type_label']} — {ctx['application']['number']} — {ctx['academic_year']}",
            "",
            f"Decision: {ctx['order']['decision'].upper()}",
        ]
        if ctx["order"]["resolution"]:
            lines.append(f"Cited resolution: {ctx['order']['resolution']}")
        if ctx["programs_list"]:
            lines += ["", "Programmes:"] + ctx["programs_list"]
        if ctx["order"]["conditions"]:
            lines += ["", "Conditions:"] + [f"  - {x}" for x in ctx["order"]["conditions"]]
        lines += ["", "Registrar"]
        return str(a.order_no or a.id), lines

    # ---- scans --------------------------------------------------------------------------------------------------------
    async def deficiency_deadline_scan(self) -> int:
        today = await self.today()
        n = 0
        rows = (
            await self.db.execute(
                select(AffiliationApplication).where(
                    AffiliationApplication.institution_id == self.inst, AffiliationApplication.status == "inspected"
                )
            )
        ).scalars()
        for a in rows:
            overdue = [
                d
                for d in a.deficiencies or []
                if d.get("status") == "open" and d.get("due_on") and date.fromisoformat(d["due_on"]) < today
            ]
            if not overdue:
                continue
            key = f"def:{a.id}:{today.isoformat()}"
            if (await self.meta("reminded", key)).get("sent"):
                continue
            c = await self.college(a.college_id)
            m = await self.meta("app", a.id)
            await self.notify_college(
                c,
                "affiliation.deficiency",
                {"number": m.get("number"), "items": f"{len(overdue)} deficiency response(s) overdue"},
            )
            await self._notify(
                "affiliation.deficiency",
                await self.office_users(),
                {"college": c.name, "number": m.get("number"), "items": "overdue responses"},
            )
            await self.put_meta("reminded", key, {"sent": True})
            n += 1
        return n

    async def inspection_reminders(self) -> int:
        today = await self.today()
        n = 0
        rows = (
            await self.db.execute(
                select(AffiliationApplication).where(
                    AffiliationApplication.institution_id == self.inst,
                    AffiliationApplication.status == "inspection_scheduled",
                    AffiliationApplication.inspection_on.in_(
                        [today, today + timedelta(days=1), today + timedelta(days=7)]
                    ),
                )
            )
        ).scalars()
        for a in rows:
            m = await self.meta("app", a.id)
            c = await self.college(a.college_id)
            ctx = {
                "number": m.get("number"),
                "on": a.inspection_on.isoformat() if a.inspection_on else "",
                "mode": (a.inspection_committee or {}).get("mode") or "",
            }
            await self.notify_college(c, "affiliation.inspection_scheduled", ctx)
            await self._notify(
                "affiliation.inspection_scheduled",
                [await self.staff_user(uuid.UUID(s)) for s in self._committee_staff(a)],
                {"college": c.name, **ctx},
            )
            n += 1
        return n


async def order_context(svc: AffiliationBase, a: AffiliationApplication) -> dict[str, Any]:
    c = (await svc.db.execute(select(College).where(College.id == a.college_id))).scalar_one()
    meta = await svc.meta("app", a.id)
    dec = meta.get("decision") or {}
    years = await svc.years_map([a.academic_year_id])
    y = years.get(a.academic_year_id)
    approvals = list(
        (
            await svc.db.execute(
                select(AffiliationProgramApproval).where(
                    AffiliationProgramApproval.id.in_(
                        [uuid.UUID(x) for x in meta.get("approvals") or []] or [uuid.uuid4()]
                    )
                )
            )
        ).scalars()
    )
    progs = await svc.programs_map([r.program_id for r in approvals])
    plist = [
        f"  {progs[r.program_id].code if r.program_id in progs else r.program_id}: intake {r.sanctioned_intake}"
        f" + lateral {r.lateral_intake} · {r.approval_status} · valid {r.valid_from or ''} to {r.valid_to or ''}"
        for r in approvals
    ]
    return {
        "college": {"name": c.name, "code": c.code, "type": c.college_type},
        "application": {
            "number": meta.get("number") or "",
            "type": a.application_type,
            "type_label": a.application_type.replace("_", " ").title(),
        },
        "academic_year": y.name if y else "",
        "order": {
            "number": a.order_no or dec.get("order_no") or "",
            "date": dec.get("order_date") or "",
            "decision": dec.get("decision") or a.status,
            "conditions": dec.get("conditions") or [],
            "resolution": dec.get("resolution_number") or "",
        },
        "programs_list": plist,
        "programs": "<br>".join(x.strip() for x in plist),
        "deficiencies": "<br>".join(
            f"{d.get('id')}: {d.get('area')} — {d.get('observation')} ({d.get('severity')}; due {d.get('due_on')})"
            for d in a.deficiencies or []
            if d.get("status") != "closed"
        ),
        "inspection": {
            "on": a.inspection_on.isoformat() if a.inspection_on else "",
            "mode": (a.inspection_committee or {}).get("mode") or "",
            "recommendation": meta.get("recommendation") or "",
            "round": meta.get("rounds") or 1,
        },
    }


@register_resolver(ENTITY)
async def _application_ctx(svc: Any, aid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    a = (await svc.db.execute(select(AffiliationApplication).where(AffiliationApplication.id == aid))).scalar_one()
    base = AffiliationBase(svc.db, None, institution_id=a.institution_id)
    ctx = await order_context(base, a)
    ctx["conditions"] = "<br>".join(ctx["order"]["conditions"])
    ctx["title"] = f"Affiliation order {ctx['order']['number']}"
    ctx["body"] = ""
    return ctx, None, None


__all__ = ["ApplicationService", "is_auditor", "order_context"]
