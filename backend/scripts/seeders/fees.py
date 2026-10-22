"""``fees`` demo seeder (Prompts/12 §12.2) — ``seed_demo_institution.py --type university --only fees``.

On top of ``attendance`` / ``admissions`` (students, enrolments, terms; fee defaults come from revision ``0012``):

* structures per programme (general + an ``SC`` category structure) for the current term with **2 tuition
  instalments** (term start + 15 / + 75 days) + exam + library fees, and one **batch-specific** structure for
  student.1's batch (the most specific one wins);
* assignments + current-term invoices for every active enrolment; payments deterministic per enrolment: 60 % paid in
  full (cash / UPI / gateway / NEFT-reconciled mix), 25 % partial (instalment 1), 15 % unpaid (overdue once the first
  due date passes) — collected by ``accountant`` on counter ``main`` (day-book rows follow);
* 3 scholarships (central / state / institution) with applications in every pipeline state (one disbursed as a fee
  credit), 10 refund requests (requested / approved / processed / rejected), 20 no-dues requests with some sign-offs,
  a few bank-statement rows (one auto-matchable NEFT declaration);
* the earlier phases' fee stubs back-filled (``InvoiceService.backfill_stubs``).

Idempotent: structures dedupe by name, invoices per structure × term, scholarships by name, the rest only when the
institution has no refunds / no-dues yet.
"""

import hashlib
import uuid
from datetime import timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


def _roll(*parts: object) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:4], "big") / 2**32


