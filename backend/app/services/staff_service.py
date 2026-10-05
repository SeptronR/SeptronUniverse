"""Staff master — Prompts/06 §06.6 ``staff_service.py``.

Rules
1. **Create**: ``employee_id`` from ``number_sequences('employee_id')`` (or supplied, unique per institution → 409);
   a user account is created (username = employee id, temporary password, ``must_change_password``) with the role
   from the designation category — ``faculty`` for teaching staff (``guest_faculty`` for guest/visiting), else
   ``receptionist`` — unless ``role_slug`` overrides it or ``user_id`` links an existing staff-type user; guest and
   visiting staff need ``hourly_rate_paise``; teaching staff get a faculty profile (cadre from the designation,
   ``max_scholars`` from the pack); a ``joining`` service-book entry; ``staff.created`` is emitted.
   **Unit holders** (Phases 03/05): when the linked user already holds ``hod`` @department, ``dean`` @faculty or
   ``class_advisor`` @section, ``departments.hod_staff_id`` / ``faculties.dean_staff_id`` /
   ``batch_sections.class_advisor_staff_id`` are back-filled with the new row (the role assignment stays the source of
   truth; existing user-based assignments keep working).
2. **Update** with the optimistic ``version``; PII (PAN, Aadhaar, bank details, statutory numbers, DOB) is read with
   ``hr:view_pii`` (or on one's own record) and written with ``hr:manage``; a member edits only ``StaffSelfUpdate``.
3. **Exit**: ``status = exited`` + ``exit_date``; blocked (409) while leaves are pending or payroll is unpaid; the user
   is deactivated (sessions revoked); an ``exit`` service-book entry; ``staff.exited``.
4. **Records**: documents (expiry reminders — Beat ``hr.document_expiry``), service book (``hr:service_book``),
   faculty profile (``is_phd_guide`` needs ``guide_recognition_no``; the member edits their own with
   ``faculty:research``), qualifications (exactly one ``is_highest``).
5. **Bulk import** (job ``hr.bulk_import``: one savepoint per CSV row, partial-success report) and **XLSX export**
   (PII masked unless ``hr:view_pii``).
"""

import csv
import io
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any

from fastapi import UploadFile

from app.core import jobs
from app.core.authz.masking import mask_pii, may_unmask
from app.core.errors import APIError, ErrorCode
from app.models.hr import (
    Designation,
    FacultyProfile,
    FacultyQualification,
    ServiceBookEntry,
    Staff,
    StaffDocument,
)
from app.repositories.leave_repository import LeaveRepository
from app.repositories.payroll_repository import PayrollRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.staff_repository import DesignationRepository, StaffRecordsRepository
from app.schemas.hr import (
    DesignationIn,
    DesignationOut,
    FacultyProfileIn,
    FacultyProfileOut,
    QualificationIn,
    QualificationOut,
    ServiceBookEntryIn,
    ServiceBookEntryOut,
    StaffCreate,
    StaffCreateResult,
    StaffDetailResponse,
    StaffDocumentIn,
    StaffDocumentOut,
    StaffExitRequest,
    StaffResponse,
    StaffSelfUpdate,
    StaffUpdate,
)
from app.schemas.rbac import UserCreate, UserRoleAssign
from app.services.hr.common import HrServiceBase, snap
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

STAFF_KEYS = (
    "employee_id",
    "first_name",
    "last_name",
    "college_id",
    "department_id",
    "designation_id",
    "employment_type",
    "staff_category",
    "status",
    "joining_date",
    "exit_date",
    "hourly_rate_paise",
    "reports_to_staff_id",
)
PII_FIELDS = {"pan", "aadhaar", "bank_details", "pf_number", "esi_number", "uan", "dob"}
ENCRYPTED = {"pan": "pan_encrypted", "aadhaar": "aadhaar_encrypted", "bank_details": "bank_details_encrypted"}
HOURLY = {"guest", "visiting"}
UNIT_LINKS = {
    ("hod", "department"): ("departments", "hod_staff_id"),
    ("dean", "faculty"): ("faculties", "dean_staff_id"),
    ("class_advisor", "offering"): ("batch_sections", "class_advisor_staff_id"),
}
IMPORT_COLUMNS = (
    "first_name",
    "last_name",
    "department_code",
    "designation",
    "employment_type",
    "staff_category",
    "joining_date",
    "email",
    "phone",
    "gender",
    "dob",
    "employee_id",
    "hourly_rate_paise",
)
TEN_YEARS = 10 * 365 * 24 * 3600


