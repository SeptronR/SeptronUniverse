"""CQI action register — Prompts/17 §17.6 ``cqi_service`` (feature ``obe.cqi``; no workflow — verification is a role
action).

Visibility ``attainment_scope.cqi_predicate`` (owner / scope units / institution; 404 otherwise). Create needs
``obe:manage`` (HOD, OBE coordinator, IQAC); edits and status moves: the owner or ``obe:manage``; ``planned ⇄
in_progress → done`` (``CQI_TRANSITIONS``; ``done`` needs evidence); ``verify`` (``obe:manage``, not the owner unless
the caller is institution-scoped) moves ``done → verified`` or back to ``in_progress``. ``gap_after`` reads the first
computed run of the action's scope after its creation (programme: the PO row; offering: the mean CO gap) — closure
evidence for NBA Criterion 7. Beat ``cqi.due_reminders`` (weekly) notifies owners of actions due within 7 days or
overdue.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.obe_attainment import CQI_TRANSITIONS
from app.models.academic import Program
from app.models.curriculum import Course
from app.models.hr import Staff
from app.models.obe import OutcomeDefinition
from app.models.obe_attainment import AttainmentRun, CoAttainment, CqiAction, PoAttainment
from app.models.offerings import CourseOffering
from app.repositories.attainment_scope import cqi_predicate
from app.schemas.obe_attainment import CqiActionIn, CqiActionOut, CqiActionUpdate, CqiStatusChange, CqiVerify
from app.services.obe.common import ObeBase, f2

ENTITY = "cqi_action"


def _snap(a: CqiAction) -> dict[str, Any]:
    return {
        "status": a.status,
        "owner_staff_id": str(a.owner_staff_id) if a.owner_staff_id else None,
        "due_on": a.due_on.isoformat() if a.due_on else None,
        "action_text": a.action_text,
        "evidence_url": a.evidence_url,
    }


class CqiService(ObeBase):
    async def _get(self, action_id: uuid.UUID, *, for_update: bool = False) -> CqiAction:
        q = select(CqiAction).where(
            CqiAction.id == action_id, CqiAction.institution_id == self.inst, cqi_predicate(self.principal)
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "CQI action not found")
        return row

    async def _may_edit(self, a: CqiAction) -> None:
        if self.can("obe", "manage") or (a.owner_staff_id and a.owner_staff_id in await self.my_staff_ids()):
            return
        raise APIError(404, ErrorCode.NOT_FOUND, "CQI action not found")

    async def _scope_label(self, scope_type: str, scope_id: uuid.UUID) -> str | None:
        if scope_type == "program":
            return (await self.db.execute(select(Program.code).where(Program.id == scope_id))).scalar_one_or_none()
        if scope_type == "course":
            return (await self.db.execute(select(Course.code).where(Course.id == scope_id))).scalar_one_or_none()
        row = (
            await self.db.execute(
                select(Course.code, CourseOffering.section_code)
                .join(CourseOffering, CourseOffering.course_id == Course.id)
                .where(CourseOffering.id == scope_id)
            )
        ).first()
        return f"{row[0]} {row[1]}" if row else None

    async def _gap_after(self, a: CqiAction) -> float | None:
        if a.scope_type == "program" and a.outcome_id:
            v = (
                await self.db.execute(
                    select(PoAttainment.gap)
                    .join(AttainmentRun, AttainmentRun.id == PoAttainment.run_id)
                    .where(
                        PoAttainment.program_id == a.scope_id,
                        PoAttainment.outcome_id == a.outcome_id,
                        AttainmentRun.run_at > a.created_at,
                    )
                    .order_by(AttainmentRun.run_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return f2(v)
        if a.scope_type == "offering":
            run = (
                await self.db.execute(
                    select(AttainmentRun.id)
                    .where(
                        AttainmentRun.scope_type == "offering",
                        AttainmentRun.scope_id == a.scope_id,
                        AttainmentRun.status == "computed",
                        AttainmentRun.run_at > a.created_at,
                    )
                    .order_by(AttainmentRun.run_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if run:
                return f2(
                    (
                        await self.db.execute(select(func.avg(CoAttainment.gap)).where(CoAttainment.run_id == run))
                    ).scalar()
                )
        return None

    async def _out(self, a: CqiAction) -> CqiActionOut:
        owner = None
        if a.owner_staff_id:
            s = (await self.db.execute(select(Staff).where(Staff.id == a.owner_staff_id))).scalar_one_or_none()
            owner = " ".join(x for x in (s.first_name, s.last_name) if x) if s else None
        outcome = None
        if a.outcome_id:
            outcome = (
                await self.db.execute(select(OutcomeDefinition.code).where(OutcomeDefinition.id == a.outcome_id))
            ).scalar_one_or_none()
        today = await self.today()
        return CqiActionOut(
            id=a.id,
            scope_type=a.scope_type,
            scope_id=a.scope_id,
            scope_label=await self._scope_label(a.scope_type, a.scope_id),
            outcome_id=a.outcome_id,
            outcome=outcome,
            gap=f2(a.gap),
            gap_after=await self._gap_after(a),
            action_text=a.action_text,
            owner_staff_id=a.owner_staff_id,
            owner_name=owner,
            due_on=a.due_on,
            overdue=bool(a.due_on and a.due_on < today and a.status not in ("done", "verified")),
            status=a.status,
            evidence_url=a.evidence_url,
            reviewed_by=a.reviewed_by,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )

    async def list(
        self,
        status: str | None = None,
        owner_staff_id: uuid.UUID | None = None,
        scope_type: str | None = None,
        scope_id: uuid.UUID | None = None,
        mine: bool = False,
    ) -> list[CqiActionOut]:
        q = select(CqiAction).where(CqiAction.institution_id == self.inst, cqi_predicate(self.principal))
        if status:
            q = q.where(CqiAction.status == status)
        if owner_staff_id:
            q = q.where(CqiAction.owner_staff_id == owner_staff_id)
        if scope_type:
            q = q.where(CqiAction.scope_type == scope_type)
        if scope_id:
            q = q.where(CqiAction.scope_id == scope_id)
        if mine:
            q = q.where(CqiAction.owner_staff_id.in_(list(await self.my_staff_ids()) or [uuid.uuid4()]))
        rows = (await self.db.execute(q.order_by(CqiAction.due_on.nulls_last(), CqiAction.created_at))).scalars().all()
        return [await self._out(a) for a in rows]

    async def get(self, action_id: uuid.UUID) -> CqiActionOut:
        return await self._out(await self._get(action_id))

    async def _check_scope(self, scope_type: str, scope_id: uuid.UUID) -> None:
        if scope_type == "offering":
            await self.att_offering(scope_id)
        elif scope_type == "program":
            await self.att_program(scope_id)
        elif (
            await self.db.execute(select(Course.id).where(Course.id == scope_id, Course.institution_id == self.inst))
        ).first() is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")

    async def _check_owner(self, staff_id: uuid.UUID | None) -> None:
        if staff_id is None:
            return
        hit = (
            await self.db.execute(
                select(Staff.id).where(
                    Staff.id == staff_id, Staff.institution_id == self.inst, Staff.deleted_at.is_(None)
                )
            )
        ).first()
        if hit is None:
            raise APIError(422, ErrorCode.VALIDATION, "Owner staff not found", {"code": "UNKNOWN_OWNER"})

    async def create(self, body: CqiActionIn) -> CqiActionOut:
        if not self.can("obe", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "obe:manage required to create CQI actions")
        await self._check_scope(body.scope_type, body.scope_id)
        await self._check_owner(body.owner_staff_id)
        a = CqiAction(
            institution_id=self.inst,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            outcome_id=body.outcome_id,
            gap=body.gap,
            action_text=body.action_text,
            owner_staff_id=body.owner_staff_id,
            due_on=body.due_on,
            status="planned",
        )
        self.db.add(a)
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit("cqi_create", ENTITY, a.id, None, _snap(a))
        await self._emit("cqi.action_created", {"id": str(a.id), "scope_type": a.scope_type}, ENTITY, a.id)
        await self._notify_owner(a, "cqi.action_assigned")
        return await self._out(a)

    async def _notify_owner(self, a: CqiAction, event: str) -> None:
        if not a.owner_staff_id:
            return
        uid = (await self.db.execute(select(Staff.user_id).where(Staff.id == a.owner_staff_id))).scalar_one_or_none()
        await self._notify(
            event,
            [uid],
            {
                "action": a.action_text[:80],
                "due": a.due_on.isoformat() if a.due_on else "—",
                "scope": await self._scope_label(a.scope_type, a.scope_id) or a.scope_type,
            },
        )

    async def update(self, action_id: uuid.UUID, body: CqiActionUpdate) -> CqiActionOut:
        a = await self._get(action_id, for_update=True)
        await self._may_edit(a)
        if a.status == "verified":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Verified actions are closed")
        old = _snap(a)
        data = body.model_dump(exclude_unset=True)
        if "owner_staff_id" in data:
            if not self.can("obe", "manage"):
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the OBE office reassigns actions")
            await self._check_owner(data["owner_staff_id"])
        for k, v in data.items():
            setattr(a, k, v)
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit("cqi_update", ENTITY, a.id, old, _snap(a))
        await self._emit("cqi.action_updated", {"id": str(a.id), "status": a.status}, ENTITY, a.id)
        if "owner_staff_id" in data:
            await self._notify_owner(a, "cqi.action_assigned")
        return await self._out(a)

    async def change_status(self, action_id: uuid.UUID, body: CqiStatusChange) -> CqiActionOut:
        a = await self._get(action_id, for_update=True)
        await self._may_edit(a)
        if body.status not in CQI_TRANSITIONS.get(a.status, ()):
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Cannot move a {a.status} action to {body.status}",
                {"code": "INVALID_TRANSITION", "from": a.status, "to": body.status},
            )
        if body.evidence_url:
            a.evidence_url = body.evidence_url
        if body.status == "done" and not a.evidence_url:
            raise APIError(
                422, ErrorCode.VALIDATION, "Attach evidence before marking done", {"code": "EVIDENCE_REQUIRED"}
            )
        old = _snap(a)
        a.status = body.status
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit("cqi_status", ENTITY, a.id, old, {**_snap(a), "comment": body.comment})
        await self._emit("cqi.action_updated", {"id": str(a.id), "status": a.status}, ENTITY, a.id)
        return await self._out(a)

    async def upload_evidence(
        self, action_id: uuid.UUID, filename: str, data: bytes, content_type: str | None
    ) -> CqiActionOut:
        """Store an evidence file (≤ 10 MB) under ``<institution>/cqi-evidence/`` and link it to the action."""
        from app.core.files import build_key, storage

        a = await self._get(action_id, for_update=True)
        await self._may_edit(a)
        if a.status == "verified":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Verified actions are closed")
        if not data or len(data) > 10 * 1024 * 1024:
            raise APIError(422, ErrorCode.VALIDATION, "Evidence must be 1 byte – 10 MB", {"code": "FILE_SIZE"})
        safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._-")[-80:] or "evidence"
        key = build_key(self.inst, "cqi-evidence", f"{a.id.hex[:8]}-{uuid.uuid4().hex[:6]}-{safe}")
        await storage.put(key, data, content_type)
        old = _snap(a)
        a.evidence_url = key
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit("cqi_evidence", ENTITY, a.id, old, _snap(a))
        return await self._out(a)

    async def verify(self, action_id: uuid.UUID, body: CqiVerify) -> CqiActionOut:
        if not self.can("obe", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "obe:manage required to verify")
        a = await self._get(action_id, for_update=True)
        if a.status != "done":
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "Only done actions can be verified",
                {"code": "NOT_DONE", "status": a.status},
            )
        old = _snap(a)
        a.status = "verified" if body.approve else "in_progress"
        a.reviewed_by = self.actor_id
        await self.db.flush()
        await self.db.refresh(a)
        await self._audit("cqi_verify", ENTITY, a.id, old, {**_snap(a), "comment": body.comment})
        if body.approve:
            await self._emit("cqi.action_verified", {"id": str(a.id)}, ENTITY, a.id)
            await self._notify_owner(a, "cqi.action_verified")
        else:
            await self._emit("cqi.action_updated", {"id": str(a.id), "status": a.status}, ENTITY, a.id)
        return await self._out(a)

    async def due_reminders(self) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(CqiAction).where(
                        CqiAction.institution_id == self.inst,
                        CqiAction.status.in_(("planned", "in_progress")),
                        CqiAction.due_on.is_not(None),
                        CqiAction.due_on <= today + timedelta(days=7),
                        CqiAction.owner_staff_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for a in rows:
            await self._notify_owner(a, "cqi.due_reminder")
        return len(rows)

    async def summary(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(CqiAction.status, func.count())
                .where(CqiAction.institution_id == self.inst)
                .group_by(CqiAction.status)
            )
        ).all()
        return {str(s): int(n) for s, n in rows}
