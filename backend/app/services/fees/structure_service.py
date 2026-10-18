"""Heads, structures, discounts and fines — Prompts/12 §12.6 ``structure_service`` (+ invoice rule 3).

* heads CRUD (GST flag / rate, refundable, ledger mapping); the minimal ledger chart is read-only here (Phase 23);
* structures CRUD with effective dates and dimension validation — another *active* structure with the identical
  dimension set and overlapping dates → 409 ``CONFLICT``; items with instalments / due offsets; ``total_paise`` =
  Σ mandatory items; clone to the next year (optional % increase); ``applicable(enrolment, term)``;
* ``assign(structure, enrolments | batch)`` → ``student_fee_assignments`` (idempotent on the unique key) and,
  unless ``generate_invoices=false``, one term invoice per enrolment (idempotent per structure × term). Above 200
  enrolments the endpoint queues the job ``fees.bulk_invoice``; dry runs answer inline;
* discounts CRUD + assignment (workflow ``fees.concession`` when ``requires_approval``) → open invoices re-priced;
  staff-ward concession (``fees.staff_ward_concession``): a guardian user who is active staff gets the ``STAFFWARD``
  discount automatically;
* fine configurations (one row per ``applies_to``).
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.workflow import engine as workflow_engine
from app.models.academic import AcademicTerm
from app.models.fees import (
    FeeDiscount,
    FeeHead,
    FeeStructure,
    FeeStructureItem,
    FineConfiguration,
    StudentDiscountAssignment,
    StudentFeeAssignment,
)
from app.models.platform import WorkflowInstance
from app.models.students import StudentProgramEnrollment
from app.repositories.fee_repository import LedgerRepository, StructureRepository
from app.schemas.fees import (
    ApplicableStructureResponse,
    DiscountAssign,
    DiscountAssignmentOut,
    DiscountIn,
    DiscountOut,
    FeeAssignRequest,
    FeeAssignResult,
    FeeHeadIn,
    FeeHeadOut,
    FeeStructureCreate,
    FeeStructureItemIn,
    FeeStructureItemOut,
    FeeStructureResponse,
    FeeStructureUpdate,
    FineConfigIn,
    FineConfigOut,
    LedgerAccountOut,
    StructureCloneRequest,
)
from app.services.fees.common import FeesBase, rule
from app.services.fees.invoice_service import InvoiceService

WF_CONCESSION = "fees.concession"
DISCOUNT_ENTITY = "student_discount_assignment"
INLINE_LIMIT = 200


class StructureService(FeesBase):
    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.structures = StructureRepository(self.db, self.principal, self.inst)

    # ---- heads / ledger -------------------------------------------------------------------------------------------------
    async def heads(self) -> list[FeeHeadOut]:
        rows = (
            await self.db.execute(select(FeeHead).where(FeeHead.institution_id == self.inst).order_by(FeeHead.code))
        ).scalars()
        return [FeeHeadOut.model_validate(h) for h in rows]

    async def _head(self, hid: uuid.UUID) -> FeeHead:
        h = (
            await self.db.execute(
                select(FeeHead).where(FeeHead.id == hid, FeeHead.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if h is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Fee head not found")
        return h

    async def create_head(self, body: FeeHeadIn) -> FeeHeadOut:
        if (
            await self.db.execute(
                select(FeeHead.id).where(FeeHead.institution_id == self.inst, FeeHead.code == body.code)
            )
        ).first():
            raise APIError(409, ErrorCode.CONFLICT, f"Head {body.code} exists")
        h = FeeHead(
            institution_id=self.inst,
            **{
                **body.model_dump(),
                "head_type": str(body.head_type),
                "gst_rate": Decimal(str(body.gst_rate)) if body.gst_rate is not None else None,
            },
        )
        self.db.add(h)
        await self.db.flush()
        await self._audit("create", "fee_head", h.id, None, body.model_dump(mode="json"))
        return FeeHeadOut.model_validate(h)

    async def update_head(self, hid: uuid.UUID, body: FeeHeadIn) -> FeeHeadOut:
        h = await self._head(hid)
        old = FeeHeadOut.model_validate(h).model_dump(mode="json")
        for k, v in body.model_dump().items():
            if k == "gst_rate":
                v = Decimal(str(v)) if v is not None else None
            setattr(h, k, str(v) if k == "head_type" else v)
        await self.db.flush()
        await self._audit("update", "fee_head", h.id, old, body.model_dump(mode="json"))
        return FeeHeadOut.model_validate(h)

    async def delete_head(self, hid: uuid.UUID) -> None:
        h = await self._head(hid)
        used = (
            await self.db.execute(select(FeeStructureItem.id).where(FeeStructureItem.fee_head_id == h.id).limit(1))
        ).first()
        if used:
            h.is_active = False  # referenced: deactivate instead of deleting
        else:
            await self.db.delete(h)
        await self.db.flush()
        await self._audit("delete", "fee_head", hid, None, {"deactivated": bool(used)})

    async def ledger(self) -> list[LedgerAccountOut]:
        return [
            LedgerAccountOut.model_validate(a)
            for a in await LedgerRepository(self.db, self.principal, self.inst).chart()
        ]

    # ---- structures -----------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[FeeStructure]) -> list[FeeStructureResponse]:
        ids = [r.id for r in rows]
        heads = {h.id: h for h in (await self.heads_by_code()).values()}
        items: dict[uuid.UUID, list[FeeStructureItem]] = {i: [] for i in ids}
        counts: dict[uuid.UUID, int] = {}
        if ids:
            for it in (
                await self.db.execute(
                    select(FeeStructureItem)
                    .where(FeeStructureItem.structure_id.in_(ids))
                    .order_by(FeeStructureItem.instalment_no)
                )
            ).scalars():
                items[it.structure_id].append(it)
            counts = dict(
                (  # type: ignore[arg-type]
                    await self.db.execute(
                        select(StudentFeeAssignment.structure_id, func.count())
                        .where(StudentFeeAssignment.structure_id.in_(ids))
                        .group_by(StudentFeeAssignment.structure_id)
                    )
                ).all()
            )
        out = []
        for r in rows:
            o = FeeStructureResponse.model_validate(r)
            o.items = []
            for it in items[r.id]:
                io = FeeStructureItemOut.model_validate(it)
                h = heads.get(it.fee_head_id)
                io.head_code, io.head_name = (h.code, h.name) if h else (None, None)
                o.items.append(io)
            o.assigned_count = int(counts.get(r.id, 0))
            out.append(o)
        return out

    async def list_structures(
        self, *, program_id: uuid.UUID | None = None, batch_id: uuid.UUID | None = None, status: str | None = None
    ) -> list[FeeStructureResponse]:
        q = self.structures._base()
        if program_id:
            q = q.where(FeeStructure.program_id == program_id)
        if batch_id:
            q = q.where(FeeStructure.batch_id == batch_id)
        if status:
            q = q.where(FeeStructure.status == status)
        return await self.outs(
            list(
                (await self.db.execute(q.order_by(FeeStructure.effective_from.desc(), FeeStructure.name)))
                .scalars()
                .all()
            )
        )

    async def get(self, sid: uuid.UUID) -> FeeStructureResponse:
        return (await self.outs([await self.structures.get(sid)]))[0]

    async def _set_items(self, s: FeeStructure, items: list[FeeStructureItemIn]) -> None:
        heads = {h.id for h in (await self.heads_by_code()).values()}
        seen = set()
        for it in items:
            if it.fee_head_id not in heads:
                raise APIError(422, ErrorCode.VALIDATION, "Unknown fee head", {"field": "items.fee_head_id"})
            key = (it.fee_head_id, it.instalment_no)
            if key in seen:
                raise APIError(422, ErrorCode.VALIDATION, "Duplicate head × instalment", {"field": "items"})
            seen.add(key)
        for old in (
            await self.db.execute(select(FeeStructureItem).where(FeeStructureItem.structure_id == s.id))
        ).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for it in items:
            self.db.add(FeeStructureItem(institution_id=self.inst, structure_id=s.id, **it.model_dump()))
        s.total_paise = sum(i.amount_paise for i in items if not i.is_optional)
        await self.db.flush()

    async def create(self, body: FeeStructureCreate) -> FeeStructureResponse:
        if (body.category or body.quota) and not await is_enabled(self.inst, "fees.structures_by_quota"):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                "Category / quota structures are disabled",
                {"feature": "fees.structures_by_quota"},
            )
        data = body.model_dump(exclude={"items"})
        clash = await self.structures.overlapping(type("S", (), data)())
        if clash is not None:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Overlaps structure '{clash.name}' with the same dimensions",
                {"structure_id": str(clash.id)},
            )
        s = FeeStructure(institution_id=self.inst, created_by=self.actor_id, status="active", **data)
        self.db.add(s)
        await self.db.flush()
        await self._set_items(s, body.items)
        await self._audit("create", "fee_structure", s.id, None, {"name": s.name, "total_paise": s.total_paise})
        return await self.get(s.id)

    async def update(self, sid: uuid.UUID, body: FeeStructureUpdate) -> FeeStructureResponse:
        s = await self.structures.get(sid, for_update=True)
        if body.version is not None and body.version != s.version:
            raise APIError(
                409, ErrorCode.STALE_VERSION, "Record was modified by someone else", {"current_version": s.version}
            )
        for k in ("name", "effective_to", "per_credit_paise", "status"):
            v = getattr(body, k)
            if v is not None:
                setattr(s, k, v)
        if s.status == "active":
            clash = await self.structures.overlapping(s, exclude=s.id)
            if clash is not None:
                raise APIError(
                    409, ErrorCode.CONFLICT, f"Overlaps structure '{clash.name}'", {"structure_id": str(clash.id)}
                )
        if body.items is not None:
            await self._set_items(s, body.items)
        s.version += 1
        await self.db.flush()
        await self._audit("update", "fee_structure", s.id, None, body.model_dump(mode="json", exclude_none=True))
        return await self.get(s.id)

    async def clone(self, sid: uuid.UUID, body: StructureCloneRequest) -> FeeStructureResponse:
        src = await self.structures.get(sid)
        items = (
            (await self.db.execute(select(FeeStructureItem).where(FeeStructureItem.structure_id == src.id)))
            .scalars()
            .all()
        )
        factor = Decimal(1) + Decimal(str(body.increase_pct)) / 100
        shift = (body.effective_from - src.effective_from).days
        new_items = [
            FeeStructureItemIn(
                fee_head_id=i.fee_head_id,
                amount_paise=int((Decimal(i.amount_paise) * factor).quantize(Decimal("1"))),
                instalment_no=i.instalment_no,
                due_date=i.due_date + timedelta(days=shift) if i.due_date else None,
                due_offset_days=i.due_offset_days,
                is_optional=i.is_optional,
            )
            for i in items
        ]
        return await self.create(
            FeeStructureCreate(
                name=body.name or f"{src.name} (copy)",
                college_id=src.college_id,
                academic_year_id=body.academic_year_id or src.academic_year_id,
                program_id=src.program_id,
                program_regulation_id=src.program_regulation_id,
                batch_id=src.batch_id,
                term_number=src.term_number,
                category=src.category,
                quota=src.quota,
                effective_from=body.effective_from,
                effective_to=body.effective_to,
                per_credit_paise=int(src.per_credit_paise * factor) if src.per_credit_paise else None,
                items=new_items,
            )
        )

    async def applicable(self, enrollment_id: uuid.UUID, term_number: int | None) -> ApplicableStructureResponse:
        enrol, student = await self.enrolment(enrollment_id)
        s, matched, n = await self.structures.applicable(enrol, student, term_number, await self.today())
        return ApplicableStructureResponse(
            structure=(await self.outs([s]))[0] if s else None, matched_on=matched, candidates=n
        )

    async def _targets(self, body: FeeAssignRequest) -> list[StudentProgramEnrollment]:
        q = select(StudentProgramEnrollment).where(
            StudentProgramEnrollment.institution_id == self.inst,
            StudentProgramEnrollment.deleted_at.is_(None),
            StudentProgramEnrollment.status.in_(("active", "provisional", "admitted")),
        )
        if body.enrollment_ids:
            q = q.where(StudentProgramEnrollment.id.in_(body.enrollment_ids))
        elif body.batch_id:
            q = q.where(StudentProgramEnrollment.batch_id == body.batch_id)
        else:
            raise APIError(422, ErrorCode.VALIDATION, "enrollment_ids or batch_id is required")
        return list((await self.db.execute(q)).scalars().all())

    async def count_targets(self, body: FeeAssignRequest) -> int:
        return len(await self._targets(body))

    async def assign(self, sid: uuid.UUID, body: FeeAssignRequest, progress: Any = None) -> FeeAssignResult:
        s = await self.structures.get(sid)
        targets = await self._targets(body)
        term = None
        if body.term_id:
            term = (
                await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == body.term_id))
            ).scalar_one_or_none()
        out = FeeAssignResult(dry_run=body.dry_run)
        inv_svc = InvoiceService(self.db, self.principal, self.request, self.inst)
        for n, e in enumerate(targets):
            existing = (
                await self.db.execute(
                    select(StudentFeeAssignment).where(
                        StudentFeeAssignment.student_program_enrollment_id == e.id,
                        StudentFeeAssignment.structure_id == s.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                out.already += 1
            elif not body.dry_run:
                self.db.add(
                    StudentFeeAssignment(
                        institution_id=self.inst,
                        student_program_enrollment_id=e.id,
                        structure_id=s.id,
                        term_id=term.id if term else None,
                        assigned_by=self.actor_id,
                    )
                )
                await self.db.flush()
                out.assigned += 1
            else:
                out.assigned += 1
            if body.generate_invoices:
                t = term or await self.current_term(e.college_id)
                if await inv_svc.structure_invoice_exists(s, e.id, t.id if t else None):
                    continue
                if body.dry_run:
                    out.invoices_created += 1
                    continue
                try:
                    await inv_svc.from_structure(s, e, t)
                    out.invoices_created += 1
                except APIError as exc:
                    out.skipped.append({"enrollment_id": str(e.id), "reason": exc.message})
            if progress and n % 25 == 0:
                await progress(int(n * 100 / max(1, len(targets))), f"{n}/{len(targets)}")
        if not body.dry_run:
            await self._audit("assign", "fee_structure", s.id, None, out.model_dump(mode="json", exclude={"skipped"}))
        return out

    async def auto_assign(self, enrol_id: uuid.UUID) -> int:
        """Consumer path (``student.created`` / ``batch.promoted``): applicable structure → assignment + invoice."""
        enrol, student = await self.enrolment(enrol_id)
        inv_svc = InvoiceService(self.db, self.principal, self.request, self.inst)
        term = await self.current_term(enrol.college_id)
        tn = await inv_svc.term_number_of(enrol, term)
        s, _, _ = await self.structures.applicable(enrol, student, tn, await self.today())
        if s is None:
            return 0
        res = await self.assign(s.id, FeeAssignRequest(enrollment_ids=[enrol.id], term_id=term.id if term else None))
        return res.invoices_created

    # ---- discounts --------------------------------------------------------------------------------------------------------
    async def discounts(self) -> list[DiscountOut]:
        rows = (
            await self.db.execute(
                select(FeeDiscount).where(FeeDiscount.institution_id == self.inst).order_by(FeeDiscount.code)
            )
        ).scalars()
        return [DiscountOut.model_validate(d) for d in rows]

    async def save_discount(self, body: DiscountIn, did: uuid.UUID | None = None) -> DiscountOut:
        if body.discount_type == "percentage" and body.value > 100:
            raise APIError(422, ErrorCode.VALIDATION, "A percentage cannot exceed 100", {"field": "value"})
        data = {**body.model_dump(), "discount_type": str(body.discount_type), "value": Decimal(str(body.value))}
        if did is None:
            if (
                await self.db.execute(
                    select(FeeDiscount.id).where(FeeDiscount.institution_id == self.inst, FeeDiscount.code == body.code)
                )
            ).first():
                raise APIError(409, ErrorCode.CONFLICT, f"Discount {body.code} exists")
            d: Any = FeeDiscount(institution_id=self.inst, **data)
            self.db.add(d)
        else:
            d = (
                await self.db.execute(
                    select(FeeDiscount)
                    .where(FeeDiscount.id == did, FeeDiscount.institution_id == self.inst)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if d is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Discount not found")
            for k, v in data.items():
                setattr(d, k, v)
        await self.db.flush()
        await self._audit("save", "fee_discount", d.id, None, body.model_dump(mode="json"))
        return DiscountOut.model_validate(d)

    async def assignment_outs(self, rows: list[StudentDiscountAssignment]) -> list[DiscountAssignmentOut]:
        ds = (
            {
                d.id: d
                for d in (
                    await self.db.execute(select(FeeDiscount).where(FeeDiscount.id.in_([r.discount_id for r in rows])))
                ).scalars()
            }
            if rows
            else {}
        )
        out = []
        for r in rows:
            o = DiscountAssignmentOut.model_validate(r)
            d = ds.get(r.discount_id)
            o.discount_code, o.discount_name = (d.code, d.name) if d else (None, None)
            out.append(o)
        return out

    async def assign_discount(self, did: uuid.UUID, body: DiscountAssign) -> DiscountAssignmentOut:
        d = (
            await self.db.execute(
                select(FeeDiscount).where(
                    FeeDiscount.id == did, FeeDiscount.institution_id == self.inst, FeeDiscount.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if d is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Discount not found")
        enrol, _ = await self.enrolment(body.enrollment_id)
        live = (
            await self.db.execute(
                select(StudentDiscountAssignment.id).where(
                    StudentDiscountAssignment.student_program_enrollment_id == enrol.id,
                    StudentDiscountAssignment.discount_id == d.id,
                    StudentDiscountAssignment.status.in_(("approved", "pending")),
                )
            )
        ).first()
        if live:
            raise APIError(409, ErrorCode.CONFLICT, "The discount is already assigned")
        row = StudentDiscountAssignment(
            institution_id=self.inst,
            student_program_enrollment_id=enrol.id,
            discount_id=d.id,
            academic_year_id=body.academic_year_id,
            reason=body.reason,
            status="pending" if d.requires_approval else "approved",
            approved_by=None if d.requires_approval else self.actor_id,
        )
        self.db.add(row)
        await self.db.flush()
        if d.requires_approval:
            try:
                wf = await workflow_engine.start(
                    self.db,
                    institution_id=self.inst,
                    key=WF_CONCESSION,
                    entity_type=DISCOUNT_ENTITY,
                    entity_id=row.id,
                    started_by=self.actor_id,
                    context={"department_id": str(enrol.department_id)},
                    title=f"Concession {d.code} · {body.reason[:80]}",
                )
                row.workflow_instance_id = wf.id
            except APIError:
                row.status, row.approved_by = "approved", self.actor_id
        await self.db.flush()
        if row.status == "approved":
            await InvoiceService(self.db, self.principal, self.request, self.inst).reapply_discounts(enrol.id)
        await self._audit(
            "assign_discount",
            DISCOUNT_ENTITY,
            row.id,
            None,
            {"discount": d.code, "status": row.status, "reason": body.reason},
        )
        return (await self.assignment_outs([row]))[0]

    async def decide_discount(self, aid: uuid.UUID, approve: bool, via_workflow: bool = False) -> DiscountAssignmentOut:
        row = (
            await self.db.execute(
                select(StudentDiscountAssignment)
                .where(StudentDiscountAssignment.id == aid, StudentDiscountAssignment.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Assignment not found")
        if row.status != "pending":
            raise APIError(409, ErrorCode.CONFLICT, f"Already {row.status}")
        if not via_workflow and row.workflow_instance_id:
            await workflow_engine.act(
                self.db,
                instance_id=row.workflow_instance_id,
                actor=self.principal,
                decision="approve" if approve else "reject",
                comment=None,
            )
            await self.db.refresh(row)
            return (await self.assignment_outs([row]))[0]
        row.status, row.approved_by = ("approved" if approve else "rejected"), self.actor_id
        await self.db.flush()
        if approve:
            await InvoiceService(self.db, self.principal, self.request, self.inst).reapply_discounts(
                row.student_program_enrollment_id
            )
        await self._audit("decide_discount", DISCOUNT_ENTITY, row.id, {"status": "pending"}, {"status": row.status})
        return (await self.assignment_outs([row]))[0]

    async def student_discounts(self, student_id: uuid.UUID) -> list[DiscountAssignmentOut]:
        from app.repositories.fee_scope import enrollment_column_predicate

        q = (
            select(StudentDiscountAssignment)
            .join(
                StudentProgramEnrollment,
                StudentProgramEnrollment.id == StudentDiscountAssignment.student_program_enrollment_id,
            )
            .where(StudentProgramEnrollment.student_id == student_id)
        )
        if self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            q = q.where(
                enrollment_column_predicate(
                    self.principal, StudentDiscountAssignment.student_program_enrollment_id, "all", "fees"
                )
            )
        return await self.assignment_outs(list((await self.db.execute(q)).scalars().all()))

    async def pending_discounts(self) -> list[DiscountAssignmentOut]:
        rows = (
            (
                await self.db.execute(
                    select(StudentDiscountAssignment).where(
                        StudentDiscountAssignment.institution_id == self.inst,
                        StudentDiscountAssignment.status == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.assignment_outs(list(rows))

    async def staff_ward_concession(self, enrol_id: uuid.UUID) -> bool:
        if not await is_enabled(self.inst, "fees.staff_ward_concession"):
            return False
        from app.models.hr import Staff
        from app.models.students import StudentGuardian

        enrol, _ = await self.enrolment(enrol_id)
        staff = (
            await self.db.execute(
                select(Staff.id)
                .join(StudentGuardian, StudentGuardian.user_id == Staff.user_id)
                .where(
                    StudentGuardian.student_id == enrol.student_id,
                    Staff.deleted_at.is_(None),
                    Staff.exit_date.is_(None),
                )
                .limit(1)
            )
        ).first()
        if not staff:
            return False
        d = (
            await self.db.execute(
                select(FeeDiscount).where(
                    FeeDiscount.institution_id == self.inst,
                    FeeDiscount.code == "STAFFWARD",
                    FeeDiscount.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if d is None:
            return False
        exists = (
            await self.db.execute(
                select(StudentDiscountAssignment.id).where(
                    StudentDiscountAssignment.student_program_enrollment_id == enrol.id,
                    StudentDiscountAssignment.discount_id == d.id,
                )
            )
        ).first()
        if exists:
            return False
        self.db.add(
            StudentDiscountAssignment(
                institution_id=self.inst,
                student_program_enrollment_id=enrol.id,
                discount_id=d.id,
                reason="Staff ward (automatic)",
                status="approved",
                approved_by=self.actor_id,
            )
        )
        await self.db.flush()
        await InvoiceService(self.db, self.principal, self.request, self.inst).reapply_discounts(enrol.id)
        return True

    # ---- fines ------------------------------------------------------------------------------------------------------------
    async def fines(self) -> list[FineConfigOut]:
        rows = (
            await self.db.execute(
                select(FineConfiguration)
                .where(FineConfiguration.institution_id == self.inst)
                .order_by(FineConfiguration.applies_to)
            )
        ).scalars()
        return [FineConfigOut.model_validate(r) for r in rows]

    async def save_fines(self, body: list[FineConfigIn]) -> list[FineConfigOut]:
        for f in body:
            data = {**f.model_dump(exclude={"id"}), "applies_to": str(f.applies_to), "calc_type": str(f.calc_type)}
            row = None
            if f.id:
                row = (
                    await self.db.execute(
                        select(FineConfiguration).where(
                            FineConfiguration.id == f.id, FineConfiguration.institution_id == self.inst
                        )
                    )
                ).scalar_one_or_none()
            if row is None:
                row = (
                    (
                        await self.db.execute(
                            select(FineConfiguration).where(
                                FineConfiguration.institution_id == self.inst,
                                FineConfiguration.applies_to == data["applies_to"],
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
            if row is None:
                self.db.add(FineConfiguration(institution_id=self.inst, **data))
            else:
                for k, v in data.items():
                    setattr(row, k, v)
        await self.db.flush()
        await self._audit("save_fines", "fine_configuration", None, None, {"rows": len(body)})
        return await self.fines()


# ---- workflow hooks ---------------------------------------------------------------------------------------------------------
def _svc(db: Any, instance: WorkflowInstance, actor: Any) -> StructureService:
    from app.services.fees.payment_service import _Actor

    return StructureService(
        db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id
    )


@workflow_engine.on(WF_CONCESSION, "approved")
async def _concession_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == DISCOUNT_ENTITY:
        await _svc(db, instance, actor).decide_discount(instance.entity_id, True, via_workflow=True)


@workflow_engine.on(WF_CONCESSION, "rejected")
async def _concession_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == DISCOUNT_ENTITY:
        await _svc(db, instance, actor).decide_discount(instance.entity_id, False, via_workflow=True)


@workflow_engine.summariser(DISCOUNT_ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(StudentDiscountAssignment, FeeDiscount)
            .join(FeeDiscount, FeeDiscount.id == StudentDiscountAssignment.discount_id)
            .where(StudentDiscountAssignment.id == entity_id)
        )
    ).first()
    if row is None:
        return None, None
    return f"Concession {row[1].code} ({row[1].name}) — {row[0].reason or ''}", "/admin/fees/discounts"


__all__ = ["StructureService", "rule"]