class StaffService(HrServiceBase):
    audit_module = "hr"

    def __init__(self, db: Any, principal: Any, request: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, request, institution_id)
        self.designations = DesignationRepository(db, principal, self.inst)
        self.records = StaffRecordsRepository(db)

    # ---- reads --------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, **filters: Any
    ) -> tuple[list[StaffResponse], PaginationMeta, VisibilityMeta]:
        from app.repositories.hr_scope import hr_visibility

        stmt = self.staff_repo.filtered(scope=scope, **filters)
        if not params.sort:
            params = params.model_copy(update={"sort": "employee_id"})
        rows, pagination = await self.staff_repo.paginate(stmt, params)
        out = await self._responses(list(rows))
        return out, pagination, hr_visibility(self.principal, "hr", pii=self.principal.has("hr", "view_pii"))

    async def _responses(self, rows: list[Staff]) -> list[StaffResponse]:
        depts = await self.staff_repo.department_rows([r.department_id for r in rows if r.department_id])
        desigs = await self.designations.by_ids([r.designation_id for r in rows if r.designation_id])
        users = await self.staff_repo.usernames([r.user_id for r in rows if r.user_id])
        out: list[StaffResponse] = []
        for s in rows:
            r = StaffResponse.model_validate(s)
            r.department_code = depts[s.department_id].code if s.department_id in depts else None
            d = desigs.get(s.designation_id) if s.designation_id else None
            r.designation_name, r.cadre = (d.name, d.cadre) if d else (None, None)
            r.username = users.get(s.user_id) if s.user_id else None
            r.is_self = s.user_id == self.principal.id
            out.append(r if r.is_self else mask_pii(r, self.principal, "hr"))
        return out

    async def get(self, staff_id: uuid.UUID) -> StaffDetailResponse:
        return await self.detail(await self.staff_repo.get_visible(staff_id))

    async def me(self) -> StaffDetailResponse:
        staff = await self.my_staff()
        assert staff is not None
        return await self.detail(staff)

    async def detail(self, s: Staff) -> StaffDetailResponse:
        base = (await self._responses([s]))[0]
        r = StaffDetailResponse(**base.model_dump())
        r.phone, r.email = s.phone, s.email
        r.dob = s.dob.isoformat() if s.dob else None
        r.gender, r.blood_group = s.gender, s.blood_group
        r.address, r.emergency_contact = s.address, s.emergency_contact
        r.confirmation_date, r.retirement_date = s.confirmation_date, s.retirement_date
        r.exit_date, r.exit_reason = s.exit_date, s.exit_reason
        r.pan, r.aadhaar, r.bank_details = s.pan_encrypted, s.aadhaar_encrypted, s.bank_details_encrypted
        r.pf_number, r.esi_number, r.uan = s.pf_number, s.esi_number, s.uan
        r.reports_to_staff_id = s.reports_to_staff_id
        if s.reports_to_staff_id:
            r.reports_to_name = (await self.staff_repo.names([s.reports_to_staff_id])).get(
                s.reports_to_staff_id, ("", "")
            )[0]
        r.has_faculty_profile = (await self.records.profile(s.id)) is not None
        r.created_at = s.created_at
        return r if r.is_self else mask_pii(r, self.principal, "hr")

    # ---- rule 1 -------------------------------------------------------------------------------------------------
    async def create(self, body: StaffCreate, *, audit: bool = True) -> StaffCreateResult:
        college_id, department_id = body.college_id, body.department_id
        if department_id is not None:
            dept = (await self.staff_repo.department_rows([department_id])).get(department_id)
            if dept is None or dept.institution_id != self.inst:
                raise APIError(422, ErrorCode.VALIDATION, "Unknown department", {"field": "department_id"})
            if college_id is not None and college_id != dept.college_id:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The department belongs to another college", {"field": "college_id"}
                )
            college_id = dept.college_id
        designation: Designation | None = None
        if body.designation_id is not None:
            designation = await self.designations.get_one(body.designation_id)
        category = (body.staff_category.value if body.staff_category else None) or (
            designation.category if designation else "teaching"
        )
        if body.employment_type.value in HOURLY and not body.hourly_rate_paise:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Guest and visiting staff need hourly_rate_paise",
                {"field": "hourly_rate_paise"},
            )
        if body.reports_to_staff_id is not None:
            await self.staff_repo.get_visible(body.reports_to_staff_id)
        employee_id = body.employee_id or await self._next_employee_id()
        if await self.staff_repo.employee_id_taken(employee_id):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Employee id {employee_id} already exists", {"field": "employee_id"}
            )

        user_id, username, temp_password = await self._account(body, employee_id, category)
        staff = await self.staff_repo.create(
            institution_id=self.inst,
            college_id=college_id,
            user_id=user_id,
            employee_id=employee_id,
            department_id=department_id,
            designation_id=body.designation_id,
            first_name=body.first_name.strip(),
            middle_name=body.middle_name,
            last_name=body.last_name,
            dob=body.dob,
            gender=body.gender,
            blood_group=body.blood_group,
            phone=body.phone,
            email=str(body.email) if body.email else None,
            address=body.address,
            emergency_contact=body.emergency_contact,
            employment_type=body.employment_type.value,
            staff_category=category,
            joining_date=body.joining_date,
            confirmation_date=body.confirmation_date,
            retirement_date=body.retirement_date,
            pan_encrypted=body.pan,
            aadhaar_encrypted=body.aadhaar,
            bank_details_encrypted=body.bank_details.model_dump_json() if body.bank_details else None,
            pf_number=body.pf_number,
            esi_number=body.esi_number,
            uan=body.uan,
            hourly_rate_paise=body.hourly_rate_paise,
            reports_to_staff_id=body.reports_to_staff_id,
            status="active",
            created_by=self.principal.id,
        )
        if body.joining_date:
            await self.add_service_entry(
                staff, "joining", body.joining_date, {"designation": designation.name if designation else None}
            )
        if category == "teaching":
            cadre = designation.cadre if designation else None
            pack = await self.pack()
            await self.records.add(
                FacultyProfile(
                    institution_id=self.inst,
                    staff_id=staff.id,
                    cadre=cadre,
                    max_scholars=pack.hr.max_scholars_by_cadre.get(cadre or ""),
                )
            )
        linked = await self.link_unit_holders(staff)
        if audit:
            await self._audit("create", "staff", staff.id, None, {**snap(staff, STAFF_KEYS), "linked_units": linked})
        await self._emit("staff.created", {"staff_id": str(staff.id), "employee_id": employee_id}, "staff", staff.id)
        if user_id and username:
            await self._notify(
                "staff.welcome",
                [user_id],
                {"name": staff.full_name, "employee_id": employee_id, "username": username},
            )
        return StaffCreateResult(staff=await self.detail(staff), username=username, temp_password=temp_password)

    async def _next_employee_id(self) -> str:
        from app.services.sequence_service import SequenceService

        try:
            nxt = await SequenceService(self.db, self.principal, self.request, self.inst).next("employee_id")
        except APIError as exc:
            if exc.status_code == 404:
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    "The institution has no 'employee_id' number sequence (Settings → Number sequences)",
                ) from exc
            raise
        return nxt.rendered

    async def _account(
        self, body: StaffCreate, employee_id: str, category: str
    ) -> tuple[uuid.UUID | None, str | None, str | None]:
        if body.user_id is not None:
            user = await self.staff_repo.user(body.user_id)
            if user is None or user.institution_id != self.inst or user.deleted_at is not None:
                raise APIError(422, ErrorCode.VALIDATION, "Unknown user", {"field": "user_id"})
            if user.user_type != "staff":
                raise APIError(422, ErrorCode.VALIDATION, "Only staff-type users can be linked", {"field": "user_id"})
            if await self.staff_repo.by_user(user.id) is not None:
                raise APIError(
                    409, ErrorCode.CONFLICT, "The user is already linked to a staff record", {"field": "user_id"}
                )
            return user.id, user.username, None
        if not body.create_user:
            return None, None, None
        slug = body.role_slug or (
            ("guest_faculty" if body.employment_type.value in HOURLY else "faculty")
            if category == "teaching"
            else "receptionist"
        )
        role = await RoleRepository(self.db).get_by_slug(slug, self.inst)
        if role is None:
            raise APIError(422, ErrorCode.VALIDATION, f"The institution has no {slug!r} role", {"field": "role_slug"})
        username = employee_id
        if await self.staff_repo.username_taken(username):
            raise APIError(409, ErrorCode.CONFLICT, f"Username {username} already exists", {"field": "employee_id"})
        from app.services.user_service import UserService

        created = await UserService(self.db, self.principal).create(
            UserCreate(
                username=username,
                email=body.email,
                phone=body.phone,
                display_name=" ".join(p for p in (body.first_name, body.last_name) if p),
                user_type="staff",
                must_change_password=True,
                roles=[UserRoleAssign(role_id=role.id)],
            ),
            self.request,
        )
        return created.id, username, created.temporary_password

    async def link_unit_holders(self, staff: Staff) -> list[str]:
        """Back the Phase 03/05 unit holders (HOD, dean, class advisor) with the staff row (rule 1)."""
        if staff.user_id is None:
            return []
        linked: list[str] = []
        for slug, scope_type, scope_id in await self.staff_repo.unit_assignments(staff.user_id):
            target = UNIT_LINKS.get((slug, scope_type))
            if target and scope_id is not None and await self.staff_repo.link_unit(*target, scope_id, staff.id):
                linked.append(f"{target[0]}.{target[1]}")
        return linked

    # ---- rule 2 -------------------------------------------------------------------------------------------------
    async def update(self, staff_id: uuid.UUID, body: StaffUpdate) -> StaffDetailResponse:
        staff = await self.staff_repo.get_visible(staff_id, for_update=True)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if PII_FIELDS & set(values) and not self.principal.has("hr", "manage"):
            raise APIError(
                403,
                ErrorCode.PERMISSION_DENIED,
                "Changing PII needs hr:manage",
                {"fields": sorted(PII_FIELDS & set(values))},
            )
        if "department_id" in values and values["department_id"] is not None:
            dept = (await self.staff_repo.department_rows([values["department_id"]])).get(values["department_id"])
            if dept is None:
                raise APIError(422, ErrorCode.VALIDATION, "Unknown department", {"field": "department_id"})
            values["college_id"] = dept.college_id
        if values.get("designation_id"):
            await self.designations.get_one(values["designation_id"])
        if values.get("reports_to_staff_id") == staff.id:
            raise APIError(
                422, ErrorCode.VALIDATION, "A member cannot report to themselves", {"field": "reports_to_staff_id"}
            )
        mapped: dict[str, Any] = {}
        for k, v in values.items():
            if k in ENCRYPTED:
                mapped[ENCRYPTED[k]] = json.dumps(v) if k == "bank_details" and v is not None else v
            elif hasattr(v, "value"):
                mapped[k] = v.value
            elif k == "email" and v is not None:
                mapped[k] = str(v)
            else:
                mapped[k] = v
        employment = mapped.get("employment_type", staff.employment_type)
        if employment in HOURLY and not mapped.get("hourly_rate_paise", staff.hourly_rate_paise):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Guest and visiting staff need hourly_rate_paise",
                {"field": "hourly_rate_paise"},
            )
        old = snap(staff, STAFF_KEYS)
        transfer = "department_id" in mapped and mapped["department_id"] != staff.department_id
        await self.staff_repo.update(staff, expected_version=body.version, **mapped)
        if transfer:
            await self.add_service_entry(
                staff,
                "transfer",
                await self.today(),
                {"from_department_id": old["department_id"], "to_department_id": str(staff.department_id)},
            )
        await self._audit(
            "update",
            "staff",
            staff.id,
            old,
            {**snap(staff, STAFF_KEYS), "pii_changed": sorted(PII_FIELDS & set(values))},
        )
        await self._emit("staff.updated", {"staff_id": str(staff.id), "fields": sorted(values)}, "staff", staff.id)
        return await self.detail(staff)

    async def update_me(self, body: StaffSelfUpdate) -> StaffDetailResponse:
        staff = await self.my_staff()
        assert staff is not None
        values = body.model_dump(exclude_unset=True)
        if "email" in values and values["email"] is not None:
            values["email"] = str(values["email"])
        old = {k: getattr(staff, k) for k in values}
        await self.staff_repo.update(staff, **values)
        await self._audit(
            "self_update",
            "staff",
            staff.id,
            {k: str(v) if v is not None else None for k, v in old.items()},
            {k: str(v) if v is not None else None for k, v in values.items()},
        )
        await self._emit(
            "staff.updated", {"staff_id": str(staff.id), "fields": sorted(values), "self": True}, "staff", staff.id
        )
        return await self.detail(staff)

    async def set_photo(self, staff_id: uuid.UUID, upload: UploadFile) -> StaffDetailResponse:
        from app.services.file_service import IMAGE_TYPES, FileService, storage

        staff = await self.staff_repo.get_visible(staff_id, for_update=True)
        if staff.user_id != self.principal.id and not self.principal.has("hr", "update"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires hr:update")
        saved = await FileService(self.db).save(upload, "staff-photos", IMAGE_TYPES, max_mb=5, institution_id=self.inst)
        staff.photo_url = storage.signed_url(saved.key, TEN_YEARS)
        await self.db.flush()
        await self._audit("photo", "staff", staff.id, None, {"photo_key": saved.key})
        return await self.detail(staff)

    # ---- rule 3 -------------------------------------------------------------------------------------------------
    async def exit(self, staff_id: uuid.UUID, body: StaffExitRequest) -> StaffDetailResponse:
        staff = await self.staff_repo.get_visible(staff_id, for_update=True)
        if staff.status == "exited":
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The member has already exited")
        pending = await LeaveRepository(self.db, self.principal, self.inst).open_count(staff.id)
        unpaid = await PayrollRepository(self.db, self.principal, self.inst).unpaid_count(staff.id)
        if pending or unpaid:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "Close the member's pending leaves and unpaid payroll first",
                {"pending_leaves": pending, "unpaid_payrolls": unpaid},
            )
        old = snap(staff, STAFF_KEYS)
        staff.status, staff.exit_date, staff.exit_reason = "exited", body.exit_date, body.exit_reason
        if staff.user_id:
            user = await self.staff_repo.user(staff.user_id)
            if user is not None and user.id != self.principal.id:
                user.is_active = False
                await self.db.flush()
                await SessionRepository(self.db).revoke_all(user.id, "staff_exit")
        await self.staff_repo.clear_reports_to(staff.id)
        await self.add_service_entry(staff, "exit", body.exit_date, {"reason": body.exit_reason})
        await self.db.flush()
        await self._audit("exit", "staff", staff.id, old, snap(staff, STAFF_KEYS))
        await self._emit(
            "staff.exited", {"staff_id": str(staff.id), "exit_date": body.exit_date.isoformat()}, "staff", staff.id
        )
        return await self.detail(staff)

    # ---- rule 4: records ----------------------------------------------------------------------------------------
    async def add_service_entry(
        self,
        staff: Staff,
        entry_type: str,
        effective: date,
        details: dict[str, Any] | None,
        document_url: str | None = None,
    ) -> ServiceBookEntry:
        return await self.records.add(  # type: ignore[no-any-return]
            ServiceBookEntry(
                institution_id=self.inst,
                staff_id=staff.id,
                entry_type=entry_type,
                effective_date=effective,
                details=details,
                document_url=document_url,
                recorded_by=self.principal.id,
            )
        )

    async def service_book(self, staff_id: uuid.UUID) -> list[ServiceBookEntryOut]:
        staff = await self.staff_repo.get_visible(staff_id)
        return [ServiceBookEntryOut.model_validate(e) for e in await self.records.service_book(staff.id)]

    async def add_service_book(self, staff_id: uuid.UUID, body: ServiceBookEntryIn) -> ServiceBookEntryOut:
        if not (self.principal.has("hr", "service_book") or self.principal.has("hr", "manage")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires hr:service_book")
        staff = await self.staff_repo.get_visible(staff_id)
        entry = await self.add_service_entry(
            staff, body.entry_type.value, body.effective_date, body.details, body.document_url
        )
        await self._audit(
            "service_book",
            "staff",
            staff.id,
            None,
            {"entry_type": body.entry_type.value, "effective_date": body.effective_date.isoformat()},
        )
        return ServiceBookEntryOut.model_validate(entry)

    async def documents(self, staff_id: uuid.UUID) -> list[StaffDocumentOut]:
        staff = await self.staff_repo.get_visible(staff_id)
        return [StaffDocumentOut.model_validate(d) for d in await self.records.documents(staff.id)]

    async def add_document(self, staff_id: uuid.UUID, body: StaffDocumentIn) -> StaffDocumentOut:
        staff = await self.staff_repo.get_visible(staff_id)
        own = staff.user_id == self.principal.id
        if not own and not self.principal.has("hr", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires hr:manage")
        doc = await self.records.add(
            StaffDocument(
                institution_id=self.inst,
                staff_id=staff.id,
                doc_type=body.doc_type,
                file_url=body.file_url,
                expires_on=body.expires_on,
                verified_by=None if own else self.principal.id,
                verified_at=None if own else datetime.now(UTC),
            )
        )
        await self._audit("document", "staff", staff.id, None, {"doc_type": body.doc_type})
        return StaffDocumentOut.model_validate(doc)

    async def faculty_profile(self, staff_id: uuid.UUID) -> FacultyProfileOut | None:
        staff = await self.staff_repo.get_visible(staff_id)
        row = await self.records.profile(staff.id)
        return FacultyProfileOut.model_validate(row) if row else None

    async def upsert_faculty_profile(self, staff_id: uuid.UUID, body: FacultyProfileIn) -> FacultyProfileOut:
        staff = await self.staff_repo.get_visible(staff_id)
        own = staff.user_id == self.principal.id
        if not (self.principal.has("hr", "manage") or (own and self.principal.has("faculty", "research"))):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Requires hr:manage (or faculty:research on your own profile)"
            )
        if body.is_phd_guide and not body.guide_recognition_no:
            raise APIError(
                422, ErrorCode.VALIDATION, "A PhD guide needs guide_recognition_no", {"field": "guide_recognition_no"}
            )
        values = body.model_dump()
        values["cadre"] = body.cadre.value if body.cadre else None
        if values.get("max_scholars") is None:
            values["max_scholars"] = (await self.pack()).hr.max_scholars_by_cadre.get(values["cadre"] or "")
        row = await self.records.profile(staff.id)
        old = snap(row, tuple(values)) if row else None
        if row is None:
            row = await self.records.add(FacultyProfile(institution_id=self.inst, staff_id=staff.id, **values))
        else:
            for k, v in values.items():
                setattr(row, k, v)
            await self.db.flush()
        await self._audit("faculty_profile", "staff", staff.id, old, snap(row, tuple(values)))
        return FacultyProfileOut.model_validate(row)

    async def qualifications(self, staff_id: uuid.UUID) -> list[QualificationOut]:
        staff = await self.staff_repo.get_visible(staff_id)
        return [QualificationOut.model_validate(q) for q in await self.records.qualifications(staff.id)]

    async def add_qualification(self, staff_id: uuid.UUID, body: QualificationIn) -> list[QualificationOut]:
        staff = await self.staff_repo.get_visible(staff_id)
        own = staff.user_id == self.principal.id
        if not (self.principal.has("hr", "manage") or (own and self.principal.has("faculty", "research"))):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires hr:manage")
        existing = await self.records.qualifications(staff.id)
        highest = body.is_highest or not existing
        if highest:
            await self.records.clear_highest(staff.id)
        await self.records.add(
            FacultyQualification(
                institution_id=self.inst, staff_id=staff.id, **{**body.model_dump(), "is_highest": highest}
            )
        )
        if highest:
            profile = await self.records.profile(staff.id)
            if profile is not None:
                profile.highest_qualification = body.degree
                profile.is_phd = profile.is_phd or body.degree.lower().replace(".", "") in {"phd", "dphil"}
        await self._audit("qualification", "staff", staff.id, None, {"degree": body.degree, "is_highest": highest})
        return await self.qualifications(staff.id)

    # ---- designations -------------------------------------------------------------------------------------------
    async def list_designations(self, include_inactive: bool) -> list[DesignationOut]:
        rows = await self.designations.all(include_inactive)
        counts = await self._designation_counts()
        out = []
        for d in rows:
            r = DesignationOut.model_validate(d)
            r.staff_count = counts.get(d.id, 0)
            out.append(r)
        return out

    async def _designation_counts(self) -> dict[uuid.UUID, int]:
        from sqlalchemy import func, select

        rows = (
            await self.db.execute(
                select(Staff.designation_id, func.count())
                .where(Staff.deleted_at.is_(None), Staff.status != "exited")
                .group_by(Staff.designation_id)
            )
        ).all()
        return {d: int(n) for d, n in rows if d}

    async def create_designation(self, body: DesignationIn) -> DesignationOut:
        if await self.designations.by_name(body.name):
            raise APIError(409, ErrorCode.CONFLICT, f"Designation {body.name!r} already exists", {"field": "name"})
        values = body.model_dump()
        values["cadre"] = body.cadre.value if body.cadre else None
        values["category"] = body.category.value
        d = await self.designations.create(institution_id=self.inst, **values)
        await self._audit("create", "designation", d.id, None, values)
        return DesignationOut.model_validate(d)

    async def update_designation(self, designation_id: uuid.UUID, body: DesignationIn) -> DesignationOut:
        d = await self.designations.get_one(designation_id)
        clash = await self.designations.by_name(body.name)
        if clash is not None and clash.id != d.id:
            raise APIError(409, ErrorCode.CONFLICT, f"Designation {body.name!r} already exists", {"field": "name"})
        values = body.model_dump()
        values["cadre"] = body.cadre.value if body.cadre else None
        values["category"] = body.category.value
        old = snap(d, tuple(values))
        await self.designations.update(d, **values)
        await self._audit("update", "designation", d.id, old, values)
        return DesignationOut.model_validate(d)

    async def delete_designation(self, designation_id: uuid.UUID) -> None:
        d = await self.designations.get_one(designation_id)
        if await self.designations.in_use(d.id):
            raise APIError(409, ErrorCode.CONFLICT, "Staff hold this designation — deactivate it instead")
        await self.db.delete(d)
        await self.db.flush()
        await self._audit("delete", "designation", designation_id, {"name": d.name}, None)

    # ---- rule 5: import / export --------------------------------------------------------------------------------
    async def enqueue_bulk_import(self, csv_text: str) -> dict[str, Any]:
        row = await jobs.enqueue(self.db, self.principal, "hr.bulk_import", {"csv": csv_text})
        return {"job_id": str(row.id), "status": row.status}

    async def run_bulk_import(self, csv_text: str, progress: Callable[[int, str], Awaitable[None]]) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        rows = list(reader)
        failed: list[dict[str, Any]] = []
        succeeded = 0
        dept_codes = await self._dept_codes()
        for n, raw in enumerate(rows, start=1):
            try:
                body = await self._import_body(raw, dept_codes)
                async with self.db.begin_nested():
                    await self.create(body, audit=False)
                succeeded += 1
            except APIError as exc:
                failed.append({"row": n, "code": exc.code, "error": exc.message, "details": exc.details})
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the import (pydantic errors …)
                failed.append({"row": n, "code": "VALIDATION", "error": _first_error(exc)})
            if n % 10 == 0:
                await progress(int(n * 100 / max(len(rows), 1)), f"{n}/{len(rows)} rows")
        await self._audit(
            "bulk_import", "staff", None, None, {"total": len(rows), "succeeded": succeeded, "failed": len(failed)}
        )
        return {"total": len(rows), "succeeded": succeeded, "failed": failed}

    async def _dept_codes(self) -> dict[str, uuid.UUID]:
        from sqlalchemy import select

        from app.models.platform import Department

        rows = (
            await self.db.execute(select(Department.code, Department.id).where(Department.deleted_at.is_(None)))
        ).all()
        return {c.upper(): i for c, i in rows}

    async def _import_body(self, raw: dict[str, Any], dept_codes: dict[str, uuid.UUID]) -> StaffCreate:
        r = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        dept = r.get("department_code", "").upper()
        if dept and dept not in dept_codes:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown department {dept}", {"field": "department_code"})
        designation = await self.designations.by_name(r["designation"]) if r.get("designation") else None
        if r.get("designation") and designation is None:
            raise APIError(
                422, ErrorCode.VALIDATION, f"Unknown designation {r['designation']}", {"field": "designation"}
            )
        payload: dict[str, Any] = {
            "first_name": r.get("first_name") or "",
            "last_name": r.get("last_name") or None,
            "department_id": dept_codes.get(dept) if dept else None,
            "designation_id": designation.id if designation else None,
            "employment_type": r.get("employment_type") or "regular",
            "staff_category": r.get("staff_category") or None,
            "joining_date": r.get("joining_date") or None,
            "email": r.get("email") or None,
            "phone": r.get("phone") or None,
            "gender": r.get("gender") or None,
            "dob": r.get("dob") or None,
            "employee_id": r.get("employee_id") or None,
            "hourly_rate_paise": int(r["hourly_rate_paise"]) if r.get("hourly_rate_paise") else None,
        }
        return StaffCreate.model_validate(payload)

    async def export_xlsx(self, scope: str | None, **filters: Any) -> bytes:
        from openpyxl import Workbook

        stmt = self.staff_repo.filtered(scope=scope, **filters).order_by(Staff.employee_id)
        rows = list((await self.db.execute(stmt)).scalars().all())
        responses = await self._responses(rows)
        unmask = may_unmask(self.principal, "hr")
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Staff"
        header = [
            "Employee id",
            "Name",
            "Department",
            "Designation",
            "Cadre",
            "Type",
            "Category",
            "Status",
            "Joined",
            "Phone",
            "E-mail",
        ]
        if unmask:
            header += ["PAN", "UAN", "PF number"]
        ws.append(header)
        for s, r in zip(rows, responses, strict=True):
            line = [
                r.employee_id,
                r.full_name,
                r.department_code,
                r.designation_name,
                r.cadre,
                r.employment_type,
                r.staff_category,
                r.status,
                r.joining_date.isoformat() if r.joining_date else None,
                r.phone,
                r.email,
            ]
            if unmask:
                line += [s.pan_encrypted, s.uan, s.pf_number]
            ws.append(line)
        buf = io.BytesIO()
        wb.save(buf)
        await self._audit("export", "staff", None, None, {"rows": len(rows), "pii": unmask})
        return buf.getvalue()


def _first_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            return f"{'.'.join(str(x) for x in first.get('loc', ()))}: {first.get('msg')}"
        except Exception:  # noqa: BLE001
            pass
    return str(exc)[:300]