@seeder("fees", after=["attendance", "admissions"])
async def seed_fees(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401  (``is_enabled`` needs the full registry outside the API process)
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import AcademicTerm, Program
    from app.models.fees import (
        FeeHead,
        FeeInvoice,
        FeeRefund,
        FeeStructure,
        NoDuesRequest,
        NoDuesSignoff,
        OfflinePaymentReconciliation,
        Scholarship,
        ScholarshipApplication,
    )
    from app.models.platform import Institution, User
    from app.models.students import Student, StudentProgramEnrollment
    from app.schemas.fees import (
        FeeAssignRequest,
        FeeStructureCreate,
        FeeStructureItemIn,
        OfflineDeclare,
        RefundCreate,
        RefundProcess,
    )
    from app.schemas.no_dues import NoDuesCreate
    from app.schemas.scholarships import DisburseRequest, ScholarshipDecision, ScholarshipIn
    from app.services.auth_service import load_principal
    from app.services.fees.defaults import seed_fee_defaults
    from app.services.fees.invoice_service import InvoiceService
    from app.services.fees.no_dues_service import NoDuesService
    from app.services.fees.payment_service import PaymentService
    from app.services.fees.refund_service import RefundService
    from app.services.fees.scholarship_service import ScholarshipService
    from app.services.fees.structure_service import StructureService

    db = ctx.db
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)

    async def user(name: str) -> User | None:
        u: User | None = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))
        ).scalar_one_or_none()
        return u

    admin = await user("inst.admin")
    acct = await user("accountant") or admin
    assert admin is not None and acct is not None
    p_admin = await load_principal(db, admin.id)
    p_acct = await load_principal(db, acct.id)
    today = today_for(inst)

    # fee masters (revision 0012 seeds them; a database seeded before the revision gets them here)
    if (await db.execute(select(func.count()).select_from(FeeHead).where(FeeHead.institution_id == inst.id))).scalar_one() == 0:
        await db.run_sync(lambda s: seed_fee_defaults(s.connection(), inst.id))
    heads = {
        h.code: h for h in (await db.execute(select(FeeHead).where(FeeHead.institution_id == inst.id))).scalars()
    }
    term = (
        await db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution_id == inst.id,
                AcademicTerm.college_id.is_(None),
                AcademicTerm.is_current.is_(True),
                AcademicTerm.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    start = term.start_date
    structures = StructureService(db, p_admin, institution_id=inst.id)

    def items(tuition: int) -> list[FeeStructureItemIn]:
        return [
            FeeStructureItemIn(fee_head_id=heads["TUITION"].id, amount_paise=tuition // 2, instalment_no=1, due_offset_days=15),
            FeeStructureItemIn(fee_head_id=heads["TUITION"].id, amount_paise=tuition - tuition // 2, instalment_no=2, due_offset_days=75),
            FeeStructureItemIn(fee_head_id=heads["EXAM"].id, amount_paise=150000, instalment_no=1, due_offset_days=15),
            FeeStructureItemIn(fee_head_id=heads["LIBRARY"].id, amount_paise=50000, instalment_no=1, due_offset_days=15),
        ]

    async def ensure(name: str, **dims: object) -> FeeStructure:
        row: FeeStructure | None = (
            await db.execute(select(FeeStructure).where(FeeStructure.institution_id == inst.id, FeeStructure.name == name))
        ).scalar_one_or_none()
        if row is not None:
            return row
        tuition = int(dims.pop("tuition"))  # type: ignore[call-overload]
        out = await structures.create(
            FeeStructureCreate(name=name, effective_from=start - timedelta(days=30), items=items(tuition), per_credit_paise=150000, **dims)  # type: ignore[arg-type]
        )
        ctx.count("fee_structures")
        return (await db.execute(select(FeeStructure).where(FeeStructure.id == out.id))).scalar_one()

    enrols = (
        await db.execute(
            select(StudentProgramEnrollment, Student)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                StudentProgramEnrollment.institution_id == inst.id,
                StudentProgramEnrollment.deleted_at.is_(None),
                StudentProgramEnrollment.status.in_(("active", "provisional", "admitted")),
            )
        )
    ).all()
    programs = {
        p.id: p
        for p in (
            await db.execute(select(Program).where(Program.id.in_({e.program_id for e, _ in enrols})))
        ).scalars()
    }
    for pid, prog in programs.items():
        await ensure(f"{prog.code} {term.name} — general", program_id=pid, tuition=6000000)
        await ensure(f"{prog.code} {term.name} — SC", program_id=pid, category="SC", tuition=1500000)
    s1 = await user("student.1")
    s1_enrol = next((e for e, st in enrols if s1 is not None and st.user_id == s1.id), None)
    if s1_enrol is not None:
        await ensure(f"Batch {str(s1_enrol.batch_id)[:6]} {term.name} — batch rate", program_id=s1_enrol.program_id, batch_id=s1_enrol.batch_id, tuition=5500000)
    await db.flush()

    # ---- assignments + invoices --------------------------------------------------------------------------------------
    inv_svc = InvoiceService(db, p_admin, institution_id=inst.id)
    pay = PaymentService(db, p_acct, institution_id=inst.id)
    pay.queue_receipt = _noop  # type: ignore[method-assign]  (receipts render on demand; no job per seeded payment)
    created = 0
    for e, st in enrols:
        tn = await inv_svc.term_number_of(e, term)
        s, _, _ = await structures.structures.applicable(e, st, tn, today)
        if s is None or await inv_svc.structure_invoice_exists(s, e.id, term.id):
            continue
        await structures.assign(s.id, FeeAssignRequest(enrollment_ids=[e.id], term_id=term.id))
        inv = (
            await db.execute(
                select(FeeInvoice).where(
                    FeeInvoice.student_program_enrollment_id == e.id,
                    FeeInvoice.source_type == "structure",
                    FeeInvoice.term_id == term.id,
                )
            )
        ).scalars().first()
        if inv is None:
            continue
        created += 1
        r = _roll(e.id, "fees")
        modes = ("cash", "upi", "gateway", "card", "cheque")
        mode = modes[int(_roll(e.id, "mode") * len(modes))]
        paid_on = max(start, today - timedelta(days=int(_roll(e.id, "day") * 10)))
        if r < 0.60:
            amount = inv.balance_paise
        elif r < 0.85:
            amount = inv.balance_paise // 2
        else:
            continue
        if amount > 0:
            await pay.record(inv, amount, mode, counter="main", reference=f"CHQ{str(e.id)[:6]}" if mode == "cheque" else None, emit=False, paid_on=paid_on)
            ctx.count("fee_payments")
    ctx.count("fee_invoices", created)
    await db.flush()

    # ---- offline declaration + a statement --------------------------------------------------------------------------
    if (await db.execute(select(func.count()).select_from(OfflinePaymentReconciliation).where(OfflinePaymentReconciliation.institution_id == inst.id))).scalar_one() == 0:
        open_inv = (
            await db.execute(select(FeeInvoice).where(FeeInvoice.institution_id == inst.id, FeeInvoice.status.in_(("pending", "overdue", "partial")), FeeInvoice.source_type == "structure").limit(1))
        ).scalars().first()
        if open_inv is not None:
            await pay.recompute(open_inv)
            amt = min(open_inv.balance_paise, 2500000)
            await PaymentService(db, p_admin, institution_id=inst.id).declare(OfflineDeclare(invoice_id=open_inv.id, amount_paise=amt, mode="neft", utr=f"UTRDEMO{today:%m%d}01", bank="SBI"))
            from app.schemas.fees import ReconcileRowIn

            await pay.reconcile_rows(
                [
                    ReconcileRowIn(utr=f"UTRDEMO{today:%m%d}01", amount_paise=amt, statement_date=today, payer_hint="NEFT demo"),
                    ReconcileRowIn(utr="UTRUNKNOWN99", amount_paise=123400, statement_date=today, payer_hint="Unknown payer"),
                ],
                None,
            )
            ctx.count("reconcile_rows", 2)

    # ---- scholarships -----------------------------------------------------------------------------------------------
    sch = ScholarshipService(db, p_admin, institution_id=inst.id)
    schemes = []
    for name, provider, amount, rules in (
        ("Post-Matric Scholarship (SC/ST)", "central_govt", 2000000, {"categories": ["SC", "ST"], "income_cap_paise": 25000000}),
        ("State Merit Scholarship", "state_govt", 1000000, {"min_cgpa": 7.5}),
        ("Institution Means-cum-Merit", "institution", 2000000, {"income_cap_paise": 80000000}),
    ):
        row = (await db.execute(select(Scholarship).where(Scholarship.institution_id == inst.id, Scholarship.name == name))).scalar_one_or_none()
        if row is None:
            out = await sch.save(ScholarshipIn(name=name, provider=provider, amount_paise=amount, eligibility_rules=rules, applications_open=today - timedelta(days=30), applications_close=today + timedelta(days=30)))  # type: ignore[arg-type]
            row = (await db.execute(select(Scholarship).where(Scholarship.id == out.id))).scalar_one()
            ctx.count("scholarships")
        schemes.append(row)
    if (await db.execute(select(func.count()).select_from(ScholarshipApplication).where(ScholarshipApplication.institution_id == inst.id))).scalar_one() == 0:
        states = ["applied", "applied", "verified", "recommended", "sanctioned", "disbursed", "rejected", "applied", "verified"]
        candidates = [(e, st) for e, st in enrols][:: max(1, len(enrols) // 12)][: len(states)]
        p_sch = ScholarshipService(db, p_acct, institution_id=inst.id)
        for (e, st), state in zip(candidates, states, strict=False):
            scheme = schemes[2]
            a = ScholarshipApplication(institution_id=inst.id, scholarship_id=scheme.id, student_program_enrollment_id=e.id, income_paise=30000000, documents=[{"type": "income_certificate", "url": None}], status="applied")
            db.add(a)
            await db.flush()
            d = ScholarshipDecision(comment="demo")
            if state in ("verified", "recommended", "sanctioned", "disbursed"):
                a.status = "verified"
            if state in ("recommended", "sanctioned", "disbursed"):
                a.status = "recommended"
            if state in ("sanctioned", "disbursed"):
                await sch.sanction(a.id, ScholarshipDecision(sanctioned_paise=2000000), via_workflow=True)
            if state == "disbursed":
                try:
                    await p_sch.disburse(a.id, DisburseRequest(mode="fee_credit"))  # type: ignore[arg-type]
                except Exception:  # noqa: BLE001 - no open invoice: record a bank transfer instead
                    await p_sch.disburse(a.id, DisburseRequest(mode="bank_transfer", reference="NEFT-DEMO"))  # type: ignore[arg-type]
            if state == "rejected":
                a.status = "rejected"
            del d
            ctx.count("scholarship_applications")
        await db.flush()

    # ---- refunds ----------------------------------------------------------------------------------------------------
    if (await db.execute(select(func.count()).select_from(FeeRefund).where(FeeRefund.institution_id == inst.id))).scalar_one() == 0:
        paid = (await db.execute(select(FeeInvoice).where(FeeInvoice.institution_id == inst.id, FeeInvoice.status == "paid").limit(10))).scalars().all()
        rs = RefundService(db, p_admin, institution_id=inst.id)
        for n, inv in enumerate(paid):
            out = await rs.submit(RefundCreate(invoice_id=inv.id, amount_paise=min(50000, inv.paid_paise), reason="Excess library fee collected"))
            if n % 4 in (1, 2):
                await rs.decide(out.id, True, None, via_workflow=True)
            if n % 4 == 2:
                await rs.process(out.id, RefundProcess(refund_mode="neft", reference_no=f"RFND{n:03d}"))
            if n % 4 == 3:
                await rs.decide(out.id, False, "Not eligible", via_workflow=True)
            ctx.count("fee_refunds")

    # ---- no-dues ----------------------------------------------------------------------------------------------------
    if (await db.execute(select(func.count()).select_from(NoDuesRequest).where(NoDuesRequest.institution_id == inst.id))).scalar_one() == 0:
        nd = NoDuesService(db, p_admin, institution_id=inst.id)
        purposes = ("graduation", "transfer", "hostel_vacate", "transcript", "exit")
        for n, (e, _) in enumerate(enrols[1:21]):
            out = await nd.create(NoDuesCreate(purpose=purposes[n % len(purposes)], enrollment_id=e.id), system=True)  # type: ignore[arg-type]
            signs = (await db.execute(select(NoDuesSignoff).where(NoDuesSignoff.request_id == out.id))).scalars().all()
            for k, s in enumerate(signs):
                if s.department_key == "accounts":
                    continue
                if n % 3 == 0 or k % 2 == 0:
                    s.status, s.signed_by, s.signed_at = "cleared", admin.id, inst.updated_at
                elif n % 5 == 1 and s.department_key == "library":
                    s.status, s.dues_paise, s.remarks = "dues_pending", 20000, "Overdue book"
            ctx.count("no_dues_requests")
        await db.flush()

    # ---- earlier phases' stubs -------------------------------------------------------------------------------------
    out = await inv_svc.backfill_stubs()
    ctx.count("fee_stubs_backfilled", out["registration"] + out["condonation"] + out["applicant"])


async def _noop(*_: object, **__: object) -> None:
    return None


__all__ = ["seed_fees", "uuid"]
