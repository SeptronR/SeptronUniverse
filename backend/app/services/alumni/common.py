"""Shared plumbing of the Phase 29 services (profiles, directory, events, jobs, fundraising, stats) — on the Phase 27
``SupportBase`` (people lookups, department predicates, the ``institution_settings`` side store, ScopeTabs).

**Visibility** (Prompts/29 "Visibility rules" / §29.5): *self* through ``alumni_profiles.user_id = principal.user_id``;
department scope through ``alumni_profiles.program_id → programs.department_id`` (HOD holding ``alumni:view_all`` at
department scope); college scope through the student's college (``college_admin``); institution-wide for
``alumni:view_all`` / ``manage`` at institution scope (coordinator, placement officer, IQAC, registrar, auditor —
the auditor reads with masked contacts). The directory is a separate, consent-projected read (``directory_service``).

Side-store kinds (category ``alumni_meta``): ``profile:<id>`` (claim_status, legacy, consent_directory_fields,
higher_studies, chapter, engagement, completeness, verification / merge history), ``claim:<token>`` (pending claim),
``job:<id>`` (status, reason, clicks, open_to_students, lead_company_id), ``campaign:<id>`` (restricted fund, ledger
account, milestones, public flag), ``donation:<id>`` (reference, wants_80g, refund, receipt history), ``intent:<id>``
(online donation awaiting the gateway), ``idem:<key>`` (Idempotency-Key → intent), ``alumni_event:<id>`` (webinar
link, invites, photos), ``contact:<id>`` (relayed contact requests), ``seq80g:<fy>`` (80G receipt counter).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import false, or_, select, true

from app.enums.alumni import DEFAULT_DIRECTORY_FIELDS
from app.models.academic import Program
from app.models.alumni import AlumniEmploymentHistory, AlumniProfile
from app.models.students import Student
from app.services.student_support.common import (
    SupportBase,
    all_access,
    dept_subquery,
    forbidden,
    is_auditor,
    module_reader,
    not_found,
    now_utc,
    rule,
    scope_ids,
)

__all__ = [
    "AlumniBase",
    "all_access",
    "dept_subquery",
    "financial_year",
    "forbidden",
    "is_auditor",
    "mask",
    "mask_pan",
    "module_reader",
    "not_found",
    "now_utc",
    "rule",
    "scope_ids",
]

META = "alumni_meta"


def mask(value: str | None, keep: int = 3) -> str | None:
    if not value:
        return value
    if "@" in value:
        user, _, domain = value.partition("@")
        return f"{user[:1]}***@{domain}"
    return value[-keep:].rjust(len(value), "*")


def mask_pan(pan: str | None) -> str | None:
    return f"{pan[:2]}XXXXX{pan[-3:]}" if pan and len(pan) == 10 else None


def financial_year(on: date) -> str:
    """Indian FY label: 1 Apr 2026 – 31 Mar 2027 → ``2026-27``."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def rupees(paise: int | None) -> str:
    return f"{(paise or 0) / 100:,.2f}"


