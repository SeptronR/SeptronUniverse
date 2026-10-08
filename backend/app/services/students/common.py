"""Shared plumbing of the Phase 07 services: tenant, repositories, audit, outbox events, notifications, the
institution's local date, pack and settings, the current academic term / year of a college and response builders that
batch-load the related rows of a page of students / enrolments / holds."""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.authz.masking import mask_pii
from app.core.errors import APIError, ErrorCode
from app.core.notifications.notify import notify_event
from app.core.packs import get_pack
from app.core.packs.base import RegulatoryPack
from app.core.tenancy import today_for
from app.models.academic import AcademicTerm, AcademicYear
from app.models.platform import Institution
from app.models.students import Student, StudentHold, StudentProgramEnrollment, StudentTermRecord
from app.repositories.academic_session_repository import AcademicTermRepository
from app.repositories.enrollment_repository import EnrollmentRepository
from app.repositories.guardian_repository import GuardianRepository
from app.repositories.hold_repository import HoldRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.term_record_repository import TermRecordRepository
from app.schemas.students import EnrollmentResponse, HoldResponse, StudentListItem, TermRecordResponse
from app.services.institution.context import tenant_id

HOLD_LABELS = {
    "registration": "Registration",
    "exam": "Examination",
    "transcript": "Transcript",
    "graduation": "Graduation",
    "hostel": "Hostel",
    "library": "Library",
    "all": "All-actions",
}


def snap(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        v = getattr(obj, k, None)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, date | datetime):
            v = v.isoformat()
        out[k] = v
    return out


class SystemActor:
    """Audit actor for institution-level work without a signed-in user (Beat jobs, rollover hooks, public routes)."""

    def __init__(self, institution_id: uuid.UUID):
        self.institution_id = institution_id
        self.id = None
        self.impersonator_id = None
        self.is_super_admin = False
        self.scopes: list[tuple[str, uuid.UUID | None]] = [("institution", None)]

    def has(self, module: str, action: str) -> bool:
        return True


