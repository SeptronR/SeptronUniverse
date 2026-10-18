"""Grade cards — Prompts/15 §15.6 ``grade_card_service``.

One card per published term result (version): document number from the ``grade_card`` sequence (fallback
``GC/{yyyy}/{nnnnnn}``), a random QR token (``/verify/{token}`` answers the hash + SGPA summary; a superseded version
says so), the PDF (institution header, grades per course incl. ``W/AB/WH/MP/I``, SGPA / CGPA, grace footnote per
``print_grace_note``) stored under ``grade-cards/``. Re-publication generates a new card; old cards stay (superseded).
Platform default template until Phase 26's document templates.
"""

import secrets
import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm
from app.models.curriculum import Course
from app.models.results import GradeCard, StudentCourseResult, StudentTermResult
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.fee_scope import own_enrollment_ids
from app.repositories.result_scope import enrollment_predicate
from app.schemas.results import GradeCardResponse, ResultVerifyResponse
from app.services.exams.common import now_utc
from app.services.results.result_service import ResultBase


class GradeCardService(ResultBase):
    async def _number(self, college_id: uuid.UUID | None) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next("grade_card", college_id)
            ).rendered[:40]
        except APIError:
            n = (
                await self.db.execute(
                    select(func.count()).select_from(GradeCard).where(GradeCard.institution_id == self.inst)
                )
            ).scalar_one()
            return f"GC/{now_utc():%Y}/{int(n) + 1:06d}"

    async def _pdf(self, t: StudentTermResult, rec: StudentTermRecord, st: Student, number: str) -> bytes:
        from app.utils.pdf import render_pdf

        inst = await self.institution()
        term = (await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == rec.term_id))).scalar_one_or_none()
        rows = (
            await self.db.execute(
                select(StudentCourseResult, Course)
                .join(Course, Course.id == StudentCourseResult.course_id)
                .where(
                    StudentCourseResult.student_program_enrollment_id == rec.student_program_enrollment_id,
                    StudentCourseResult.term_id == rec.term_id,
                    StudentCourseResult.status == "published",
                    StudentCourseResult.is_current.is_(True),
                )
                .order_by(Course.code)
            )
        ).all()
        name = " ".join(x for x in (st.first_name, st.last_name) if x)
        lines = [
            f"{inst.name} — Grade card",
            f"No. {number}  ·  {name}  ·  Reg. {st.registration_number}",
            f"Term {rec.term_number}{' (' + term.name + ')' if term else ''}",
            "",
        ]
        grace = False
        body = ""
        for r, c in rows:
            g = r.letter_grade or r.result_status.upper()
            star = "*" if r.grace_marks and r.grace_marks > 0 else ""
            grace = grace or bool(star)
            lines.append(f"{c.code:<12} {c.title[:40]:<40} {float(r.credits):>4} {g}{star} {r.grade_point or ''}")
            body += (
                f"<tr><td>{c.code}</td><td>{c.title}</td><td>{float(r.credits)}</td>"
                f"<td>{g}{star}</td><td>{r.grade_point or ''}</td></tr>"
            )
        lines += [
            "",
            f"SGPA {t.sgpa or '—'}   CGPA {t.cgpa or '—'}   Credits {t.credits_earned}/{t.credits_registered}"
            f"   Class {t.result_class or '—'}",
        ]
        rules = {}
        try:
            from app.services.academics.rules import RulesResolver

            enr = (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.id == rec.student_program_enrollment_id
                    )
                )
            ).scalar_one()
            rules = await RulesResolver(self.db).for_program_regulation(enr.program_regulation_id)
        except APIError:
            pass
        if grace and rules.get("print_grace_note", True):
            lines.append("* grace marks awarded as per regulation")
        lines.append(f"Verify: /verify/<QR>  ·  version {t.version}")
        html = (
            f"<html><body><h2>{inst.name}</h2><h3>Grade card {number}</h3><p>{name} · {st.registration_number} · "
            f"Term {rec.term_number}</p><table border='1' cellpadding='4'><tr><th>Code</th><th>Course</th><th>Credits</th>"
            f"<th>Grade</th><th>GP</th></tr>{body}</table><p>SGPA {t.sgpa or '—'} · CGPA {t.cgpa or '—'} · "
            f"Class {t.result_class or '—'}</p></body></html>"
        )
        return render_pdf(html, lines, title=f"Grade card {number}")

    async def generate_for_run(self, run_id: uuid.UUID, progress: Any = None) -> dict[str, int]:
        from app.core.files import build_key, storage

        terms = (
            await self.db.execute(
                select(StudentTermResult, StudentTermRecord, Student)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == StudentTermRecord.student_program_enrollment_id,
                )
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(
                    StudentTermResult.run_id == run_id,
                    StudentTermResult.status == "published",
                    StudentTermResult.institution_id == self.inst,
                )
            )
        ).all()
        have = set(
            (
                await self.db.execute(
                    select(GradeCard.student_term_result_id).where(
                        GradeCard.student_term_result_id.in_([t.id for t, _, _ in terms] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        )
        made = 0
        for i, (t, rec, st) in enumerate(terms, start=1):
            if t.id in have:
                continue
            number = await self._number(st.college_id)
            pdf = await self._pdf(t, rec, st, number)
            key = build_key(self.inst, "grade-cards", f"{number.replace('/', '-')}-v{t.version}.pdf")
            await storage.put(key, pdf, "application/pdf")
            self.db.add(
                GradeCard(
                    institution_id=self.inst,
                    student_term_result_id=t.id,
                    document_number=number,
                    pdf_url=key,
                    qr_token=secrets.token_hex(24),
                    version=t.version,
                )
            )
            made += 1
            if progress and i % 50 == 0:
                await progress(int(100 * i / len(terms)), f"{i} grade cards")
        await self.db.flush()
        if made:
            await self._emit("grade_card.generated", {"run_id": str(run_id), "count": made}, "result_run", run_id)
        return {"generated": made, "existing": len(have)}

    async def _cards(self, pred: Any) -> list[GradeCardResponse]:
        rows = (
            await self.db.execute(
                select(GradeCard, StudentTermResult, StudentTermRecord.term_number)
                .join(StudentTermResult, StudentTermResult.id == GradeCard.student_term_result_id)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .where(GradeCard.institution_id == self.inst, pred)
                .order_by(StudentTermRecord.term_number, GradeCard.version)
            )
        ).all()
        out = []
        for g, t, tn in rows:
            o = GradeCardResponse.model_validate(g, from_attributes=True)
            o.superseded, o.term_number, o.sgpa = not t.is_current or t.status == "superseded", tn, t.sgpa
            out.append(o)
        return out

    async def student_cards(self, student_id: uuid.UUID) -> list[GradeCardResponse]:
        enr = select(StudentProgramEnrollment.id).where(
            StudentProgramEnrollment.student_id == student_id,
            enrollment_predicate(self.principal, StudentProgramEnrollment.id),
        )
        return await self._cards(StudentTermRecord.student_program_enrollment_id.in_(enr))

    async def my_cards(self, term_id: uuid.UUID | None) -> list[GradeCardResponse]:
        pred: Any = StudentTermRecord.student_program_enrollment_id.in_(
            own_enrollment_ids(self.principal, advisees=False)
        )
        if term_id:
            pred = pred & (StudentTermRecord.term_id == term_id)
        return await self._cards(pred)

    async def pdf(self, card_id: uuid.UUID) -> tuple[bytes, str]:
        from app.core.files import storage

        g = (
            await self.db.execute(
                select(GradeCard).where(GradeCard.id == card_id, GradeCard.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if g is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Grade card not found")
        enr = (
            await self.db.execute(
                select(StudentTermRecord.student_program_enrollment_id)
                .join(StudentTermResult, StudentTermResult.student_term_record_id == StudentTermRecord.id)
                .where(StudentTermResult.id == g.student_term_result_id)
            )
        ).scalar_one()
        visible = (
            await self.db.execute(
                select(StudentProgramEnrollment.id).where(
                    StudentProgramEnrollment.id == enr,
                    enrollment_predicate(self.principal, StudentProgramEnrollment.id),
                )
            )
        ).first()
        if visible is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Grade card not found")
        data = await storage.get(g.pdf_url) if g.pdf_url else None
        if not data:
            raise APIError(404, ErrorCode.NOT_FOUND, "The grade card file is not available yet")
        return data, g.document_number.replace("/", "-")


async def verify_grade_card(token: str) -> ResultVerifyResponse | None:
    """``/verify/{token}`` for grade-card QR tokens (platform session — the token names the tenant)."""
    from app.db.session import PlatformSessionLocal
    from app.models.platform import Institution

    if len(token) != 48 or not all(c in "0123456789abcdef" for c in token):
        return None
    async with PlatformSessionLocal() as db:
        row = (
            await db.execute(
                select(GradeCard, StudentTermResult, StudentTermRecord.term_number, Student, Institution.name)
                .join(StudentTermResult, StudentTermResult.id == GradeCard.student_term_result_id)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == StudentTermRecord.student_program_enrollment_id,
                )
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .join(Institution, Institution.id == GradeCard.institution_id)
                .where(GradeCard.qr_token == token)
            )
        ).first()
        if row is None:
            return ResultVerifyResponse(valid=False, message="Unknown grade card")
        g, t, tn, st, inst = row
        hashes = (
            (
                await db.execute(
                    select(StudentCourseResult.hash)
                    .where(StudentCourseResult.run_id == t.run_id)
                    .where(StudentCourseResult.student_program_enrollment_id == StudentProgramEnrollment.id)
                    .where(StudentProgramEnrollment.student_id == st.id)
                    .order_by(StudentCourseResult.hash)
                )
            )
            .scalars()
            .all()
        )
    from app.services.results.compute import checksum

    superseded = not t.is_current or t.status == "superseded"
    return ResultVerifyResponse(
        valid=t.status in ("published", "superseded"),
        document_number=g.document_number,
        holder_name=" ".join(x for x in (st.first_name, st.last_name) if x),
        registration_number=st.registration_number,
        term_number=tn,
        sgpa=t.sgpa,
        cgpa=t.cgpa,
        hash=checksum([h for h in hashes if h]),
        superseded=superseded,
        institution=inst,
        message="Superseded by a revised grade card" if superseded else None,
    )
