"""Shared plumbing of the Phase 26 document services — on the Phase 25 ``FacilitiesBase`` (people, meta rows,
sequences, ScopeTab predicates).

**Visibility** (Prompts/26 "Visibility rules") of ``issued_documents``: *self* (``person_id`` = the caller's student /
staff record — alumni are students), *wards* (consented guardians), *department* (HOD / class advisor, students of
their departments and only ``bonafide | conduct | character``), *college* (``college_admin``, students / staff of the
college) and *all* (institution-scoped ``certificates:view_all | issue | manage``). Office roles are further limited by
template type: the controller of examinations sees exam types, the HR officer staff types; registrar, office staff
(receptionist) and the auditor see every type.

Small facts without a column (template draft / change note, document version and supersession, downloads, request
timeline / pickup / courier / checks, serial void reasons and book mapping, bulk job reports) live in
``institution_settings`` rows of category ``documents_meta`` keyed ``<kind>:<id>``.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_, select, true

from app.enums.documents import DEPARTMENT_TYPES, EXAM_TYPES, STAFF_TYPES
from app.models.documents import IssuedDocument
from app.models.hr import Staff
from app.models.students import Student, StudentProgramEnrollment
from app.services.facilities.common import (
    FacilitiesBase,
    dept_subquery,
    forbidden,
    institution_scope,
    not_found,
    now_utc,
    rule,
    scope_ids,
)

__all__ = ["DocumentsBase", "forbidden", "not_found", "now_utc", "rule"]

DOC_META = "documents_meta"
UNLIMITED_ROLES = frozenset(
    {"registrar", "institution_admin", "super_admin", "college_admin", "auditor", "receptionist", "support_agent"}
)


def mask_holder(name: str | None, reg_no: str | None = None) -> str:
    initials = " ".join(f"{p[0]}." for p in (name or "").split() if p)
    if reg_no:
        tail = reg_no[-3:] if len(reg_no) > 3 else reg_no
        return f"{initials} ({'*' * max(len(reg_no) - 3, 0)}{tail})".strip()
    return initials or "—"


class DocumentsBase(FacilitiesBase):
    audit_module = "documents"
    module = "certificates"
    meta_category = DOC_META

    # ---- role limits ----------------------------------------------------------------------------------------------------
    def roles(self) -> set[str]:
        return set(getattr(self.principal, "roles", None) or [])

    def type_limit(self) -> set[str] | None:
        """Template types an office role may see (``None`` = every type)."""
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return None
        roles = self.roles()
        if roles & UNLIMITED_ROLES:
            return None
        allowed: set[str] = set()
        if "controller_of_examinations" in roles or "exam_cell" in roles:
            allowed |= EXAM_TYPES
        if "hr_officer" in roles:
            allowed |= STAFF_TYPES
        if roles & {"hod", "class_advisor", "dean"}:
            allowed |= DEPARTMENT_TYPES
        return allowed if allowed else None

    def office(self) -> bool:
        return self.can("certificates", "issue") or self.can("certificates", "manage")

    def registrar_like(self) -> bool:
        """Revoke / reissue / register management (registrar per rules; institution admins hold ``manage``)."""
        return self.can("certificates", "manage") and not self.roles() <= {"college_admin"}

    # ---- people ---------------------------------------------------------------------------------------------------------
    async def my_person_ids(self) -> list[uuid.UUID]:
        out: list[uuid.UUID] = []
        st = await self.my_student()
        if st is not None:
            out.append(st.id)
        sf = await self.my_staff()
        if sf is not None:
            out.append(sf.id)
        return out

    async def holder(self, person_type: str | None, person_id: uuid.UUID | None) -> tuple[str | None, str | None]:
        """``(name, registration / employee number)``."""
        if person_id is None:
            return None, None
        if person_type == "staff":
            s = (await self.db.execute(select(Staff).where(Staff.id == person_id))).scalar_one_or_none()
            return (" ".join(x for x in (s.first_name, s.last_name) if x), s.employee_id) if s else (None, None)
        st = (await self.db.execute(select(Student).where(Student.id == person_id))).scalar_one_or_none()
        return (st.full_name, st.registration_number) if st else (None, None)

    # ---- issued_documents visibility -------------------------------------------------------------------------------------
    async def issued_predicate(self, scope: str | None = None) -> ColumnElement[bool]:
        p = self.principal
        limit = self.type_limit()
        type_ok: ColumnElement[bool] = IssuedDocument.template_type.in_(limit) if limit is not None else true()
        reader = self.can("certificates", "view_all") or self.office()
        if scope in (None, "all") and reader and (p is None or institution_scope(p)):
            return type_ok
        if getattr(p, "id", None) is None:
            return false()
        parts: list[ColumnElement[bool]] = []
        if scope in (None, "self", "mine"):
            mine = await self.my_person_ids()
            if mine:
                parts.append(IssuedDocument.person_id.in_(mine))
        if scope in (None, "wards"):
            wards = await self.ward_ids()
            if wards:
                parts.append(and_(IssuedDocument.person_type == "student", IssuedDocument.person_id.in_(wards)))
        units = scope_ids(p, "department") or scope_ids(p, "faculty")
        if scope in (None, "department") and units and reader:
            studs = select(StudentProgramEnrollment.student_id).where(
                StudentProgramEnrollment.department_id.in_(dept_subquery(p))
            )
            staff = select(Staff.id).where(Staff.department_id.in_(dept_subquery(p)))
            parts.append(
                and_(
                    IssuedDocument.template_type.in_(DEPARTMENT_TYPES),
                    or_(IssuedDocument.person_id.in_(studs), IssuedDocument.person_id.in_(staff)),
                )
            )
        colleges = scope_ids(p, "college")
        if scope in (None, "college") and colleges and reader:
            parts.append(
                and_(
                    type_ok,
                    or_(
                        IssuedDocument.person_id.in_(select(Student.id).where(Student.college_id.in_(colleges))),
                        IssuedDocument.person_id.in_(select(Staff.id).where(Staff.college_id.in_(colleges))),
                    ),
                )
            )
        return or_(*parts) if parts else false()

    def issued_scopes(self) -> list[str]:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return ["all"]
        tabs = ["self"]
        reader = self.can("certificates", "view_all") or self.office()
        if (scope_ids(p, "department") or scope_ids(p, "faculty")) and reader:
            tabs.append("department")
        if scope_ids(p, "college") and reader:
            tabs.append("college")
        if reader and institution_scope(p):
            tabs.append("all")
        return tabs

    async def visible_document(self, did: uuid.UUID, *, for_update: bool = False) -> IssuedDocument:
        stmt = select(IssuedDocument).where(
            IssuedDocument.id == did,
            IssuedDocument.institution_id == self.inst,
            await self.issued_predicate(),
        )
        if for_update:
            stmt = stmt.with_for_update()
        d = (await self.db.execute(stmt)).scalar_one_or_none()
        if d is None:
            raise not_found("Document")
        return d

    def require_type(self, template_type: str) -> None:
        limit = self.type_limit()
        if limit is not None and template_type not in limit:
            raise forbidden(f"Your role does not handle {template_type} documents")

    async def doc_setting(self, key: str, default: Any = None) -> Any:
        v = await self.setting("documents", key)
        return default if v is None else v
