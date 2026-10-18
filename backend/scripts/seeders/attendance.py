"""``attendance`` demo seeder (Prompts/11 §11.2) — ``seed_demo_institution.py --type university --only attendance``.

On top of ``timetable`` (published section timetables with generated class sessions):

* attendance for the **last 6 weeks** of sessions up to yesterday (institution-local): each roster student has an
  attendance probability — 85 % on average; ``student.1`` and 7 more students sit in the condonable band (≈ 70 %),
  4 students below the condonation floor (≈ 55 %) → 12 students below 75 %, 4 below 65 %. Sessions become
  ``conducted`` / ``taken`` and those older than 3 days ``finalized`` (marks are deterministic per student/session);
* 5 on-duty requests (2 approved and applied, 1 recommended, 2 requested);
* 3 condonation requests (requested, HOD-recommended, approved with the fee order pending) for condonable students;
* summaries computed for every offering of the term and eligibility snapshot **v1** for the current term.

Idempotent: marks upsert on the partitioned unique key, OD / condonations dedupe per student, the eligibility
snapshot is only computed when the term has no version yet.
"""

import hashlib
import uuid
from datetime import timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.academic import AcademicTerm
from app.models.attendance import AttendanceCondonation, AttendanceSummary, OnDutyRequest, StudentClassAttendance
from app.models.platform import Institution, User
from app.models.students import Student, StudentProgramEnrollment
from app.models.timetable import ClassSession


