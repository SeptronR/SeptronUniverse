"""Student and parent portal foundations — Prompts/07 §07.6 "Portals foundation".

``GET /students/me/dashboard`` (profile, enrolment, current term, open holds, pending undertakings, standing, quick
links) and ``GET /guardians/me/wards`` (+ ``/{student_id}/dashboard``) — a parent sees only wards with
``guardian_portal_consent`` (anything else is 404). Later phases add widgets (attendance, results, fees, hostel …) to
the same payload.
"""

import uuid

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.models.students import Student
from app.repositories.credit_transfer_repository import CreditTransferRepository
from app.schemas.students import QuickLink, StudentDashboard, WardSummary
from app.services.student_records_service import StudentRecordsService
from app.services.student_service import StudentService
from app.services.students.common import StudentServiceBase

QUICK_LINKS: tuple[tuple[str, str, str, str | None], ...] = (
    ("profile", "My profile", "/student/profile", "students.self_service_profile"),
    ("undertakings", "Undertakings", "/student/undertakings", "students.undertakings"),
    ("id_card", "ID card", "/student/id-card", "students.id_cards"),
    ("curriculum", "My curriculum", "/student/curriculum", "academics.curriculum"),
    ("credit_transfers", "Credit transfers", "/student/credit-transfers", "academics.credit_transfer_mooc"),
)


class StudentPortalService(StudentServiceBase):
    async def my_dashboard(self) -> StudentDashboard:
        student = await StudentService(self.db, self.principal, self.request, self.inst).my_student()
        return await self.dashboard(student)

    async def dashboard(self, student: Student, *, ward: bool = False) -> StudentDashboard:
        detail = await StudentService(self.db, self.principal, self.request, self.inst).detail(student)
        records = StudentRecordsService(self.db, self.principal, self.request, self.inst)
        pending = await records.pending(student)
        ct_pending = 0
        if detail.enrollment is not None:
            ct_pending = await CreditTransferRepository(self.db).pending_count(detail.enrollment.id)
        links = []
        for key, label, route, feature in QUICK_LINKS:
            if feature and not await is_enabled(self.inst, feature):
                continue
            links.append(
                QuickLink(
                    key=key,
                    label=label,
                    route=route.replace("/student", "/parent", 1) if ward else route,
                    feature=feature,
                )
            )
        return StudentDashboard(
            student=detail,
            enrollment=detail.enrollment,
            current_term=detail.current_term,
            holds=detail.holds,
            undertakings_pending=pending,
            standing=detail.enrollment.academic_standing if detail.enrollment else None,
            credit_transfers_pending=ct_pending,
            quick_links=[] if ward else links,
        )

    async def wards(self) -> list[WardSummary]:
        pairs = await self.guardians.wards_of(self.principal.id)
        items = await self.list_items([s for s, _ in pairs], mask=False)
        relation = {s.id: g.relation for s, g in pairs}
        return [
            WardSummary(
                student_id=i.id,
                registration_number=i.registration_number,
                name=i.full_name,
                relation=relation.get(i.id),
                program_code=i.program_code,
                batch_code=i.batch_code,
                term_number=i.term_number,
                status=i.status,
                academic_standing=i.academic_standing,
                open_holds=i.open_holds,
                photo_url=i.photo_url,
            )
            for i in items
        ]

    async def ward_dashboard(self, student_id: uuid.UUID) -> StudentDashboard:
        if student_id not in await self.guardians.ward_ids(self.principal.id):
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        student = await self.students.by_id(student_id)
        if student is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        return await self.dashboard(student, ward=True)