class AlumniBase(SupportBase):
    audit_module = "alumni"
    module = "alumni"
    meta_category = META

    # ---- roles ------------------------------------------------------------------------------------------------------
    def coordinator(self) -> bool:
        p = self.principal
        return p is None or bool(getattr(p, "is_super_admin", False)) or p.has("alumni", "manage")

    def require_coordinator(self, *actions: str) -> None:
        self.require_writer()
        if not any(self.can("alumni", a) for a in (*actions, "manage")):
            raise forbidden(f"alumni:{'|'.join((*actions, 'manage'))} required")

    def staff_reader(self) -> bool:
        return module_reader(self.principal, "alumni") or self.can("placement", "manage")

    # ---- self ---------------------------------------------------------------------------------------------------------
    async def my_profile(self, *, lock: bool = False) -> AlumniProfile | None:
        if self.actor_id is None:
            return None
        stmt = select(AlumniProfile).where(
            AlumniProfile.institution_id == self.inst, AlumniProfile.user_id == self.actor_id
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def require_my_profile(self, *, lock: bool = False, verified: bool = False) -> AlumniProfile:
        a = await self.my_profile(lock=lock)
        if a is None:
            raise forbidden("No alumni profile for the caller")
        if verified and not a.is_verified:
            raise rule("Your alumni profile is not verified yet", "VERIFICATION_REQUIRED", 403)
        return a

    # ---- predicates -----------------------------------------------------------------------------------------------------
    async def profile_predicate(self, scope: str | None = None) -> Any:
        """Profiles a caller may read in the managed views: self, department, college, all."""
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return true()
        if scope in (None, "all") and (all_access(p, "alumni") or (self.can("placement", "manage") and not scope)):
            return true()
        parts: list[Any] = []
        if scope in (None, "self", "mine") and self.actor_id is not None:
            parts.append(AlumniProfile.user_id == self.actor_id)
        if module_reader(p, "alumni"):
            if scope in (None, "department") and (scope_ids(p, "department") or scope_ids(p, "faculty")):
                parts.append(
                    AlumniProfile.program_id.in_(select(Program.id).where(Program.department_id.in_(dept_subquery(p))))
                )
            if scope in (None, "college") and scope_ids(p, "college"):
                parts.append(
                    AlumniProfile.student_id.in_(
                        select(Student.id).where(Student.college_id.in_(scope_ids(p, "college")))
                    )
                )
        return or_(*parts) if parts else false()

    async def profile(self, aid: uuid.UUID, *, lock: bool = False, visible: bool = True) -> AlumniProfile:
        stmt = select(AlumniProfile).where(AlumniProfile.id == aid, AlumniProfile.institution_id == self.inst)
        if visible:
            stmt = stmt.where(await self.profile_predicate())
        if lock:
            stmt = stmt.with_for_update()
        a = (await self.db.execute(stmt)).scalar_one_or_none()
        if a is None:
            raise not_found("Alumni profile")
        return a

    # ---- lookups ------------------------------------------------------------------------------------------------------
    async def cards(self, profiles: Sequence[AlumniProfile]) -> dict[uuid.UUID, dict[str, Any]]:
        """``{profile id: {name, registration_number, program, program_code, department_id, college_id}}``."""
        sids = list({a.student_id for a in profiles})
        pids = list({a.program_id for a in profiles if a.program_id})
        students = (
            {s.id: s for s in (await self.db.execute(select(Student).where(Student.id.in_(sids)))).scalars()}
            if sids
            else {}
        )
        programs = (
            {p.id: p for p in (await self.db.execute(select(Program).where(Program.id.in_(pids)))).scalars()}
            if pids
            else {}
        )
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for a in profiles:
            s, pr = students.get(a.student_id), programs.get(a.program_id) if a.program_id else None
            out[a.id] = {
                "name": s.full_name if s else "Alumnus",
                "registration_number": s.registration_number if s else None,
                "college_id": s.college_id if s else None,
                "program": pr.name if pr else None,
                "program_code": pr.code if pr else None,
                "department_id": pr.department_id if pr else None,
            }
        return out

    async def employment(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[AlumniEmploymentHistory]]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(AlumniEmploymentHistory)
                .where(AlumniEmploymentHistory.alumni_id.in_(list(ids)))
                .order_by(AlumniEmploymentHistory.is_current.desc(), AlumniEmploymentHistory.from_on.desc())
            )
        ).scalars()
        out: dict[uuid.UUID, list[AlumniEmploymentHistory]] = {}
        for r in rows:
            out.setdefault(r.alumni_id, []).append(r)
        return out

    async def directory_defaults(self) -> list[str]:
        v = await self.setting("alumni", "directory_default_fields")
        return list(v) if isinstance(v, list) else list(DEFAULT_DIRECTORY_FIELDS)

    async def profile_meta(self, aid: uuid.UUID) -> dict[str, Any]:
        return await self.meta("profile", aid)

    async def alumni_role_grant(self, user_id: uuid.UUID | None) -> bool:
        """Grant the ``alumni`` role (self scope) to the graduate's user — portal login continues on the same account."""
        if user_id is None:
            return False
        from app.models.platform import Role, User, UserRole

        role = (
            await self.db.execute(
                select(Role).where(Role.institution_id == self.inst, Role.slug == "alumni", Role.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if role is None:
            return False
        has = (
            await self.db.execute(
                select(UserRole.id).where(UserRole.user_id == user_id, UserRole.role_id == role.id).limit(1)
            )
        ).scalar_one_or_none()
        if has is None:
            self.db.add(
                UserRole(institution_id=self.inst, user_id=user_id, role_id=role.id, scope_type="self", scope_id=None)
            )
        u = (await self.db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if u is not None and u.user_type == "student":
            u.user_type = "alumni"
        await self.db.flush()
        return has is None
