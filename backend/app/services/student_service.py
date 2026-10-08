"""Student master — Prompts/07 §07.6 ``student_service.py``.

Rules
1. **Create** (``source = manual | import | admission``; Phase 08 calls it with ``admission``): the plan's student seat
   limit is checked first (``403 RULE_VIOLATION`` / ``SEAT_LIMIT``); category and quota must be pack codes, APAAR /
   ABC ids pass the pack check digit (and are unique), Aadhaar its Verhoeff check; the programme fixes the college and
   department (a college-scoped office creates only in its college). The batch is the given one or the
   (college, programme, admission year, entry type) batch — **created when missing** with the active regulation whose
   ``effective_from_admission_year`` ≤ the admission year. ``registration_number`` comes from the per-programme-year
   sequence ``regno:{yyyy}:{programme}`` (created on first use from the institution's ``register_no`` pattern when it
   carries ``{prog_code}``, else ``{college_code}{yy}{prog_code}{seq:3}``) unless supplied (affiliating university —
   unique, 409). A student user (username = registration number, temporary password, role ``student``,
   ``must_change_password``), the enrolment pinned to the programme-regulation, the term record for the college's
   current term (section, roll number), guardians — with parent-portal users created or **reused by phone / e-mail
   across siblings** when ``students.guardians_portal`` is on — and the ``academic`` / ``communication`` consent records
   are written; ``student.created`` is emitted (search index; Phases 12/18/19 subscribe).
2. **Update** (registrar) with the optimistic ``version``; PII (Aadhaar, bank details, APAAR/ABC) is written with
   ``students:manage`` and read with ``students:view_pii`` (or on the own record). A student edits only
   ``StudentSelfUpdate`` (setting ``students.self_service_fields``); extra keys → 422.
3. **Status machine** — ``provisional → admitted → active`` (Phase 09 activates on the first confirmed registration),
   ``on_break``, ``detained``, ``dropped_out``, ``expelled``, ``deceased`` through ``POST /students/{id}/status``;
   ``exited`` (NEP exit), ``transferred`` (transfer completion), ``graduated`` (Phase 18) and ``alumni`` (Phase 29) only
   through their own flows. The open enrolment follows (``break`` / ``detained`` / ``withdrawn`` / ``expelled``);
   terminal states deactivate the user and revoke its sessions (graduates / alumni keep their account).
4. **Stats** by status / programme / batch / category / gender / standing over the caller's visible students.
5. **Bulk import** (CSV / XLSX template, dry run = validation report, apply = job ``students.bulk_import`` with one
   savepoint per row and a partial-success report) and **XLSX export** (PII masked unless ``students:view_pii``).
"""

import csv
import io
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core import jobs
from app.core.authz.masking import mask_pii, mask_value, may_unmask
from app.core.errors import APIError, ErrorCode
from app.core.security import generate_temp_password, hash_password
from app.enums.students import TERMINAL_STATUSES
from app.models.academic import Batch, BatchSection, Program, ProgramRegulation, Regulation
from app.models.platform import User, UserRole
from app.models.students import Student, StudentGuardian, StudentProgramEnrollment
from app.repositories.consent_repository import ConsentRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.sequence_repository import SequenceRepository, render
from app.repositories.session_repository import SessionRepository
from app.repositories.student_scope import student_visibility
from app.schemas.students import (
    BulkImportFailure,
    BulkImportResult,
    GuardianIn,
    GuardianOut,
    StatBucket,
    StatusChangeRequest,
    StudentCreate,
    StudentCreateResult,
    StudentDetailResponse,
    StudentListItem,
    StudentSelfUpdate,
    StudentStats,
    StudentUpdate,
)
from app.services.institution.context import check_college_writable
from app.services.students.common import StudentServiceBase, snap
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

STUDENT_KEYS = (
    "registration_number",
    "first_name",
    "last_name",
    "college_id",
    "status",
    "category",
    "gender",
    "dob",
    "admission_quota",
    "admission_date",
    "apaar_id",
    "guardian_portal_consent",
)
PII_FIELDS = {"aadhaar", "bank_details", "apaar_id", "abc_id"}
ENCRYPTED = {"aadhaar": "aadhaar_encrypted", "bank_details": "bank_details_encrypted"}
TEN_YEARS = 10 * 365 * 24 * 3600
TRANSITIONS: dict[str, set[str]] = {
    "provisional": {"admitted", "active", "dropped_out", "deceased"},
    "admitted": {"active", "on_break", "dropped_out", "deceased"},
    "active": {"on_break", "detained", "dropped_out", "expelled", "deceased"},
    "on_break": {"active", "dropped_out", "deceased"},
    "detained": {"active", "on_break", "dropped_out", "expelled", "deceased"},
    "graduated": set(),
    "alumni": set(),
    "dropped_out": set(),
    "transferred": set(),
    "exited": set(),
    "expelled": set(),
    "deceased": set(),
}
ENROLLMENT_STATUS_FOR = {
    "active": "active",
    "admitted": "active",
    "provisional": "active",
    "on_break": "break",
    "detained": "detained",
    "dropped_out": "withdrawn",
    "deceased": "withdrawn",
    "expelled": "expelled",
    "transferred": "transferred",
}
IMPORT_COLUMNS = (
    "registration_number",
    "first_name",
    "last_name",
    "dob",
    "gender",
    "category",
    "quota",
    "program_code",
    "batch_code",
    "section",
    "entry_type",
    "phone",
    "email",
    "guardian_name",
    "guardian_relation",
    "guardian_phone",
    "apaar_id",
    "admission_date",
)
EXPORT_HEADER = [
    "Registration no.",
    "Name",
    "College",
    "Department",
    "Programme",
    "Batch",
    "Section",
    "Term",
    "Status",
    "Standing",
    "Category",
    "Gender",
    "Phone",
    "E-mail",
    "APAAR id",
]


