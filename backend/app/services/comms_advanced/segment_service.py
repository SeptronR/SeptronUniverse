"""Audience segments — Prompts/24 §24.6 ``segment_service``.

``SegmentRules`` compile into SQL over enrolments / students / guardians / staff / hostel and transport allocations /
invoices / attendance summaries, **with the caller's visibility applied at compile time** (HODs → their department,
college admins → their college). The result is a de-duplicated set of users (a guardian of two wards receives once)
with channel reachability (phone → sms / whatsapp, email, active push device, every user → in-app). Saved segments are
the ``comms.segments`` setting (JSON list of ``{id, name, rules, owner_user_id, shared, updated_at}``).
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.enums.comms_advanced import SEGMENT_FIELDS
from app.models.hr import Staff
from app.models.platform import DeviceToken, Role, User, UserRole
from app.models.students import Student, StudentGuardian, StudentProgramEnrollment
from app.schemas.comms_advanced import SavedSegmentIn, SavedSegmentOut, SegmentPreview, SegmentRules
from app.services.comms_advanced.common import CommsBase, now_utc

FIELDS = {f: (t, ops) for f, t, ops in SEGMENT_FIELDS}


@dataclass
class Audience:
    users: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)  # user_id → {name, phone, email, push}

    def reach(self) -> dict[str, int]:
        return {
            "sms": sum(1 for u in self.users.values() if u.get("phone")),
            "whatsapp": sum(1 for u in self.users.values() if u.get("phone")),
            "email": sum(1 for u in self.users.values() if u.get("email")),
            "push": sum(1 for u in self.users.values() if u.get("push")),
            "in_app": len(self.users),
        }


def _cond(col: Any, op: str, value: Any) -> Any:
    if op == "eq":
        return col == value
    if op == "in":
        return col.in_(value if isinstance(value, list) else [value])
    if op == "between" and isinstance(value, list) and len(value) == 2:  # noqa: PLR2004
        return col.between(value[0], value[1])
    if op == "gte":
        return col >= value
    if op == "lte":
        return col <= value
    if op == "is_null":
        return col.is_(None)
    raise APIError(422, ErrorCode.VALIDATION, f"Unsupported operator {op}")


class SegmentService(CommsBase):
    def fields(self) -> list[dict[str, Any]]:
        return [{"field": f, "type": t, "ops": list(ops)} for f, (t, ops) in FIELDS.items()]

    async def _enrolment_ids(self, rules: SegmentRules) -> Any:
        """Active enrolments matching the student-side rules and the caller's unit scope (SQL sub-select)."""
        E = StudentProgramEnrollment
        q = (
            select(E.id)
            .join(Student, Student.id == E.student_id)
            .where(E.institution_id == self.inst, E.status == "active", Student.deleted_at.is_(None))
        )
        scope = await self.unit_scope()
        if "college" in scope:
            q = q.where(E.college_id.in_(scope["college"]))
        if "department" in scope:
            q = q.where(E.department_id.in_(scope["department"] or [uuid.uuid4()]))
        if rules.college_id:
            q = q.where(E.college_id == rules.college_id)
        if rules.program_ids:
            q = q.where(E.program_id.in_(rules.program_ids))
        if rules.batch_ids:
            q = q.where(E.batch_id.in_(rules.batch_ids))
        if rules.department_ids:
            q = q.where(E.department_id.in_(rules.department_ids))
        mapping: dict[str, Any] = {
            "college": E.college_id,
            "department": E.department_id,
            "program": E.program_id,
            "batch": E.batch_id,
            "gender": Student.gender,
            "category": Student.category,
            "status": E.status,
        }

        def compile_one(c: Any) -> Any:
            if c.field in mapping:
                return _cond(mapping[c.field], c.op, c.value)
            if c.field == "hostel":
                from app.models.hostel import HostelAllocation

                return E.id.in_(
                    select(HostelAllocation.student_program_enrollment_id).where(
                        _cond(HostelAllocation.hostel_id, c.op, c.value),
                        HostelAllocation.status.in_(("allotted", "checked_in")),
                    )
                )
            if c.field == "route":
                from app.models.transport import TransportAllocation

                return E.student_id.in_(
                    select(TransportAllocation.person_id).where(
                        TransportAllocation.person_type == "student",
                        _cond(TransportAllocation.route_id, c.op, c.value),
                        TransportAllocation.status.in_(("active", "suspended")),
                    )
                )
            if c.field == "dues_paise":
                from app.models.fees import FeeInvoice

                sub = (
                    select(FeeInvoice.student_program_enrollment_id)
                    .where(
                        FeeInvoice.institution_id == self.inst, FeeInvoice.status.in_(("pending", "partial", "overdue"))
                    )
                    .group_by(FeeInvoice.student_program_enrollment_id)
                )
                return E.id.in_(sub.having(_cond(func.sum(FeeInvoice.balance_paise), c.op, c.value)))
            if c.field == "attendance_pct":
                from app.models.attendance import AttendanceSummary

                return E.id.in_(
                    select(AttendanceSummary.student_program_enrollment_id).where(
                        _cond(AttendanceSummary.pct, c.op, c.value)
                    )
                )
            if c.field == "term_number":
                from app.models.students import StudentTermRecord

                return E.id.in_(
                    select(StudentTermRecord.student_program_enrollment_id).where(
                        _cond(StudentTermRecord.term_number, c.op, c.value)
                    )
                )
            if c.field == "role":
                return Student.user_id.in_(
                    select(UserRole.user_id)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(_cond(Role.slug, c.op, c.value))
                )
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown segment field {c.field}", {"field": c.field})

        if rules.all:
            q = q.where(and_(*[compile_one(c) for c in rules.all]))
        if rules.any:
            q = q.where(or_(*[compile_one(c) for c in rules.any]))
        if rules.hostel_ids:
            from app.models.hostel import HostelAllocation

            q = q.where(
                E.id.in_(
                    select(HostelAllocation.student_program_enrollment_id).where(
                        HostelAllocation.hostel_id.in_(rules.hostel_ids),
                        HostelAllocation.status.in_(("allotted", "checked_in")),
                    )
                )
            )
        if rules.route_ids:
            from app.models.transport import TransportAllocation

            q = q.where(
                E.student_id.in_(
                    select(TransportAllocation.person_id).where(
                        TransportAllocation.person_type == "student",
                        TransportAllocation.route_id.in_(rules.route_ids),
                        TransportAllocation.status.in_(("active", "suspended")),
                    )
                )
            )
        if rules.dues:
            from app.models.fees import FeeInvoice

            dq = select(FeeInvoice.student_program_enrollment_id).where(
                FeeInvoice.institution_id == self.inst,
                FeeInvoice.balance_paise > 0,
                FeeInvoice.status.notin_(("paid", "cancelled", "waived")),
            )
            if rules.dues.overdue_only:
                dq = dq.where(FeeInvoice.due_date < date.today())
            dq = dq.group_by(FeeInvoice.student_program_enrollment_id).having(
                func.sum(FeeInvoice.balance_paise) >= max(rules.dues.min_paise, 1)
            )
            q = q.where(E.id.in_(dq))
        if rules.attendance:
            from app.models.attendance import AttendanceSummary

            aq = select(AttendanceSummary.student_program_enrollment_id).where(
                AttendanceSummary.pct < Decimal(str(rules.attendance.below_pct))
            )
            q = q.where(E.id.in_(aq))
        return q

    async def compile(self, rules: SegmentRules) -> Audience:
        aud = Audience()
        user_ids: set[Any] = set()
        student_side = "student" in rules.person_types or "guardian" in rules.person_types or rules.notify_guardians
        has_student_rules = bool(
            rules.all
            or rules.any
            or rules.program_ids
            or rules.batch_ids
            or rules.department_ids
            or rules.hostel_ids
            or rules.route_ids
            or rules.dues
            or rules.attendance
            or rules.college_id
        )
        if student_side and (has_student_rules or not rules.roles):
            enrol = await self._enrolment_ids(rules)
            students = select(StudentProgramEnrollment.student_id).where(StudentProgramEnrollment.id.in_(enrol))
            if "student" in rules.person_types:
                user_ids |= set(
                    (
                        await self.db.execute(
                            select(Student.user_id).where(Student.id.in_(students), Student.user_id.is_not(None))
                        )
                    ).scalars()
                )
            if "guardian" in rules.person_types or rules.notify_guardians:
                user_ids |= set(
                    (
                        await self.db.execute(
                            select(StudentGuardian.user_id).where(
                                StudentGuardian.student_id.in_(students),
                                StudentGuardian.user_id.is_not(None),
                                StudentGuardian.portal_access.is_(True),
                            )
                        )
                    ).scalars()
                )
        if "staff" in rules.person_types:
            sq = select(Staff.user_id).where(
                Staff.institution_id == self.inst, Staff.user_id.is_not(None), Staff.status == "active"
            )
            scope = await self.unit_scope()
            if "college" in scope:
                sq = sq.where(Staff.college_id.in_(scope["college"]))
            if "department" in scope:
                sq = sq.where(Staff.department_id.in_(scope["department"] or [uuid.uuid4()]))
            if rules.department_ids:
                sq = sq.where(Staff.department_id.in_(rules.department_ids))
            if rules.college_id:
                sq = sq.where(Staff.college_id == rules.college_id)
            user_ids |= {x for x in (await self.db.execute(sq)).scalars() if x}
        if rules.roles:
            rq = (
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.institution_id == self.inst, Role.slug.in_(rules.roles))
            )
            ids = set((await self.db.execute(rq)).scalars())
            scope = await self.unit_scope()
            if scope:  # non-officers only reach role holders inside their unit
                inside = set(
                    (
                        await self.db.execute(
                            select(Staff.user_id).where(
                                Staff.department_id.in_(scope.get("department") or [uuid.uuid4()])
                            )
                        )
                    ).scalars()
                )
                inside |= set(
                    (
                        await self.db.execute(
                            select(Student.user_id).where(
                                Student.id.in_(
                                    select(StudentProgramEnrollment.student_id).where(
                                        StudentProgramEnrollment.id.in_(await self._enrolment_ids(SegmentRules()))
                                    )
                                )
                            )
                        )
                    ).scalars()
                )
                ids &= inside
            user_ids |= ids
        if rules.custom_user_ids:
            custom = set(rules.custom_user_ids)
            if await self.unit_scope():
                allowed = await self.compile(SegmentRules(person_types=["student", "guardian", "staff"]))
                custom &= set(allowed.users)
            user_ids |= custom
        user_ids.discard(None)  # type: ignore[arg-type]
        if not user_ids:
            return aud
        rows = (
            await self.db.execute(
                select(User.id, User.display_name, User.username, User.phone, User.email).where(
                    User.id.in_(user_ids), User.deleted_at.is_(None)
                )
            )
        ).all()
        push = set(
            (
                await self.db.execute(
                    select(DeviceToken.user_id).where(
                        DeviceToken.user_id.in_(user_ids), DeviceToken.is_active.is_(True)
                    )
                )
            ).scalars()
        )
        for uid, name, uname, phone, email in rows:
            aud.users[uid] = {"name": name or uname, "phone": phone, "email": email, "push": uid in push}
        return aud

    async def preview(self, rules: SegmentRules) -> SegmentPreview:
        self.require("bulk", "send")
        aud = await self.compile(rules)
        sample = [
            {"user_id": str(k), "name": v["name"], "phone": ("•••" + str(v["phone"])[-4:]) if v.get("phone") else None}
            for k, v in list(aud.users.items())[:10]
        ]
        return SegmentPreview(count=len(aud.users), by_channel_reachable=aud.reach(), sample=sample)

    # ---- saved segments ----------------------------------------------------------------------------------------------------
    async def _all(self) -> list[dict[str, Any]]:
        v = await self.get_json("comms", "segments", [])
        return list(v) if isinstance(v, list) else []

    def _out(self, s: dict[str, Any]) -> SavedSegmentOut:
        return SavedSegmentOut(
            id=uuid.UUID(s["id"]),
            name=s["name"],
            rules=s.get("rules", {}),
            shared=bool(s.get("shared")),
            owner_user_id=uuid.UUID(s["owner_user_id"]) if s.get("owner_user_id") else None,
            updated_at=s.get("updated_at"),
        )

    async def saved(self) -> list[SavedSegmentOut]:
        self.require("bulk", "send")
        mine = str(self.actor_id)
        return [
            self._out(s)
            for s in await self._all()
            if s.get("shared") or s.get("owner_user_id") == mine or self.can("communication", "bulk")
        ]

    async def get_saved(self, sid: uuid.UUID) -> dict[str, Any]:
        s = next((x for x in await self._all() if x["id"] == str(sid)), None)
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Segment not found")
        return s

    async def save(self, body: SavedSegmentIn, sid: uuid.UUID | None = None) -> SavedSegmentOut:
        self.require("bulk", "send")
        rows = await self._all()
        rec = {
            "id": str(sid or uuid.uuid4()),
            "name": body.name,
            "rules": body.rules.model_dump(mode="json"),
            "shared": body.shared,
            "owner_user_id": str(self.actor_id) if self.actor_id else None,
            "updated_at": now_utc().isoformat(),
        }
        if sid:
            cur = next((x for x in rows if x["id"] == str(sid)), None)
            if cur is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Segment not found")
            if cur.get("owner_user_id") != str(self.actor_id) and not self.can("communication", "bulk"):
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the owner edits a segment")
            rec["owner_user_id"] = cur.get("owner_user_id")
            rows = [rec if x["id"] == str(sid) else x for x in rows]
        else:
            rows.append(rec)
        await self.put_json("comms", "segments", rows)
        await self._emit(
            "comms.segment_saved", {"segment_id": rec["id"], "name": body.name}, "segment", uuid.UUID(str(rec["id"]))
        )
        return self._out(rec)

    async def delete(self, sid: uuid.UUID) -> None:
        self.require("bulk", "send")
        rows = await self._all()
        cur = next((x for x in rows if x["id"] == str(sid)), None)
        if cur is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Segment not found")
        if cur.get("owner_user_id") != str(self.actor_id) and not self.can("communication", "bulk"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the owner deletes a segment")
        await self.put_json("comms", "segments", [x for x in rows if x["id"] != str(sid)])
