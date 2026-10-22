"""``exams`` demo seeder (Prompts/14 §14.2) — ``seed_demo_institution.py --type university --only exams``.

On top of ``assessment`` / ``fees`` (offerings, confirmed registrations, eligibility v1, fee heads):

* a regular session for the current term (registration open from 5 days ago, late fee window, hall tickets released)
  with papers from every offered course + arrear-only courses (bulk), a date-sheet over 10 days FN / AN starting
  three weeks out (published; clashes force-published by the COE and recorded as exceptions);
* registrations for every enrolment with confirmed items (bulk), ~92 % paid (counter cash), the rest ``fee_pending``;
  the term eligibility applied (detained / pending items flagged); hall tickets generated;
* seating for the first exam day FN across the largest rooms (published), invigilation auto-assigned for that slot,
  QP assignments (sets A/B) for 6 papers — set B of three papers to the external examiner ``examiner.ext`` —
  with uploads, one selected set and a logged print; hall attendance for the first paper with 3 malpractice reports;
* an arrear session in ``draft``.

Idempotent: sessions dedupe by name; the rest runs only when the session has no registrations yet.
"""

import uuid
from datetime import UTC, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("exams", after=["assessment", "fees"])
async def seed_exams(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401  (``is_enabled`` needs the full registry outside the API process)
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import AcademicTerm
    from app.models.exams import ExamPaper, ExamRegistration, ExamRegistrationItem, ExamSeatingPlan, ExamSession
    from app.models.fees import FeeInvoice
    from app.models.hr import Staff
    from app.models.platform import Institution, User
    from app.models.timetable import Room
    from app.schemas.exams import (
        BulkPapersRequest,
        DateSheetEntry,
        DateSheetUpdate,
        EligibilityApplyRequest,
        ExamSessionCreate,
        HallAttendanceMark,
        HallAttendanceRow,
        HallTicketGenerateRequest,
        InvigilationAutoAssignRequest,
        MalpracticeReportCreate,
        QpAssignmentCreate,
        QpPrintRequest,
        QpScrutinyRequest,
        SeatingGenerateRequest,
    )
    from app.services.auth_service import load_principal
    from app.services.exams.duty_qp_service import ConductService, InvigilationService, QpService
    from app.services.exams.hall_seating_service import HallTicketService, SeatingService
    from app.services.exams.registration_service import ExamRegistrationService
    from app.services.exams.session_service import ExamSessionService
    from app.services.fees.payment_service import PaymentService

    db = ctx.db
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)

    async def user(name: str) -> User | None:
        u: User | None = (await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))).scalar_one_or_none()
        return u

    admin = await user("inst.admin")
    assert admin is not None
    p = await load_principal(db, admin.id)
    acct = await user("accountant")
    p_acct = await load_principal(db, acct.id) if acct else p
    today = today_for(inst)
    term = (await db.execute(select(AcademicTerm).where(AcademicTerm.institution_id == inst.id, AcademicTerm.college_id.is_(None), AcademicTerm.is_current.is_(True), AcademicTerm.deleted_at.is_(None)))).scalar_one()
    sessions = ExamSessionService(db, p, institution_id=inst.id)
    regs = ExamRegistrationService(db, p, institution_id=inst.id)
    now = datetime.now(UTC)
    name = f"{term.name} — End-semester (regular)"
    s = (await db.execute(select(ExamSession).where(ExamSession.institution_id == inst.id, ExamSession.name == name))).scalar_one_or_none()
    if s is None:
        out = await sessions.create(ExamSessionCreate(name=name, term_id=term.id, exam_kind="regular", registration_start=now - timedelta(days=5), registration_end=now + timedelta(days=5), late_fee_until=now + timedelta(days=10), hall_ticket_release_at=now - timedelta(days=1), start_date=today + timedelta(days=21), end_date=today + timedelta(days=31)))
        s = (await db.execute(select(ExamSession).where(ExamSession.id == out.id))).scalar_one()
        ctx.count("exam_sessions")
    if (await db.execute(select(func.count()).select_from(ExamRegistration).where(ExamRegistration.exam_session_id == s.id))).scalar_one():
        return
    bulk = await sessions.papers_bulk(s.id, BulkPapersRequest())
    ctx.count("exam_papers", bulk.created)
    papers = (await db.execute(select(ExamPaper).where(ExamPaper.exam_session_id == s.id).order_by(ExamPaper.paper_type, ExamPaper.paper_code))).scalars().all()
    entries = []
    for i, pp in enumerate(papers):
        day = today + timedelta(days=21 + (i // 2) % 10)
        entries.append(DateSheetEntry(paper_id=pp.id, exam_date=day, session_slot="FN" if i % 2 == 0 else "AN"))
    await sessions.update_date_sheet(s.id, DateSheetUpdate(entries=entries))
    coe = await user("coe")
    coe_sessions = ExamSessionService(db, await load_principal(db, coe.id), institution_id=inst.id) if coe else sessions
    report = await coe_sessions.publish_date_sheet(s.id, force=True)
    ctx.count("date_sheet_clash_exceptions", len(report.items))
    await sessions.change_status(s.id, "registration_open")

    # ---- registrations + fees ---------------------------------------------------------------------------------------
    res = await regs.bulk_register(s.id)
    ctx.count("exam_registrations", res["registrations"])
    pay = PaymentService(db, p_acct, institution_id=inst.id)
    pay.queue_receipt = _noop  # type: ignore[method-assign]
    pending = (await db.execute(select(ExamRegistration).where(ExamRegistration.exam_session_id == s.id, ExamRegistration.status == "fee_pending"))).scalars().all()
    for n, reg in enumerate(pending):
        if n % 12 == 11 or reg.fee_invoice_id is None:
            continue  # ~8 % stay fee_pending
        inv = (await db.execute(select(FeeInvoice).where(FeeInvoice.id == reg.fee_invoice_id).with_for_update())).scalar_one()
        await pay.recompute(inv)
        if inv.balance_paise > 0:
            await pay.record(inv, inv.balance_paise, "cash", counter="exam", emit=False)
        await regs.on_paid(reg.id)
    await regs.apply_eligibility(s.id, EligibilityApplyRequest())
    ht = await HallTicketService(db, p, institution_id=inst.id).generate(s.id, HallTicketGenerateRequest(only_missing=True))
    ctx.count("hall_tickets", ht["issued"])

    # ---- seating + invigilation for day 1 FN --------------------------------------------------------------------------
    first = min((pp for pp in papers if pp.exam_date), key=lambda x: (x.exam_date, x.session_slot), default=None)
    if first is not None:
        rooms = (await db.execute(select(Room).where(Room.institution_id == inst.id, Room.deleted_at.is_(None), Room.is_active.is_(True)).order_by(Room.capacity.desc()).limit(6))).scalars().all()
        seating = SeatingService(db, p, institution_id=inst.id)
        try:
            out = await seating.generate(s.id, SeatingGenerateRequest(exam_date=first.exam_date, session_slot="FN", room_ids=[r.id for r in rooms]))
            await seating.publish(s.id, first.exam_date, "FN")
            ctx.count("seat_allocations", out.allocated)
            inv_out = await InvigilationService(db, p, institution_id=inst.id).auto_assign(s.id, InvigilationAutoAssignRequest(date_from=first.exam_date, date_to=first.exam_date))
            ctx.count("invigilation_duties", inv_out.duties)
        except APIError as exc:
            print(f"   seating skipped: {exc.message}")

    # ---- question papers ---------------------------------------------------------------------------------------------
    qp = QpService(db, await load_principal(db, coe.id) if coe else p, institution_id=inst.id)
    ext = await user("examiner.ext")
    staff = (await db.execute(select(Staff).where(Staff.institution_id == inst.id, Staff.deleted_at.is_(None), Staff.staff_category == "teaching").limit(6))).scalars().all()
    theory = [pp for pp in papers if pp.paper_type == "theory"][:6]
    for i, pp in enumerate(theory):
        a = await qp.create(pp.id, QpAssignmentCreate(setter_staff_id=staff[i % len(staff)].id if staff else None, set_label="A", remuneration_paise=200000, external_setter=None if staff else {"name": "Setter"}))
        b_ext = {"name": "External examiner", "email": "examiner@example.invalid", "user_id": str(ext.id)} if ext and i < 3 else None
        b = await qp.create(pp.id, QpAssignmentCreate(setter_staff_id=None if b_ext else (staff[(i + 1) % len(staff)].id if staff else None), external_setter=b_ext or (None if staff else {"name": "Setter B"}), set_label="B", remuneration_paise=200000))
        await qp.upload(a.id, b"%PDF-1.4 demo question paper set A\n", "set-a.pdf")
        ctx.count("qp_assignments", 2)
        if i == 0:
            await qp.upload(b.id, b"%PDF-1.4 demo question paper set B\n", "set-b.pdf")
            await qp.scrutinise(a.id, QpScrutinyRequest(decision="approve", remarks="Balanced"))
            await QpService(db, await load_principal(db, coe.id), institution_id=inst.id).select_set(a.id) if coe else await qp.select_set(a.id)
            await qp.print(a.id, QpPrintRequest(copies=60))

    # ---- conduct: hall attendance + malpractice ------------------------------------------------------------------------
    if first is not None:
        conduct = ConductService(db, p, institution_id=inst.id)
        rows = await conduct.roster(first.id, None)
        marks = []
        for k, r in enumerate(rows):
            status = "absent" if k % 17 == 5 else "present"
            marks.append(HallAttendanceRow(exam_registration_item_id=r.exam_registration_item_id, status=status, answer_booklet_number=None if status == "absent" else f"AB{first.paper_code or ''}{k + 1:04d}"[:30]))
        if marks:
            await conduct.mark(first.id, HallAttendanceMark(items=marks))
            for r in rows[1:4]:
                await conduct.report_malpractice(first.id, MalpracticeReportCreate(exam_registration_item_id=r.exam_registration_item_id, category="material", invigilator_report="Chit found under the answer booklet"))
                ctx.count("malpractice_reports")

    # ---- arrear session in draft ----------------------------------------------------------------------------------------
    arrear_name = f"{term.name} — Arrear (supplementary)"
    if not (await db.execute(select(ExamSession.id).where(ExamSession.institution_id == inst.id, ExamSession.name == arrear_name))).first():
        await sessions.create(ExamSessionCreate(name=arrear_name, term_id=term.id, exam_kind="arrear"))
        ctx.count("exam_sessions")
    _ = (ExamRegistrationItem, ExamSeatingPlan, uuid)


async def _noop(*_: object, **__: object) -> None:
    return None