@dataclass
class CreatedStudent:
    student: Student
    enrollment: StudentProgramEnrollment
    user: User | None = None
    temp_password: str | None = None
    guardian_accounts: list[dict[str, Any]] = dc_field(default_factory=list)


def _compact(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", code).upper()


def _phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    return digits[:20] or None


class StudentService(StudentServiceBase):
    # ---- reads ------------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, **filters: Any
    ) -> tuple[list[StudentListItem], PaginationMeta, VisibilityMeta]:
        stmt = self.students.filtered(scope=scope, **filters)
        if not params.sort:
            params = params.model_copy(update={"sort": "registration_number"})
        rows, pagination = await self.students.paginate(stmt, params)
        return await self.list_items(rows), pagination, student_visibility(self.principal)

    async def get(self, student_id: uuid.UUID) -> StudentDetailResponse:
        return await self.detail(await self.students.get_visible(student_id))

    async def my_student(self) -> Student:
        row = await self.students.by_user(self.principal.id)
        if row is None:
            raise APIError(
                404, ErrorCode.NOT_FOUND, "Your account is not linked to a student record", {"reason": "no_student"}
            )
        return row

    async def me(self) -> StudentDetailResponse:
        return await self.detail(await self.my_student())

    async def detail(self, s: Student) -> StudentDetailResponse:
        from app.services.student_records_service import StudentRecordsService

        base = (await self.list_items([s], mask=False))[0]
        r = StudentDetailResponse(**base.model_dump())
        for key in (
            "middle_name",
            "dob",
            "blood_group",
            "sub_category",
            "is_pwd",
            "pwd_pct",
            "pwd_type",
            "is_minority",
            "minority_type",
            "religion",
            "nationality",
            "mother_tongue",
            "domicile_state",
            "permanent_address",
            "enrolment_number",
            "is_international",
            "passport",
            "visa",
            "frro",
            "guardian_portal_consent",
            "admission_quota",
            "admission_mode",
            "admission_date",
            "user_id",
            "version",
            "created_at",
            "abc_id",
        ):
            setattr(r, key, getattr(s, key))
        address = dict(s.current_address or {})
        r.emergency_contact = address.pop("emergency_contact", None)
        r.current_address = address or None
        r.aadhaar, r.bank_details = s.aadhaar_encrypted, s.bank_details_encrypted
        r.is_adult = await self.is_adult(s.dob)
        if s.user_id:
            user = (await self.students.users([s.user_id])).get(s.user_id)
            r.username = user.username if user else None
        enrolment = await self.enrollments.current(s.id)
        if enrolment is not None:
            r.enrollment = (await self.enrollment_responses([enrolment]))[0]
            latest = (await self.terms.latest_for([enrolment.id])).get(enrolment.id)
            if latest is not None:
                r.current_term = (await self.term_record_responses([latest]))[0]
            r.holds = await self.hold_responses(await self.holds.for_enrollments([enrolment.id], open_only=True))
        records = StudentRecordsService(self.db, self.principal, self.request, self.inst)
        r.guardians = await records.guardian_responses(s)
        if self.can("students", "view") or self.can("students", "self"):
            r.documents = await records.document_responses(s)
        r.undertakings = await records.undertaking_status(s)
        r.allowed_transitions = sorted(TRANSITIONS.get(s.status, set())) if self.can("students", "update") else []
        if r.is_self or r.is_ward:
            # own / ward record: contact data unmasked, identity numbers only for the student themself
            if not r.is_self and not may_unmask(self.principal, "students"):
                r.aadhaar = None if r.aadhaar is None else "********"
                r.bank_details = None if r.bank_details is None else "********"
            return r
        masked: StudentDetailResponse = mask_pii(r, self.principal, "students")
        if masked.emergency_contact and not may_unmask(self.principal, "students"):
            # the emergency contact lives in a JSON column: mask its phone like the student's own
            contact = {**masked.emergency_contact, "phone": mask_value(masked.emergency_contact.get("phone"), "phone")}
            masked = masked.model_copy(update={"emergency_contact": contact})
        return masked

    # ---- rule 1: create ---------------------------------------------------------------------------------------------
    async def create(
        self,
        body: StudentCreate,
        source: str = "manual",
        *,
        audit: bool = True,
        password_hash: str | None = None,
        seat_check: bool = True,
        notify: bool = True,
    ) -> StudentCreateResult:
        created = await self.create_record(
            body, source, audit=audit, password_hash=password_hash, seat_check=seat_check, notify=notify
        )
        return StudentCreateResult(
            student=await self.detail(created.student),
            username=created.user.username if created.user else None,
            temp_password=created.temp_password,
            guardian_accounts=created.guardian_accounts,
        )

    async def create_record(
        self,
        body: StudentCreate,
        source: str = "manual",
        *,
        audit: bool = True,
        password_hash: str | None = None,
        seat_check: bool = True,
        notify: bool = True,
    ) -> "CreatedStudent":
        """Rule 1 without the response decoration (bulk import, the demo seeder and Phase 08 admissions)."""
        from app.services.entitlement_service import EntitlementService

        if seat_check:
            await EntitlementService(self.db, self.principal).enforce_seat_limit("student", institution_id=self.inst)
        pack = await self.pack()
        category = self._category(body.category, pack)
        quota = self._quota(body.admission_quota, pack)
        await self._check_ids(pack, body.apaar_id, body.abc_id, body.aadhaar)
        program = await self._program(body.program_id)
        if self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            check_college_writable(self.principal, program.college_id)
        today = await self.today()
        admission_date = body.admission_date or today
        batch = await self._batch(body, program, admission_date)
        pr_id = body.program_regulation_id or batch.program_regulation_id
        await self._check_binding(pr_id, program.id)
        section = await self._section(batch, body.section_id, body.section)
        registration_number = await self._registration_number(body.registration_number, program, batch)

        user, temp_password = (None, None)
        if body.create_user:
            user, temp_password = await self._student_user(registration_number, body, password_hash)
        address = dict(body.current_address or {})
        if body.emergency_contact is not None:
            address["emergency_contact"] = body.emergency_contact.model_dump()
        student = Student(
            institution_id=self.inst,
            college_id=program.college_id,
            user_id=user.id if user else None,
            registration_number=registration_number,
            enrolment_number=body.enrolment_number,
            apaar_id=body.apaar_id,
            abc_id=body.abc_id,
            aadhaar_encrypted=re.sub(r"\s", "", body.aadhaar) if body.aadhaar else None,
            first_name=body.first_name.strip(),
            middle_name=body.middle_name,
            last_name=body.last_name,
            dob=body.dob,
            gender=body.gender.value,
            blood_group=body.blood_group,
            category=category,
            sub_category=body.sub_category,
            is_pwd=body.is_pwd,
            pwd_pct=body.pwd_pct,
            pwd_type=body.pwd_type,
            is_minority=body.is_minority,
            minority_type=body.minority_type,
            religion=body.religion,
            nationality=body.nationality,
            is_international=body.is_international,
            passport=body.passport,
            visa=body.visa,
            frro=body.frro,
            domicile_state=body.domicile_state,
            mother_tongue=body.mother_tongue,
            phone=_phone(body.phone),
            email=str(body.email) if body.email else None,
            permanent_address=body.permanent_address,
            current_address=address or None,
            bank_details_encrypted=body.bank_details.model_dump_json() if body.bank_details else None,
            admission_quota=quota,
            admission_mode=body.admission_mode or ("admission" if source == "admission" else None),
            admission_date=admission_date,
            status=body.status,
            created_by=self.actor_id,
        )
        self.db.add(student)
        await self.db.flush()
        entry_term = body.entry_term_number or batch.current_term_number or 1
        enrolment = StudentProgramEnrollment(
            institution_id=self.inst,
            college_id=program.college_id,
            student_id=student.id,
            program_id=program.id,
            batch_id=batch.id,
            program_regulation_id=pr_id,
            department_id=program.department_id,
            admission_date=admission_date,
            entry_type=body.entry_type.value,
            entry_term_number=entry_term,
            specialization=body.specialization,
            minor_program_id=body.minor_program_id,
            is_honours=body.is_honours,
            expected_exit_term=program.total_terms,
            status="active",
            created_by=self.actor_id,
        )
        self.db.add(enrolment)
        await self.db.flush()
        term = await self.current_term(program.college_id)
        if term is not None:
            await self.terms.get_or_create(
                enrolment.id,
                term.id,
                max(entry_term, batch.current_term_number or 1),
                section_id=section.id if section else None,
                roll_number=body.roll_number,
            )
        guardian_accounts = [await self._add_guardian(student, g, notify=notify) for g in body.guardians]
        if user is not None:
            await self._consents(user.id)
        if audit:
            await self._audit(
                "create",
                "student",
                student.id,
                None,
                {
                    **snap(student, STUDENT_KEYS),
                    "source": source,
                    "batch": batch.code,
                    "enrollment_id": str(enrolment.id),
                },
            )
        await self._emit(
            "student.created",
            {
                "student_id": str(student.id),
                "registration_number": registration_number,
                "program_id": str(program.id),
                "batch_id": str(batch.id),
                "enrollment_id": str(enrolment.id),
                "college_id": str(program.college_id),
                "source": source,
            },
            "student",
            student.id,
        )
        if user is not None and notify:
            await self._notify(
                "student.welcome",
                [user.id],
                {
                    "name": student.full_name,
                    "institution_name": (await self.institution()).name,
                    "registration_number": registration_number,
                    "username": user.username,
                },
            )
        return CreatedStudent(
            student=student,
            enrollment=enrolment,
            user=user,
            temp_password=temp_password,
            guardian_accounts=[a for a in guardian_accounts if a],
        )

    def _category(self, raw: str | None, pack: Any) -> str | None:
        if not raw:
            return None
        codes: dict[str, str] = {c.code.upper(): c.code for c in pack.categories}
        key = raw.strip().upper().replace("_", "-")
        if key not in codes:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown category {raw!r} for the {pack.code} pack",
                {"field": "category", "allowed": sorted(codes.values())},
            )
        return codes[key]

    def _quota(self, raw: str | None, pack: Any) -> str | None:
        if not raw:
            return None
        codes: dict[str, str] = {q.code.upper(): q.code for q in pack.quotas}
        key = raw.strip().upper()
        if key not in codes:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown quota {raw!r} for the {pack.code} pack",
                {"field": "admission_quota", "allowed": sorted(codes.values())},
            )
        return codes[key]

    async def _check_ids(
        self, pack: Any, apaar: str | None, abc: str | None, aadhaar: str | None, exclude: uuid.UUID | None = None
    ) -> None:
        for field, value in (("apaar_id", apaar), ("abc_id", abc), ("aadhaar", aadhaar)):
            if not value:
                continue
            check = pack.validators.get(field.split("_")[0])
            if check is not None and not check(value):
                raise APIError(422, ErrorCode.VALIDATION, f"Invalid {field.replace('_', ' ')}", {"field": field})
        if apaar and await self.students.apaar_taken(apaar, exclude):
            raise APIError(409, ErrorCode.CONFLICT, "Another student holds this APAAR id", {"field": "apaar_id"})

    async def _program(self, program_id: uuid.UUID) -> Program:
        program = (
            await self.db.execute(
                select(Program).where(
                    Program.id == program_id, Program.institution_id == self.inst, Program.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if program is None:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown programme", {"field": "program_id"})
        if program.status == "closed":
            raise APIError(422, ErrorCode.VALIDATION, f"Programme {program.code} is closed", {"field": "program_id"})
        return program

    async def _check_binding(self, pr_id: uuid.UUID, program_id: uuid.UUID) -> None:
        row = (
            await self.db.execute(
                select(ProgramRegulation.program_id).where(
                    ProgramRegulation.id == pr_id, ProgramRegulation.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if row != program_id:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The programme-regulation belongs to another programme",
                {"field": "program_regulation_id"},
            )

    async def regulation_for_year(self, program_id: uuid.UUID, year: int) -> ProgramRegulation | None:
        """The active regulation binding of the programme effective for an admission year (latest first)."""
        row = (
            await self.db.execute(
                select(ProgramRegulation)
                .join(Regulation, Regulation.id == ProgramRegulation.regulation_id)
                .where(
                    ProgramRegulation.program_id == program_id,
                    ProgramRegulation.deleted_at.is_(None),
                    Regulation.deleted_at.is_(None),
                    Regulation.status == "active",
                    Regulation.effective_from_admission_year <= year,
                )
                .order_by(Regulation.effective_from_admission_year.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

    async def _batch(self, body: StudentCreate, program: Program, admission_date: date) -> Batch:
        if body.batch_id is not None:
            batch = (
                await self.db.execute(select(Batch).where(Batch.id == body.batch_id, Batch.institution_id == self.inst))
            ).scalar_one_or_none()
            if batch is None or batch.program_id != program.id or batch.deleted_at is not None:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The batch belongs to another programme", {"field": "batch_id"}
                )
            return batch
        year = body.admission_year or admission_date.year
        entry = "lateral" if body.entry_type.value == "lateral" else "regular"
        batch = (
            await self.db.execute(
                select(Batch).where(
                    Batch.institution_id == self.inst,
                    Batch.college_id == program.college_id,
                    Batch.program_id == program.id,
                    Batch.admission_year == year,
                    Batch.entry_type == entry,
                    Batch.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if batch is not None:
            return batch
        binding = None
        if body.program_regulation_id is not None:
            binding = (
                await self.db.execute(
                    select(ProgramRegulation).where(ProgramRegulation.id == body.program_regulation_id)
                )
            ).scalar_one_or_none()
        binding = binding or await self.regulation_for_year(program.id, year)
        if binding is None:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"No active regulation of {program.code} covers admission year {year}",
                {"field": "admission_year"},
            )
        from app.schemas.academics import BatchCreate
        from app.services.batch_service import BatchService

        created = await BatchService(self.db, self.principal, self.request).create(
            BatchCreate(
                program_id=program.id,
                program_regulation_id=binding.id,
                admission_year=year,
                entry_type=entry,
                section_count=1,
            )
        )
        return (await self.db.execute(select(Batch).where(Batch.id == created.id))).scalar_one()

    async def _section(self, batch: Batch, section_id: uuid.UUID | None, name: str | None) -> BatchSection | None:
        sections = list(
            (
                await self.db.execute(
                    select(BatchSection).where(BatchSection.batch_id == batch.id).order_by(BatchSection.name)
                )
            ).scalars()
        )
        if section_id is not None:
            match = next((s for s in sections if s.id == section_id), None)
            if match is None:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The section belongs to another batch", {"field": "section_id"}
                )
            return match
        if name:
            match = next((s for s in sections if s.name.upper() == name.strip().upper()), None)
            if match is None:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"Batch {batch.code} has no section {name}", {"field": "section"}
                )
            return match
        if not sections:
            return None
        rows = (
            await self.db.execute(
                text(
                    "SELECT r.section_id, COUNT(*) FROM student_term_records r JOIN student_program_enrollments e "
                    "ON e.id = r.student_program_enrollment_id WHERE e.batch_id = :b AND r.term_number = :n "
                    "AND e.status IN ('active','break','detained') GROUP BY r.section_id"
                ),
                {"b": batch.id, "n": batch.current_term_number},
            )
        ).all()
        counts: dict[Any, int] = {r[0]: int(r[1]) for r in rows}
        return min(sections, key=lambda s: (counts.get(s.id, 0), s.name))

    async def _registration_number(self, manual: str | None, program: Program, batch: Batch) -> str:
        if manual:
            number = manual.strip().upper()
            if await self.students.registration_taken(number):
                raise APIError(
                    409,
                    ErrorCode.CONFLICT,
                    f"Registration number {number} already exists",
                    {"field": "registration_number"},
                )
            return number
        scope = f"regno:{batch.admission_year}:{program.code}"
        seq_repo = SequenceRepository(self.db, self.principal, self.inst)
        if await seq_repo.by_scope(self.inst, scope, program.college_id) is None and (
            await seq_repo.by_scope(self.inst, scope, None) is None
        ):
            base = await seq_repo.by_scope(self.inst, "register_no", None)
            pattern = (
                base.pattern
                if base is not None and "{prog_code}" in base.pattern.lower()
                else "{college_code}{yy}{prog_code}{seq:3}"
            )
            await self.db.execute(
                text(
                    "INSERT INTO number_sequences (institution_id, college_id, scope_key, pattern, next_value, padding, "
                    "reset_policy) VALUES (:i, :c, :k, :p, 1, 3, 'never') ON CONFLICT DO NOTHING"
                ),
                {"i": self.inst, "c": program.college_id, "k": scope, "p": pattern},
            )
        college = (await self.students.college_rows([program.college_id])).get(program.college_id)
        ctx = {
            "yy": f"{batch.admission_year % 100:02d}",
            "yyyy": str(batch.admission_year),
            "mm": "",
            "college_code": college.code if college else "",
            "prog_code": _compact(program.code),
            "term": "",
        }
        for _ in range(50):
            value, seq = await seq_repo.next_value(self.inst, scope, program.college_id)
            number = render(seq.pattern, ctx, value, seq.padding).upper()[:30]
            if not await self.students.registration_taken(number):
                return number
        raise APIError(409, ErrorCode.CONFLICT, f"Sequence {scope} keeps producing taken numbers — check its pattern")

    async def _student_user(
        self, username: str, body: StudentCreate, password_hash: str | None
    ) -> tuple[User, str | None]:
        role = await RoleRepository(self.db).get_by_slug("student", self.inst)
        if role is None:
            raise APIError(422, ErrorCode.VALIDATION, "The institution has no 'student' role")
        taken = (
            await self.db.execute(
                select(User.id).where(User.institution_id == self.inst, func.lower(User.username) == username.lower())
            )
        ).first()
        if taken is not None:
            raise APIError(
                409, ErrorCode.CONFLICT, f"Username {username} already exists", {"field": "registration_number"}
            )
        temp = None
        if password_hash is None:
            temp = generate_temp_password()
            password_hash = hash_password(temp)
        user = User(
            institution_id=self.inst,
            username=username,
            email=str(body.email) if body.email else None,
            phone=_phone(body.phone),
            display_name=" ".join(p for p in (body.first_name, body.last_name) if p),
            user_type="student",
            password_hash=password_hash,
            must_change_password=True,
            is_verified=False,
            locale="en-IN",
            created_by=self.actor_id,
        )
        self.db.add(user)
        await self.db.flush()
        self.db.add(
            UserRole(
                institution_id=self.inst,
                user_id=user.id,
                role_id=role.id,
                scope_type="self",
                scope_id=None,
                assigned_by=self.actor_id,
            )
        )
        await self.db.flush()
        return user, temp

    async def _consents(self, user_id: uuid.UUID) -> None:
        version = await self.setting("privacy", "consent_texts_version") or "1.0"
        repo = ConsentRepository(self.db)
        for purpose in ("academic", "communication"):
            await repo.record(
                institution_id=self.inst,
                user_id=user_id,
                purpose=purpose,
                granted=True,
                text_version=str(version),
                granted_by_user_id=self.actor_id,
                ip=None,
            )

    async def _add_guardian(self, student: Student, g: GuardianIn, *, notify: bool = True) -> dict[str, Any] | None:
        from app.services.student_records_service import StudentRecordsService

        return await StudentRecordsService(self.db, self.principal, self.request, self.inst).add_guardian_row(
            student, g, notify=notify
        )

    # ---- rule 2: update -----------------------------------------------------------------------------------------------
    async def update(self, student_id: uuid.UUID, body: StudentUpdate) -> StudentDetailResponse:
        student = await self.students.get_visible(student_id, for_update=True)
        self._college_writable(student)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if PII_FIELDS & set(values) and not self.can("students", "manage"):
            raise APIError(
                403,
                ErrorCode.PERMISSION_DENIED,
                "Changing PII needs students:manage",
                {"fields": sorted(PII_FIELDS & set(values))},
            )
        pack = await self.pack()
        await self._check_ids(pack, values.get("apaar_id"), values.get("abc_id"), values.get("aadhaar"), student.id)
        mapped: dict[str, Any] = {}
        for k, v in values.items():
            if k == "category":
                mapped[k] = self._category(v, pack)
            elif k == "admission_quota":
                mapped[k] = self._quota(v, pack)
            elif k in ENCRYPTED:
                mapped[ENCRYPTED[k]] = (json.dumps(v) if k == "bank_details" and v is not None else v) or None
            elif k == "emergency_contact":
                address = dict(student.current_address or {})
                address["emergency_contact"] = v
                mapped["current_address"] = address
            elif k == "current_address":
                keep = (student.current_address or {}).get("emergency_contact")
                mapped[k] = {
                    **(v or {}),
                    **({"emergency_contact": keep} if keep and "emergency_contact" not in values else {}),
                }
            elif k == "phone":
                mapped[k] = _phone(v)
            elif hasattr(v, "value"):
                mapped[k] = v.value
            elif k == "email" and v is not None:
                mapped[k] = str(v)
            else:
                mapped[k] = v
        old = snap(student, STUDENT_KEYS)
        await self.students.update(student, expected_version=body.version, **mapped)
        await self._audit(
            "update",
            "student",
            student.id,
            old,
            {**snap(student, STUDENT_KEYS), "pii_changed": sorted(PII_FIELDS & set(values))},
        )
        await self._emit(
            "student.updated", {"student_id": str(student.id), "fields": sorted(values)}, "student", student.id
        )
        return await self.detail(student)

    def _college_writable(self, student: Student) -> None:
        if self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            try:
                check_college_writable(self.principal, student.college_id)
            except APIError:
                raise APIError(404, ErrorCode.NOT_FOUND, "Student not found") from None

    async def self_update(self, body: StudentSelfUpdate) -> StudentDetailResponse:
        student = await self.my_student()
        values = body.model_dump(exclude_unset=True)
        allowed = await self.setting("students", "self_service_fields") or []
        blocked = sorted(k for k in values if allowed and k not in allowed)
        if blocked:
            raise APIError(422, ErrorCode.VALIDATION, "These fields are not self-editable", {"fields": blocked})
        old = {k: getattr(student, k, None) for k in ("phone", "email", "current_address")}
        address = dict(student.current_address or {})
        if "current_address" in values:
            keep = address.get("emergency_contact")
            address = dict(values["current_address"] or {})
            if keep:
                address["emergency_contact"] = keep
        if "emergency_contact" in values:
            address["emergency_contact"] = values["emergency_contact"]
        if "phone" in values:
            student.phone = _phone(values["phone"])
        if "email" in values:
            student.email = str(values["email"]) if values["email"] else None
        if {"current_address", "emergency_contact"} & set(values):
            student.current_address = address or None
        await self.db.flush()
        await self._audit(
            "self_update",
            "student",
            student.id,
            {k: str(v) if v is not None else None for k, v in old.items()},
            {k: str(getattr(student, k)) if getattr(student, k) is not None else None for k in old},
        )
        await self._emit(
            "student.updated",
            {"student_id": str(student.id), "fields": sorted(values), "self": True},
            "student",
            student.id,
        )
        return await self.detail(student)

    async def set_photo(self, student_id: uuid.UUID, upload: UploadFile) -> StudentDetailResponse:
        from app.services.file_service import IMAGE_TYPES, FileService, storage

        student = await self.students.get_visible(student_id, for_update=True)
        own = student.user_id == self.actor_id
        if not own and not self.can("students", "update"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires students:update")
        saved = await FileService(self.db).save(
            upload, "student-photos", IMAGE_TYPES, max_mb=5, institution_id=self.inst
        )
        student.photo_url = storage.signed_url(saved.key, TEN_YEARS)
        await self.db.flush()
        await self._audit("photo", "student", student.id, None, {"photo_key": saved.key, "self": own})
        return await self.detail(student)

    # ---- rule 3: status ---------------------------------------------------------------------------------------------
    async def change_status(self, student_id: uuid.UUID, body: StatusChangeRequest) -> StudentDetailResponse:
        student = await self.students.get_visible(student_id, for_update=True)
        self._college_writable(student)
        target = body.status.value
        if target not in TRANSITIONS.get(student.status, set()):
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"A {student.status} student cannot move to {target} here",
                {"from": student.status, "to": target, "allowed": sorted(TRANSITIONS.get(student.status, set()))},
            )
        await self.apply_status(student, target, body.reason)
        return await self.detail(student)

    async def apply_status(
        self, student: Student, target: str, reason: str | None, *, enrollment_status: str | None = None
    ) -> None:
        """Move the student (and the open enrolment) to ``target``; terminal states deactivate the user."""
        previous = student.status
        student.status = target
        enrolment = await self.enrollments.open_for(student.id, for_update=True)
        wanted = enrollment_status or ENROLLMENT_STATUS_FOR.get(target)
        if enrolment is not None and wanted and enrolment.status != wanted:
            enrolment.status = wanted
            if wanted == "break":
                latest = (await self.terms.latest_for([enrolment.id])).get(enrolment.id)
                if latest is not None and latest.status in ("pending_registration", "registered", "in_progress"):
                    latest.status = "on_break"
        if target in {s.value for s in TERMINAL_STATUSES} and student.user_id:
            user = (await self.students.users([student.user_id])).get(student.user_id)
            if user is not None and user.is_active:
                user.is_active = False
                await self.db.flush()
                await SessionRepository(self.db).revoke_all(user.id, f"student_{target}")
        await self.db.flush()
        await self._audit("status", "student", student.id, {"status": previous}, {"status": target, "reason": reason})
        await self._emit(
            "student.status_changed",
            {"student_id": str(student.id), "from": previous, "to": target, "reason": reason},
            "student",
            student.id,
        )

    # ---- rule 4: stats ------------------------------------------------------------------------------------------------
    async def stats(
        self, college_id: uuid.UUID | None, program_id: uuid.UUID | None, batch_id: uuid.UUID | None
    ) -> StudentStats:
        stmt = self.students.filtered(scope="all", college_id=college_id, program_id=program_id, batch_id=batch_id)
        visible = stmt.with_only_columns(Student.id)
        total = int((await self.db.execute(select(func.count()).select_from(visible.subquery()))).scalar_one())
        out = StudentStats(total=total)
        programs: dict[uuid.UUID, Program] = {}
        batches: dict[uuid.UUID, Batch] = {}
        for dim in ("status", "program", "batch", "category", "gender", "standing"):
            rows = await self.students.stats(visible, dim)
            if dim == "program":
                programs = await self.students.program_rows([k for k, _ in rows if k])
            if dim == "batch":
                batches = await self.students.batch_rows([k for k, _ in rows if k])
            buckets = []
            for key, n in sorted(rows, key=lambda r: (-r[1], str(r[0]))):
                label = str(key) if key is not None else "—"
                if dim == "program" and key in programs:
                    label = programs[key].code
                if dim == "batch" and key in batches:
                    label = batches[key].code
                if dim == "gender":
                    label = {"M": "Male", "F": "Female", "O": "Other"}.get(str(key), label)
                buckets.append(StatBucket(key=str(key) if key is not None else "", label=label, count=n))
            setattr(out, f"by_{dim}", buckets)
        return out

    # ---- rule 5: import / export ------------------------------------------------------------------------------------
    @staticmethod
    def import_template() -> bytes:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Students"
        ws.append(list(IMPORT_COLUMNS))
        ws.append(
            [
                "",
                "Asha",
                "Verma",
                "2007-04-12",
                "F",
                "GEN",
                "STATE",
                "BTECH-CSE",
                "2026",
                "A",
                "regular",
                "+919800000001",
                "asha.verma@example.in",
                "Ravi Verma",
                "father",
                "+919800000002",
                "",
                "2026-08-01",
            ]
        )
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def parse_rows(content: bytes, filename: str | None) -> list[dict[str, str]]:
        """CSV (UTF-8, header row) or XLSX (first sheet, header row) → list of column→value dicts."""
        if content[:2] == b"PK" or (filename or "").lower().endswith(".xlsx"):
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            values = list(ws.iter_rows(values_only=True))
            if not values:
                return []
            header = [str(h or "").strip() for h in values[0]]
            out = []
            for row in values[1:]:
                if row is None or all(c in (None, "") for c in row):
                    continue
                out.append(
                    {
                        header[i]: ("" if c is None else (c.isoformat() if isinstance(c, date) else str(c))).strip()
                        for i, c in enumerate(row)
                        if i < len(header) and header[i]
                    }
                )
            return out
        decoded = content.decode("utf-8-sig", errors="replace")
        return [
            {k.strip(): (v or "").strip() for k, v in r.items() if k}
            for r in csv.DictReader(io.StringIO(decoded.strip()))
            if any((v or "").strip() for v in r.values())
        ]

    async def validate_rows(
        self, rows: list[dict[str, str]]
    ) -> tuple[list[tuple[int, StudentCreate]], list[BulkImportFailure]]:
        """Dry run: build every row's ``StudentCreate`` and check the references a real create would check."""
        programs = {
            p.code.upper(): p
            for p in (
                await self.db.execute(
                    select(Program).where(Program.institution_id == self.inst, Program.deleted_at.is_(None))
                )
            ).scalars()
        }
        pack = await self.pack()
        good: list[tuple[int, StudentCreate]] = []
        failed: list[BulkImportFailure] = []
        seen_reg: set[str] = set()
        seen_apaar: set[str] = set()
        for n, raw in enumerate(rows, start=2):  # row 1 is the header
            try:
                body = await self._import_body(raw, programs)
                self._category(body.category, pack)
                self._quota(body.admission_quota, pack)
                await self._check_ids(pack, body.apaar_id, None, None)
                if body.registration_number:
                    key = body.registration_number.upper()
                    if key in seen_reg or await self.students.registration_taken(key):
                        raise APIError(
                            409,
                            ErrorCode.CONFLICT,
                            f"Registration number {key} already exists",
                            {"field": "registration_number"},
                        )
                    seen_reg.add(key)
                if body.apaar_id:
                    if body.apaar_id in seen_apaar:
                        raise APIError(409, ErrorCode.CONFLICT, "Duplicate APAAR id in the file", {"field": "apaar_id"})
                    seen_apaar.add(body.apaar_id)
                good.append((n, body))
            except APIError as exc:
                failed.append(BulkImportFailure(row=n, reason=exc.message, field=(exc.details or {}).get("field")))
            except Exception as exc:  # noqa: BLE001 - pydantic errors and bad dates are row failures
                failed.append(BulkImportFailure(row=n, reason=_first_error(exc)))
        return good, failed

    async def _import_body(self, raw: dict[str, str], programs: dict[str, Program]) -> StudentCreate:
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        code = r.get("program_code", "").upper()
        program = programs.get(code)
        if program is None:
            raise APIError(
                422, ErrorCode.VALIDATION, f"Unknown programme {code or '(empty)'}", {"field": "program_code"}
            )
        year: int | None = None
        batch_code = r.get("batch_code", "")
        if batch_code:
            m = re.match(r"^(\d{4})", batch_code)
            if not m:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"Batch {batch_code} must start with the admission year",
                    {"field": "batch_code"},
                )
            year = int(m.group(1))
        gender = {"male": "M", "female": "F", "other": "O"}.get(
            r.get("gender", "").lower(), r.get("gender", "").upper()
        )
        guardians = []
        if r.get("guardian_name"):
            guardians.append(
                {
                    "relation": (r.get("guardian_relation") or "guardian").lower(),
                    "name": r["guardian_name"],
                    "phone": r.get("guardian_phone") or None,
                    "is_primary": True,
                }
            )
        payload: dict[str, Any] = {
            "registration_number": r.get("registration_number") or None,
            "first_name": r.get("first_name", ""),
            "last_name": r.get("last_name") or None,
            "dob": r.get("dob") or None,
            "gender": gender or None,
            "category": r.get("category") or None,
            "admission_quota": r.get("quota") or None,
            "program_id": program.id,
            "admission_year": year,
            "section": r.get("section") or None,
            "entry_type": (r.get("entry_type") or "regular").lower(),
            "phone": r.get("phone") or None,
            "email": r.get("email") or None,
            "apaar_id": r.get("apaar_id") or None,
            "admission_date": r.get("admission_date") or None,
            "guardians": guardians,
            "status": "active" if r.get("registration_number") else "admitted",
        }
        return StudentCreate.model_validate(payload)

    async def dry_run(self, content: bytes, filename: str | None) -> BulkImportResult:
        rows = self.parse_rows(content, filename)
        good, failed = await self.validate_rows(rows)
        return BulkImportResult(dry_run=True, total=len(rows), succeeded=len(good), failed=failed)

    async def enqueue_import(self, content: bytes, filename: str | None) -> BulkImportResult:
        from app.core.files import build_key, storage

        rows = self.parse_rows(content, filename)
        if not rows:
            raise APIError(422, ErrorCode.VALIDATION, "The file has no data rows", {"field": "file"})
        if len(rows) > 5000:
            raise APIError(422, ErrorCode.VALIDATION, "At most 5,000 rows per import", {"field": "file"})
        key = build_key(self.inst, "student-imports", filename or "students.csv")
        await storage.put(key, content, "application/octet-stream")
        job = await jobs.enqueue(
            self.db, self.principal, "students.bulk_import", {"key": key, "filename": filename}, queue="reports"
        )
        return BulkImportResult(dry_run=False, total=len(rows), succeeded=0, job_id=job.id)

    async def run_import(
        self, content: bytes, filename: str | None, progress: Callable[[int, str], Awaitable[None]]
    ) -> dict[str, Any]:
        from app.services.entitlement_service import EntitlementService

        rows = self.parse_rows(content, filename)
        good, failed = await self.validate_rows(rows)
        if good:
            await EntitlementService(self.db, self.principal).enforce_seat_limit(
                "student", institution_id=self.inst, adding=len(good)
            )
        created: list[dict[str, Any]] = []
        for i, (n, body) in enumerate(good, start=1):
            try:
                async with self.db.begin_nested():
                    result = await self.create_record(body, "import", audit=False, seat_check=False, notify=False)
                created.append(
                    {
                        "row": n,
                        "student_id": str(result.student.id),
                        "registration_number": result.student.registration_number,
                    }
                )
            except APIError as exc:
                failed.append(BulkImportFailure(row=n, reason=exc.message, field=(exc.details or {}).get("field")))
            except IntegrityError as exc:
                failed.append(BulkImportFailure(row=n, reason=f"duplicate or invalid reference: {str(exc.orig)[:160]}"))
            if i % 10 == 0:
                await progress(int(i * 100 / max(len(good), 1)), f"{i}/{len(good)} rows")
        failed.sort(key=lambda f: f.row)
        await self._audit(
            "bulk_import", "student", None, None, {"total": len(rows), "succeeded": len(created), "failed": len(failed)}
        )
        return BulkImportResult(
            dry_run=False, total=len(rows), succeeded=len(created), failed=failed, created=created
        ).model_dump(mode="json")

    async def export_xlsx(self, scope: str | None, **filters: Any) -> bytes:
        from openpyxl import Workbook

        stmt = self.students.filtered(scope=scope, **filters).order_by(Student.registration_number)
        rows = list((await self.db.execute(stmt.limit(20000))).scalars().all())
        unmask = may_unmask(self.principal, "students")
        items: list[StudentListItem] = []
        for i in range(0, len(rows), 500):
            items += await self.list_items(rows[i : i + 500], mask=not unmask)
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Students"
        header = list(EXPORT_HEADER)
        if unmask:
            header += ["Date of birth", "Aadhaar"]
        ws.append(header)
        for s, r in zip(rows, items, strict=True):
            line: list[Any] = [
                r.registration_number,
                r.full_name,
                r.college_code,
                r.department_code,
                r.program_code,
                r.batch_code,
                r.section_name,
                r.term_number,
                r.status,
                r.academic_standing,
                r.category,
                r.gender,
                r.phone,
                r.email,
                r.apaar_id,
            ]
            if unmask:
                line += [s.dob.isoformat() if s.dob else None, s.aadhaar_encrypted]
            ws.append(line)
        buf = io.BytesIO()
        wb.save(buf)
        await self._audit("export", "student", None, None, {"rows": len(rows), "pii": unmask})
        return buf.getvalue()

    async def enqueue_export(self, scope: str | None, filters: dict[str, Any]) -> uuid.UUID:
        clean = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in filters.items() if v is not None}
        job = await jobs.enqueue(
            self.db, self.principal, "students.export", {"scope": scope, "filters": clean}, queue="reports"
        )
        return job.id

    # ---- guardians helpers used by the seeder / admissions ----------------------------------------------------------
    async def guardian_rows(self, student_id: uuid.UUID) -> Sequence[StudentGuardian]:
        return await self.guardians.for_student(student_id)

    @staticmethod
    def guardian_out(rows: Sequence[StudentGuardian]) -> list[GuardianOut]:
        return [GuardianOut.model_validate(g) for g in rows]


async def count_seated_students(db: Any, institution_id: uuid.UUID) -> int:
    """Seat usage for the plan's ``student_limit`` (Phase 02 counted users; Phase 07 counts the student master)."""
    from app.repositories.student_repository import StudentRepository

    return await StudentRepository(db, None, institution_id).count_seated(institution_id)


def _first_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            return f"{'.'.join(str(x) for x in first.get('loc', ()))}: {first.get('msg')}"
        except Exception:  # noqa: BLE001
            pass
    return str(exc)[:300]