def _roll(*parts: object) -> float:
    """Deterministic 0..1 value per (student, session)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:4], "big") / 2**32


@seeder("attendance", after=["timetable"])
async def seed_attendance(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401  (``is_enabled`` needs the full registry outside the API process)
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.schemas.attendance import EligibilityComputeRequest, OdDecision
    from app.services.attendance.eligibility_service import EligibilityService
    from app.services.attendance.od_service import OdService
    from app.services.attendance.summary_service import SummaryService
    from app.services.auth_service import load_principal

    inst = (await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)
    admin = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "inst.admin"))
    ).scalar_one()
    principal = await load_principal(ctx.db, admin.id)
    term = (
        await ctx.db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution_id == inst.id,
                AcademicTerm.college_id.is_(None),
                AcademicTerm.is_current.is_(True),
                AcademicTerm.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    today = today_for(inst)
    start = max(term.start_date, today - timedelta(days=42))
    summaries = SummaryService(ctx.db, principal, institution_id=inst.id)

    # ---- who is weak -------------------------------------------------------------------------------------------------
    s1_user = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "student.1"))
    ).scalar_one_or_none()
    s1_enrol = None
    if s1_user is not None:
        s1_enrol = (
            await ctx.db.execute(
                select(StudentProgramEnrollment.id)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(Student.user_id == s1_user.id, StudentProgramEnrollment.deleted_at.is_(None))
                .order_by(StudentProgramEnrollment.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    sessions = list(
        (
            await ctx.db.execute(
                select(ClassSession)
                .where(
                    ClassSession.institution_id == inst.id,
                    ClassSession.term_id == term.id,
                    ClassSession.session_date >= start,
                    ClassSession.session_date < today,
                    ClassSession.status.in_(("scheduled", "conducted")),
                )
                .order_by(ClassSession.session_date, ClassSession.start_time)
            )
        )
        .scalars()
        .all()
    )
    rosters: dict[uuid.UUID, list[uuid.UUID]] = {}
    everyone: set[uuid.UUID] = set()
    for s in sessions:
        ids = [r[0] for r in await summaries.marks.roster(s)]
        rosters[s.id] = ids
        everyone |= set(ids)
    ordered = sorted(everyone, key=lambda e: hashlib.sha256(str(e).encode()).hexdigest())
    condonable = ([s1_enrol] if s1_enrol in everyone else []) + [e for e in ordered if e != s1_enrol][:8]
    condonable = condonable[:8]
    low = [e for e in ordered if e not in condonable][:4]
    prob = {e: 0.9 for e in everyone} | {e: 0.70 for e in condonable} | {e: 0.55 for e in low}

    # ---- marks ---------------------------------------------------------------------------------------------------------
    marked = 0
    for s in sessions:
        ids = rosters.get(s.id) or []
        if not ids:
            continue
        rows = []
        for e in ids:
            r = _roll(e, s.id)
            status = "present" if r < prob[e] else "absent"
            if status == "present" and r > prob[e] - 0.03:
                status = "late"
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "institution_id": inst.id,
                    "session_id": s.id,
                    "session_date": s.session_date,
                    "student_program_enrollment_id": e,
                    "status": status,
                    "source": "manual",
                    "marked_by": None,
                }
            )
        stmt = insert(StudentClassAttendance).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["session_id", "student_program_enrollment_id", "session_date"])
        await ctx.db.execute(stmt)
        marked += len(rows)
        s.status = "conducted"
        if s.attendance_status == "not_taken":
            s.attendance_status = "taken"
            s.attendance_taken_at = func.now()
        if s.session_date <= today - timedelta(days=3) and s.attendance_status != "finalized":
            s.attendance_status, s.finalized_at = "finalized", func.now()
    await ctx.db.flush()
    ctx.count("attendance_marks", marked)
    ctx.count("sessions_marked", len(sessions))

    # ---- summaries ------------------------------------------------------------------------------------------------------
    out = await summaries.recompute_term(term.id)
    ctx.count("attendance_summaries", out["rows"])

    # ---- on duty -----------------------------------------------------------------------------------------------------------
    od_svc = OdService(ctx.db, principal, institution_id=inst.id)
    od_students = [e for e in ordered if e not in condonable and e not in low][:5]
    plan = [("approved", 6, "sports"), ("approved", 9, "nss"), ("recommended", -2, "placement"), ("requested", -4, "conference"), ("requested", -6, "ncc")]
    for enr, (status, days_ago, reason) in zip(od_students, plan, strict=False):
        exists = (
            await ctx.db.execute(select(OnDutyRequest.id).where(OnDutyRequest.student_program_enrollment_id == enr))
        ).first()
        if exists:
            continue
        frm = today - timedelta(days=days_ago)
        row = OnDutyRequest(
            institution_id=inst.id,
            student_program_enrollment_id=enr,
            from_date=frm,
            to_date=frm + timedelta(days=1),
            reason_type=reason,
            reason=f"Demo {reason} on-duty",
            status="requested" if status == "approved" else status,
        )
        ctx.db.add(row)
        await ctx.db.flush()
        if status == "approved":
            await od_svc.approve(row.id, OdDecision(comment="demo"), via_workflow=True)
        ctx.count("on_duty_requests")

    # ---- condonations ---------------------------------------------------------------------------------------------------
    cond_rows = (
        await ctx.db.execute(
            select(AttendanceSummary)
            .where(
                AttendanceSummary.student_program_enrollment_id.in_(condonable),
                AttendanceSummary.eligibility == "condonable",
            )
            .order_by(AttendanceSummary.pct)
        )
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    statuses = ["requested", "hod_recommended", "approved"]
    for summ in cond_rows:
        if len(seen) >= 3 or summ.student_program_enrollment_id in seen or summ.student_program_enrollment_id == s1_enrol:
            continue  # student.1 is left free for the verification script's own request
        seen.add(summ.student_program_enrollment_id)
        if (
            await ctx.db.execute(
                select(AttendanceCondonation.id).where(
                    AttendanceCondonation.student_program_enrollment_id == summ.student_program_enrollment_id,
                    AttendanceCondonation.term_id == term.id,
                )
            )
        ).first():
            continue
        enrol = (
            await ctx.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == summ.student_program_enrollment_id))
        ).scalar_one()
        status = statuses[len(seen) - 1]
        ctx.db.add(
            AttendanceCondonation(
                institution_id=inst.id,
                college_id=enrol.college_id,
                student_program_enrollment_id=enrol.id,
                term_id=term.id,
                offering_id=summ.offering_id,
                actual_pct=summ.pct,
                reason_type="medical",
                reason="Demo: hospitalised for a week",
                status=status,
                approved_by=admin.id if status == "approved" else None,
                approved_at=func.now() if status == "approved" else None,
            )
        )
        ctx.count("condonations")
    await ctx.db.flush()

    # ---- eligibility v1 ------------------------------------------------------------------------------------------------
    elig = EligibilityService(ctx.db, principal, institution_id=inst.id)
    if await elig.elig.term_version(term.id) == 0:
        res = await elig.run(term, EligibilityComputeRequest(), write=True)
        ctx.count("eligibility_rows", res.rows)
    await ctx.db.flush()
