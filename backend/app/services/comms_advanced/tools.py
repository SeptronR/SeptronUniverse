"""Read-only tools shared by the WhatsApp bot and the AI assistant — Prompts/24 §24.6.

Every tool runs **under the caller's principal**: the student set is ``own_student_ids(principal, wards=True)`` (own or
consented wards), department aggregates need ``attendance:view_all`` with a department scope, fee collection needs
``fees:view_all``. Tools never write; they return ``(text, data)`` where ``data`` carries the citation.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.fee_scope import own_student_ids


async def students_of(db: Any, principal: Any) -> list[Student]:
    return list(
        (
            await db.execute(
                select(Student)
                .where(Student.id.in_(own_student_ids(principal, wards=True, advisees=False)))
                .order_by(Student.first_name)
            )
        ).scalars()
    )


async def enrolment_of(db: Any, student_id: uuid.UUID) -> StudentProgramEnrollment | None:
    row: StudentProgramEnrollment | None = (
        await db.execute(
            select(StudentProgramEnrollment)
            .where(StudentProgramEnrollment.student_id == student_id, StudentProgramEnrollment.status == "active")
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def attendance(
    db: Any, principal: Any, student: Student, course_hint: str | None = None
) -> tuple[str, dict[str, Any]]:
    from app.models.attendance import AttendanceSummary
    from app.models.curriculum import Course
    from app.models.offerings import CourseOffering

    e = await enrolment_of(db, student.id)
    if e is None:
        return f"No active enrolment for {student.full_name}.", {"tool": "my_attendance", "rows": 0}
    rows = (
        await db.execute(
            select(
                Course.code,
                Course.title,
                AttendanceSummary.pct,
                AttendanceSummary.present,
                AttendanceSummary.total_sessions,
            )
            .join(CourseOffering, CourseOffering.id == AttendanceSummary.offering_id)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(AttendanceSummary.student_program_enrollment_id == e.id)
            .order_by(Course.code)
        )
    ).all()
    if course_hint:
        h = course_hint.lower()
        rows = [r for r in rows if h in r[0].lower() or h in r[1].lower()] or rows
    if not rows:
        return f"No attendance has been recorded yet for {student.full_name}.", {"tool": "my_attendance", "rows": 0}
    lines = [f"Attendance — {student.full_name}"]
    for code, title, pct, present, total in rows[:12]:
        need = (
            max(0, int((Decimal("0.75") * total - present) / Decimal("0.25")) + 1) if total and Decimal(pct) < 75 else 0
        )  # noqa: PLR2004
        lines.append(
            f"• {code} {title[:28]}: {float(pct):.1f}% ({present}/{total}){f' — attend {need} more in a row to reach 75%' if need else ''}"
        )
    return "\n".join(lines), {"tool": "my_attendance", "rows": len(rows)}


async def dues(db: Any, principal: Any, student: Student) -> tuple[str, dict[str, Any]]:
    from app.models.fees import FeeInvoice

    e = await enrolment_of(db, student.id)
    q = select(FeeInvoice).where(
        FeeInvoice.balance_paise > 0, FeeInvoice.status.notin_(("paid", "cancelled", "waived"))
    )
    q = q.where(FeeInvoice.student_program_enrollment_id == e.id) if e else q.where(FeeInvoice.payer_id == student.id)
    rows = list((await db.execute(q.order_by(FeeInvoice.due_date))).scalars())
    if not rows:
        return f"No dues for {student.full_name}. 🎉", {"tool": "my_dues", "rows": 0}
    total = sum(int(r.balance_paise) for r in rows)
    lines = [f"Dues — {student.full_name}: ₹{total / 100:,.2f}"]
    lines += [
        f"• {r.description or r.invoice_number}: ₹{r.balance_paise / 100:,.2f} (due {r.due_date or '—'})"
        for r in rows[:8]
    ]
    lines.append(f"Pay online: {settings.frontend_url}/student/fees")
    return "\n".join(lines), {"tool": "my_dues", "rows": len(rows), "total_paise": total}


async def timetable(db: Any, principal: Any, student: Student, on: date) -> tuple[str, dict[str, Any]]:
    from app.models.attendance import AttendanceSummary
    from app.models.curriculum import Course
    from app.models.offerings import CourseOffering
    from app.models.timetable import TimeSlot, TimetableEntry

    e = await enrolment_of(db, student.id)
    if e is None:
        return "No active enrolment.", {"tool": "my_timetable", "rows": 0}
    offerings = select(AttendanceSummary.offering_id).where(AttendanceSummary.student_program_enrollment_id == e.id)
    rows = (
        await db.execute(
            select(TimeSlot.start_time, TimeSlot.end_time, Course.code, Course.title)
            .join(TimetableEntry, TimetableEntry.time_slot_id == TimeSlot.id)
            .join(CourseOffering, CourseOffering.id == TimetableEntry.offering_id)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(
                TimetableEntry.offering_id.in_(offerings),
                TimetableEntry.day_of_week == on.isoweekday(),
                TimetableEntry.is_active.is_(True),
            )
            .order_by(TimeSlot.start_time)
        )
    ).all()
    if not rows:
        return f"No classes scheduled on {on:%A %d %b}.", {"tool": "my_timetable", "rows": 0}
    return "\n".join(
        [f"Classes on {on:%A %d %b}:"] + [f"• {s:%H:%M}–{t:%H:%M} {c} {ti[:30]}" for s, t, c, ti in rows]
    ), {"tool": "my_timetable", "rows": len(rows)}


async def results(db: Any, principal: Any, student: Student) -> tuple[str, dict[str, Any]]:
    from app.models.results import StudentTermResult
    from app.models.students import StudentTermRecord

    e = await enrolment_of(db, student.id)
    if e is None:
        return "No active enrolment.", {"tool": "my_results", "rows": 0}
    r = (
        await db.execute(
            select(StudentTermResult, StudentTermRecord.term_number)
            .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
            .where(
                StudentTermRecord.student_program_enrollment_id == e.id,
                StudentTermResult.is_current.is_(True),
                StudentTermResult.published_at.is_not(None),
            )
            .order_by(StudentTermRecord.term_number.desc())
            .limit(1)
        )
    ).first()
    if r is None:
        return "No results have been published yet.", {"tool": "my_results", "rows": 0}
    res, term = r
    return (
        f"Term {term} result — SGPA {res.sgpa or '—'}, CGPA {res.cgpa or '—'}, backlogs {res.backlog_count}. Details: {settings.frontend_url}/student/results",
        {"tool": "my_results", "rows": 1},
    )


async def outpass(db: Any, principal: Any, student: Student) -> tuple[str, dict[str, Any]]:
    try:
        from app.models.hostel import HostelLeave
    except ImportError:  # pragma: no cover
        return "Hostel module not available.", {"tool": "outpass_status", "rows": 0}
    e = await enrolment_of(db, student.id)
    row = (
        await db.execute(
            select(HostelLeave)
            .where(HostelLeave.student_program_enrollment_id == (e.id if e else None))
            .order_by(HostelLeave.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return "No out-pass / leave requests.", {"tool": "outpass_status", "rows": 0}
    return (
        f"Latest {row.leave_type.replace('_', ' ')}: {row.status} ({row.from_at:%d %b %H:%M} → {row.to_at:%d %b %H:%M}).",
        {"tool": "outpass_status", "rows": 1},
    )


async def receipt(db: Any, principal: Any, student: Student) -> tuple[str, dict[str, Any]]:
    from app.models.fees import FeeInvoice, FeePayment

    e = await enrolment_of(db, student.id)
    row = (
        await db.execute(
            select(FeePayment)
            .join(FeeInvoice, FeeInvoice.id == FeePayment.invoice_id)
            .where(FeeInvoice.student_program_enrollment_id == (e.id if e else None), FeePayment.status == "success")
            .order_by(FeePayment.payment_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return "No fee receipts yet.", {"tool": "fee_receipt", "rows": 0}
    return (
        f"Receipt {row.receipt_number}: ₹{row.amount_paise / 100:,.2f} on {row.payment_date:%d %b %Y}. Download: {settings.frontend_url}/student/fees",
        {"tool": "fee_receipt", "rows": 1},
    )


async def department_attendance(db: Any, principal: Any, below: float = 75.0) -> tuple[str, dict[str, Any]]:
    from app.models.attendance import AttendanceSummary

    depts = [sid for t, sid in getattr(principal, "scopes", []) if t == "department" and sid]
    if not (principal.has("attendance", "view_all") and depts):
        return "You can only ask about your own attendance.", {
            "tool": "department_attendance",
            "rows": 0,
            "denied": True,
        }
    n = (
        await db.execute(
            select(func.count(func.distinct(AttendanceSummary.student_program_enrollment_id)))
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == AttendanceSummary.student_program_enrollment_id
            )
            .where(StudentProgramEnrollment.department_id.in_(depts), AttendanceSummary.pct < Decimal(str(below)))
        )
    ).scalar_one()
    return (
        f"{n} student(s) in your department are below {below:.0f}% in at least one course. List: {settings.frontend_url}/admin/attendance/eligibility",
        {"tool": "department_attendance", "rows": int(n)},
    )


async def fee_collection_today(db: Any, principal: Any, on: date) -> tuple[str, dict[str, Any]]:
    from app.models.fees import FeePayment

    if not principal.has("fees", "view_all"):
        return "Fee collection figures need accounts access.", {"tool": "fee_collection_today", "denied": True}
    total, n = (
        await db.execute(
            select(func.coalesce(func.sum(FeePayment.amount_paise), 0), func.count()).where(
                FeePayment.payment_date == on, FeePayment.status == "success"
            )
        )
    ).one()
    return f"Collected today: ₹{int(total) / 100:,.2f} across {n} receipt(s).", {
        "tool": "fee_collection_today",
        "rows": int(n),
    }


async def faq(db: Any, query: str) -> tuple[str, dict[str, Any]]:
    from app.models.platform import HelpArticle

    words = [w for w in query.lower().split() if len(w) > 3][:4]  # noqa: PLR2004
    q = select(HelpArticle).where(HelpArticle.is_published.is_(True))
    for w in words:
        q = q.where(HelpArticle.title.ilike(f"%{w}%") | HelpArticle.body.ilike(f"%{w}%"))
    hit = (await db.execute(q.limit(1))).scalar_one_or_none()
    if hit is None:
        return "", {"tool": "faq", "rows": 0}
    return f"{hit.title}: {hit.body[:400]}", {"tool": "faq", "rows": 1, "slug": hit.slug}


def today_now() -> datetime:
    return datetime.now()