class StudentServiceBase:
    audit_module = "students"

    def __init__(
        self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: uuid.UUID | None = None
    ):
        self.db, self.principal, self.request = db, principal, request
        self.inst = institution_id or tenant_id(principal, request)
        self.students = StudentRepository(db, principal, self.inst)
        self.enrollments = EnrollmentRepository(db, principal, self.inst)
        self.terms = TermRecordRepository(db, self.inst)
        self.holds = HoldRepository(db, principal, self.inst)
        self.guardians = GuardianRepository(db, self.inst)
        self._institution: Institution | None = None
        self._pack: RegulatoryPack | None = None

    # ---- context ------------------------------------------------------------------------------------------------
    @property
    def actor_id(self) -> uuid.UUID | None:
        return getattr(self.principal, "id", None)

    def can(self, module: str, action: str) -> bool:
        p = self.principal
        return p is None or bool(getattr(p, "is_super_admin", False)) or bool(p.has(module, action))

    async def institution(self) -> Institution:
        if self._institution is None:
            self._institution = (
                await self.db.execute(select(Institution).where(Institution.id == self.inst))
            ).scalar_one()
        return self._institution

    async def pack(self) -> RegulatoryPack:
        if self._pack is None:
            self._pack = get_pack((await self.institution()).regulatory_pack)
        return self._pack

    async def today(self) -> date:
        return today_for(await self.institution())

    async def setting(self, category: str, key: str, college_id: uuid.UUID | None = None) -> Any:
        from app.services.settings_service import SettingsService

        return await SettingsService(self.db).value(self.inst, category, key, college_id)

    async def current_term(self, college_id: uuid.UUID | None) -> AcademicTerm | None:
        return await AcademicTermRepository(self.db, self.principal, self.inst).get_current_term(self.inst, college_id)

    async def require_current_term(self, college_id: uuid.UUID | None) -> AcademicTerm:
        term = await self.current_term(college_id)
        if term is None:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "No current academic term — set one under Academic years first",
                {"reason": "no_current_term"},
            )
        return term

    async def current_year(self, college_id: uuid.UUID | None) -> AcademicYear | None:
        term = await self.current_term(college_id)
        if term is None:
            return None
        return await self.terms.year_of(term)

    async def required_undertakings(self, college_id: uuid.UUID | None = None) -> list[str]:
        configured = await self.setting("students", "undertakings_required", college_id)
        if isinstance(configured, list) and configured:
            return [str(x) for x in configured]
        return list((await self.pack()).students.required_undertakings)

    async def adult_age(self) -> int:
        return int(await self.setting("students", "adult_age") or (await self.pack()).students.majority_age)

    async def is_adult(self, dob: date | None) -> bool:
        if dob is None:
            return True
        today = await self.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return age >= await self.adult_age()

    # ---- side effects ---------------------------------------------------------------------------------------------
    async def _audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID | None,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        module: str | None = None,
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal or SystemActor(self.inst),
            module=module or self.audit_module,
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=old,
            new=new,
            request=self.request,
        )

    async def _emit(
        self, event_type: str, payload: dict[str, Any], aggregate_type: str, aggregate_id: uuid.UUID | None
    ) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload=payload,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_user_id=self.actor_id,
        )

    async def _notify(
        self,
        event_type: str,
        user_ids: Sequence[uuid.UUID | None],
        context: dict[str, Any],
        *,
        guardians: bool = False,
        **kw: Any,
    ) -> None:
        ids = [str(u) for u in user_ids if u]
        audience = kw.pop("audience", None) or {"user_ids": ids}
        if guardians:
            audience["include_guardians"] = True
        if not audience.get("user_ids") and not audience.get("roles"):
            return
        await notify_event(
            self.db, self.inst, event_type, audience=audience, context=context, actor_user_id=self.actor_id, **kw
        )

    # ---- response builders ---------------------------------------------------------------------------------------
    async def list_items(self, rows: Sequence[Student], *, mask: bool = True) -> list[StudentListItem]:
        """Decorate a page of students with their current enrolment, latest term record, open holds and labels."""
        rows = list(rows)
        enrolments = await self.enrollments.current_for([s.id for s in rows])
        latest = await self.terms.latest_for([e.id for e in enrolments.values()])
        holds = await self.holds.open_counts([e.id for e in enrolments.values()])
        colleges = await self.students.college_rows([s.college_id for s in rows])
        programs = await self.students.program_rows([e.program_id for e in enrolments.values()])
        batches = await self.students.batch_rows([e.batch_id for e in enrolments.values()])
        depts = await self.students.department_rows([e.department_id for e in enrolments.values()])
        sections = await self.students.section_rows([r.section_id for r in latest.values()])
        wards = await self.ward_ids()
        out: list[StudentListItem] = []
        for s in rows:
            item = StudentListItem.model_validate(s)
            item.full_name = s.full_name
            item.college_code = colleges[s.college_id].code if s.college_id in colleges else None
            e = enrolments.get(s.id)
            if e is not None:
                rec = latest.get(e.id)
                item.program_id, item.batch_id = e.program_id, e.batch_id
                item.program_code = programs[e.program_id].code if e.program_id in programs else None
                item.batch_code = batches[e.batch_id].code if e.batch_id in batches else None
                item.department_code = depts[e.department_id].code if e.department_id in depts else None
                item.enrollment_status, item.academic_standing = e.status, e.academic_standing
                item.open_holds = holds.get(e.id, 0)
                if rec is not None:
                    item.term_number = rec.term_number
                    section = sections.get(rec.section_id) if rec.section_id else None
                    item.section_name = section.name if section else None
            item.is_self = s.user_id is not None and s.user_id == self.actor_id
            item.is_ward = s.id in wards
            out.append(item if (item.is_self or not mask) else mask_pii(item, self.principal, "students"))
        return out

    async def ward_ids(self) -> set[uuid.UUID]:
        if self.actor_id is None or not self.can("students", "view"):
            return set()
        return await self.guardians.ward_ids(self.actor_id)

    async def enrollment_responses(self, rows: Sequence[StudentProgramEnrollment]) -> list[EnrollmentResponse]:
        rows = list(rows)
        latest = await self.terms.latest_for([e.id for e in rows])
        programs = await self.students.program_rows([e.program_id for e in rows])
        batches = await self.students.batch_rows([e.batch_id for e in rows])
        depts = await self.students.department_rows([e.department_id for e in rows])
        sections = await self.students.section_rows([r.section_id for r in latest.values()])
        holds = await self.holds.open_counts([e.id for e in rows])
        reg_codes = await self._regulation_codes([e.program_regulation_id for e in rows])
        out = []
        for e in rows:
            r = EnrollmentResponse.model_validate(e)
            p = programs.get(e.program_id)
            r.program_code, r.program_name = (p.code, p.name) if p else (None, None)
            r.total_terms = p.total_terms if p else None
            b = batches.get(e.batch_id)
            r.batch_code = b.code if b else None
            d = depts.get(e.department_id)
            r.department_code = d.code if d else None
            r.regulation_code = reg_codes.get(e.program_regulation_id)
            rec = latest.get(e.id)
            if rec is not None:
                r.current_term_number, r.section_id = rec.term_number, rec.section_id
                section = sections.get(rec.section_id) if rec.section_id else None
                r.section_name = section.name if section else None
            r.open_holds = holds.get(e.id, 0)
            out.append(r)
        return out

    async def _regulation_codes(self, pr_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        from app.models.academic import ProgramRegulation, Regulation

        clean = [i for i in pr_ids if i]
        if not clean:
            return {}
        rows = (
            await self.db.execute(
                select(ProgramRegulation.id, Regulation.code)
                .join(Regulation, Regulation.id == ProgramRegulation.regulation_id)
                .where(ProgramRegulation.id.in_(clean))
            )
        ).all()
        return {r[0]: r[1] for r in rows}

    async def term_record_responses(self, rows: Sequence[StudentTermRecord]) -> list[TermRecordResponse]:
        rows = list(rows)
        meta = await self.terms.term_meta([r.term_id for r in rows])
        sections = await self.students.section_rows([r.section_id for r in rows])
        out = []
        for rec in rows:
            r = TermRecordResponse.model_validate(rec)
            r.term_name, r.academic_year_name = meta.get(rec.term_id, (None, None))
            section = sections.get(rec.section_id) if rec.section_id else None
            r.section_name = section.name if section else None
            out.append(r)
        return out

    async def hold_responses(self, rows: Sequence[StudentHold]) -> list[HoldResponse]:
        rows = list(rows)
        enrolment_ids = list({h.student_program_enrollment_id for h in rows})
        enrol_rows = {}
        if enrolment_ids:
            enrol_rows = {
                e.id: e
                for e in (
                    await self.db.execute(
                        select(StudentProgramEnrollment).where(StudentProgramEnrollment.id.in_(enrolment_ids))
                    )
                ).scalars()
            }
        student_rows = {}
        sids = list({e.student_id for e in enrol_rows.values()})
        if sids:
            student_rows = {
                s.id: s for s in (await self.db.execute(select(Student).where(Student.id.in_(sids)))).scalars()
            }
        users = await self.students.users([h.placed_by for h in rows] + [h.released_by for h in rows])
        reasons = await self.holds.release_reasons([h.id for h in rows if h.released_at is not None])
        out = []
        for h in rows:
            r = HoldResponse.model_validate(h)
            e = enrol_rows.get(h.student_program_enrollment_id)
            s = student_rows.get(e.student_id) if e else None
            if s is not None:
                r.student_id, r.registration_number, r.student_name = s.id, s.registration_number, s.full_name
            placer = users.get(h.placed_by)
            r.placed_by_name = (placer.display_name or placer.username) if placer else "system"
            releaser = users.get(h.released_by) if h.released_by else None
            r.released_by_name = (releaser.display_name or releaser.username) if releaser else None
            r.release_reason = reasons.get(h.id)
            r.is_open = h.released_at is None
            r.can_release = r.is_open and self.may_manage_hold_type(h.hold_type)
            out.append(r)
        return out

    async def workflow_instances(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, Any]:
        from app.models.platform import WorkflowInstance

        clean = [i for i in ids if i]
        if not clean:
            return {}
        rows = (await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id.in_(clean)))).scalars().all()
        return {r.id: r for r in rows}

    async def actionable(self, ids: Sequence[uuid.UUID | None]) -> set[uuid.UUID]:
        """Workflow instances with an open step the caller may act on (directly, by role pool or after escalation)."""
        from app.models.platform import WorkflowStep

        clean = [i for i in ids if i]
        if not clean or self.principal is None:
            return set()
        rows = (
            await self.db.execute(
                select(
                    WorkflowStep.instance_id,
                    WorkflowStep.approver_user_id,
                    WorkflowStep.approver_role_slug,
                    WorkflowStep.escalated_to,
                ).where(WorkflowStep.instance_id.in_(clean), WorkflowStep.status.in_(("pending", "escalated")))
            )
        ).all()
        roles = set(getattr(self.principal, "roles", []) or [])
        out = set()
        for iid, user_id, role_slug, escalated_to in rows:
            if user_id == self.actor_id or escalated_to == self.actor_id or (user_id is None and role_slug in roles):
                out.add(iid)
        return out

    def may_manage_hold_type(self, hold_type: str) -> bool:
        """``students:holds`` places/releases every hold type; the library (``library:manage``) and hostel offices
        (``hostel:manage``) only their own type (Prompts/07 visibility table: librarian / warden place library / hostel
        holds). Fee-sourced holds arrive with Phase 12."""
        if self.can("students", "holds"):
            return True
        own = {"library": ("library", "manage"), "hostel": ("hostel", "manage")}.get(hold_type)
        return bool(own and self.principal is not None and self.principal.has(*own))


def now_utc() -> datetime:
    return datetime.now(UTC)
