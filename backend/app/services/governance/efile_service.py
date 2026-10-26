"""e-File — Prompts/33 §33.6 ``efile_service`` ({governance.efile}).

1. Files: ``file_no`` from the ``efile`` sequence, subject / category / priority, attachments and the initial noting
   (the first ``efile_movements`` row, action ``forward`` from the creator to themselves). Movements ``forward`` (to a
   user, or a role resolved to a holder of that role — department / college / institution), ``return`` (to the
   previous sender unless a user is named), ``approve`` / ``reject`` (recorded decision; the file stays with the holder
   who closes or forwards it). Every movement carries a noting and attachments; the sheet is **append-only** (no
   update route — ``PUT`` answers 405). Only the current holder moves a file (administrators reassign).
   Pendency = time with the current holder; ``efile.pendency_sla_days`` reminders and escalation to the holder's
   reporting head (Phase 06 ``reports_to_staff_id``, else HOD) once per day; close with summary; reopen by admin.
   Delegation while on leave rides the Phase 04 workflow delegation rules when a structured ``efile.approval`` route is
   started (``route_user_ids`` on a forward).
2. Inbox (with me), outbox (I moved it, someone else holds it), mine (created by me); search by number / subject;
   notings PDF; linking to entities (RTI request, purchase file, legal case, policy draft).

Visibility: creator, current holder, past holders; ``efile:manage`` / ``view_all`` at institution scope (registrar,
principal, auditor read); ``college_admin`` files created by staff of their college.
"""

import uuid
from typing import Any

from sqlalchemy import exists, func, or_, select

from app.models.governance import Efile, EfileMovement
from app.models.hr import Staff
from app.schemas.governance import (
    EfileClose,
    EfileCreate,
    EfileMove,
    EfileMovementOut,
    EfileOut,
    EfileReopen,
    PendencyRow,
)
from app.services.governance.common import GovernanceBase, forbidden, is_auditor, not_found, now_utc, rule

ENTITY = "efile"
E = "efile"
WF_KEY = "efile.approval"


class EfileService(GovernanceBase):
    audit_module = E

    def admin_e(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and p.has(E, "manage") and self.reader_all(E))

    def visibility_predicate(self) -> Any:
        if self.reader_all(E):
            return None
        me = self.actor_id or uuid.uuid4()
        conds = [
            Efile.created_by == me,
            Efile.current_holder_user_id == me,
            exists().where(
                EfileMovement.efile_id == Efile.id,
                or_(EfileMovement.from_user_id == me, EfileMovement.to_user_id == me),
            ),
        ]
        colleges = self.college_ids()
        if colleges and self.has_any(E, "manage", "view_all"):
            conds.append(
                Efile.created_by.in_(
                    select(Staff.user_id).where(Staff.college_id.in_(colleges), Staff.user_id.is_not(None))
                )
            )
        return or_(*conds)

    async def _row(self, fid: uuid.UUID, *, lock: bool = False) -> Efile:
        stmt = select(Efile).where(Efile.id == fid, Efile.institution_id == self.inst)
        pred = self.visibility_predicate()
        if pred is not None:
            stmt = stmt.where(pred)
        if lock:
            stmt = stmt.with_for_update(of=Efile)
        f = (await self.db.execute(stmt)).scalar_one_or_none()
        if f is None:
            raise not_found("File")
        return f

    async def _last_move(self, fid: uuid.UUID) -> EfileMovement | None:
        return (
            await self.db.execute(
                select(EfileMovement)
                .where(EfileMovement.efile_id == fid)
                .order_by(EfileMovement.moved_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def outs(self, rows: list[Efile], *, full: bool = False) -> list[EfileOut]:
        if not rows:
            return []
        ids = [f.id for f in rows]
        last: dict[uuid.UUID, Any] = {
            r[0]: r[1]
            for r in (
                await self.db.execute(
                    select(EfileMovement.efile_id, func.max(EfileMovement.moved_at))
                    .where(EfileMovement.efile_id.in_(ids))
                    .group_by(EfileMovement.efile_id)
                )
            ).all()
        }
        metas = await self.metas("efile", [str(i) for i in ids])
        sla = await self.gov_int("efile.pendency_sla_days")
        moves: dict[uuid.UUID, list[EfileMovement]] = {}
        if full:
            for mv in (
                await self.db.execute(
                    select(EfileMovement).where(EfileMovement.efile_id.in_(ids)).order_by(EfileMovement.moved_at)
                )
            ).scalars():
                moves.setdefault(mv.efile_id, []).append(mv)
        users = await self.user_names(
            [f.created_by for f in rows]
            + [f.current_holder_user_id for f in rows]
            + [u for mvs in moves.values() for mv in mvs for u in (mv.from_user_id, mv.to_user_id)]
        )
        now = now_utc()
        out = []
        for f in rows:
            since = last.get(f.id) or f.created_at
            days = (now - since).days if f.status != "closed" else 0
            m = metas.get(str(f.id), {})
            out.append(
                EfileOut(
                    id=f.id,
                    file_no=f.file_no,
                    subject=f.subject,
                    category=f.category,
                    priority=f.priority,
                    status=f.status,
                    created_by=f.created_by,
                    creator_name=users.get(f.created_by),
                    current_holder_user_id=f.current_holder_user_id,
                    holder_name=users.get(f.current_holder_user_id) if f.current_holder_user_id else None,
                    pendency_days=days,
                    over_sla=f.status != "closed" and days > sla,
                    linked_entity=m.get("linked_entity"),
                    closed_at=f.closed_at,
                    summary=m.get("summary"),
                    created_at=f.created_at,
                    movements=[
                        EfileMovementOut(
                            id=mv.id,
                            from_user_id=mv.from_user_id,
                            from_name=users.get(mv.from_user_id) if mv.from_user_id else None,
                            to_user_id=mv.to_user_id,
                            to_name=users.get(mv.to_user_id) if mv.to_user_id else None,
                            action=mv.action,
                            noting=mv.noting,
                            attachments=list(mv.attachments or []),
                            moved_at=mv.moved_at,
                        )
                        for mv in moves.get(f.id, [])
                    ],
                )
            )
        return out

    async def list_files(
        self,
        box: str | None = None,
        q: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EfileOut], int]:
        me = self.actor_id or uuid.uuid4()
        stmt = select(Efile).where(Efile.institution_id == self.inst)
        if box == "inbox":
            stmt = stmt.where(Efile.current_holder_user_id == me, Efile.status != "closed")
        elif box == "outbox":
            stmt = stmt.where(
                exists().where(EfileMovement.efile_id == Efile.id, EfileMovement.from_user_id == me),
                or_(Efile.current_holder_user_id.is_(None), Efile.current_holder_user_id != me),
            )
        elif box == "mine":
            stmt = stmt.where(Efile.created_by == me)
        else:
            pred = self.visibility_predicate()
            if pred is not None:
                stmt = stmt.where(pred)
        if q:
            stmt = stmt.where(or_(Efile.file_no.ilike(f"%{q}%"), Efile.subject.ilike(f"%{q}%")))
        if status:
            stmt = stmt.where(Efile.status == status)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.db.execute(stmt.order_by(Efile.updated_at.desc()).limit(limit).offset(offset))).scalars()
        return await self.outs(list(rows)), int(total)

    async def get(self, fid: uuid.UUID) -> EfileOut:
        return (await self.outs([await self._row(fid)], full=True))[0]

    async def create(self, body: EfileCreate) -> EfileOut:
        self.require_writer()
        if not self.has_any(E, "create", "manage"):
            raise forbidden("efile:create required")
        if self.actor_id is None:
            raise forbidden("A signed-in user creates files")
        f = Efile(
            institution_id=self.inst,
            file_no=await self.sequence("efile", "EF"),
            subject=body.subject,
            category=body.category,
            created_by=self.actor_id,
            current_holder_user_id=self.actor_id,
            priority=body.priority,
            status="open",
        )
        self.db.add(f)
        await self.db.flush()
        self.db.add(
            EfileMovement(
                institution_id=self.inst,
                efile_id=f.id,
                from_user_id=self.actor_id,
                to_user_id=self.actor_id,
                noting=body.initial_noting,
                attachments=list(body.attachments),
                action="forward",
            )
        )
        if body.linked_entity:
            await self.put_meta("efile", f.id, {"linked_entity": body.linked_entity.model_dump(mode="json")})
        await self.db.flush()
        await self._audit("create", ENTITY, f.id, None, {"file_no": f.file_no, "subject": f.subject})
        await self._emit("efile.created", {"efile_id": str(f.id), "file_no": f.file_no}, ENTITY, f.id)
        return (await self.outs([f], full=True))[0]

    async def resolve_role(self, role: str, f: Efile) -> uuid.UUID:
        creator = (await self.db.execute(select(Staff).where(Staff.user_id == self.actor_id))).scalar_one_or_none()
        users = await self.role_users(role, creator.department_id if creator else None)
        users = [u for u in users if u != self.actor_id] or users
        if not users:
            raise rule(f"No holder of role {role}", "NO_ROLE_HOLDER", 422)
        return users[0]

    async def move(self, fid: uuid.UUID, body: EfileMove) -> EfileOut:
        self.require_writer()
        f = await self._row(fid, lock=True)
        if f.status == "closed":
            raise rule("The file is closed", "FILE_CLOSED")
        if f.current_holder_user_id != self.actor_id and not self.admin_e():
            raise forbidden("Only the current holder moves the file")
        to_user: uuid.UUID | None = body.to_user_id
        if body.action == "forward":
            if to_user is None and body.to_role:
                to_user = await self.resolve_role(body.to_role, f)
            if to_user is None:
                raise rule("Forward to a user or a role", "NO_RECIPIENT", 422)
        elif body.action == "return":
            if to_user is None:
                prev = (
                    await self.db.execute(
                        select(EfileMovement.from_user_id)
                        .where(EfileMovement.efile_id == f.id, EfileMovement.to_user_id == f.current_holder_user_id)
                        .order_by(EfileMovement.moved_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                to_user = prev if prev and prev != f.current_holder_user_id else f.created_by
        else:  # approve / reject — decision recorded, the file stays with the holder
            if not self.has_any(E, "approve", "manage") and f.current_holder_user_id != self.actor_id:
                raise forbidden("efile:approve required")
            to_user = f.current_holder_user_id
        mv = EfileMovement(
            institution_id=self.inst,
            efile_id=f.id,
            from_user_id=self.actor_id,
            to_user_id=to_user,
            noting=body.noting,
            attachments=list(body.attachments),
            action=body.action,
        )
        self.db.add(mv)
        f.current_holder_user_id = to_user
        f.status = "in_movement"
        await self.db.flush()
        if body.action == "forward" and body.route_user_ids:
            ctx = {f"route_{i + 1}": str(u) for i, u in enumerate(body.route_user_ids[:4])}
            wf = await self.start_workflow(WF_KEY, ENTITY, f.id, f"File {f.file_no} · {f.subject}", ctx)
            if wf:
                m = await self.meta("efile", f.id)
                m["workflow_instance_id"] = str(wf)
                await self.put_meta("efile", f.id, m)
        event = {
            "forward": "efile.moved",
            "return": "efile.returned",
            "approve": "efile.approved",
            "reject": "efile.rejected",
        }[body.action]
        await self._emit(event, {"efile_id": str(f.id), "to_user_id": str(to_user) if to_user else None}, ENTITY, f.id)
        if to_user and to_user != self.actor_id:
            names = await self.user_names([self.actor_id])
            await self._notify(
                "efile.returned" if body.action == "return" else "efile.received",
                [to_user],
                {
                    "file_no": f.file_no,
                    "subject": f.subject,
                    "action": "forwarded" if body.action == "forward" else body.action + "d",
                    "sender": names.get(self.actor_id, "") if self.actor_id else "",
                },
            )
        return (await self.outs([f], full=True))[0]

    async def close(self, fid: uuid.UUID, body: EfileClose) -> EfileOut:
        self.require_writer()
        f = await self._row(fid, lock=True)
        if f.status == "closed":
            raise rule("The file is already closed", "FILE_CLOSED")
        if f.current_holder_user_id != self.actor_id and not self.admin_e():
            raise forbidden("Only the current holder closes the file")
        f.status, f.closed_at = "closed", now_utc()
        m = await self.meta("efile", f.id)
        m["summary"] = body.summary
        await self.put_meta("efile", f.id, m)
        await self.db.flush()
        await self._emit("efile.closed", {"efile_id": str(f.id)}, ENTITY, f.id)
        return (await self.outs([f], full=True))[0]

    async def reopen(self, fid: uuid.UUID, body: EfileReopen) -> EfileOut:
        self.require_writer()
        if not self.admin_e():
            raise forbidden("efile:manage required")
        f = await self._row(fid, lock=True)
        if f.status != "closed":
            raise rule("The file is not closed", "INVALID_TRANSITION")
        f.status, f.closed_at = "in_movement", None
        await self.timeline("efile", f.id, "reopened", reason=body.reason)
        await self.db.flush()
        return (await self.outs([f], full=True))[0]

    async def notings_lines(self, fid: uuid.UUID) -> tuple[str, list[str]]:
        out = await self.get(fid)
        lines = [
            f"File {out.file_no} — {out.subject}",
            f"Category: {out.category or '—'}  ·  priority {out.priority}  ·  status {out.status}",
            "",
        ]
        for i, mv in enumerate(out.movements, 1):
            lines.append(
                f"{i}. {mv.moved_at:%d-%m-%Y %H:%M} · {mv.action} · {mv.from_name or '—'} → {mv.to_name or '—'}"
            )
            lines += [f"     {x}" for x in (mv.noting or "").splitlines()]
            lines.append("")
        if out.summary:
            lines += ["Closing summary:", out.summary]
        return f"notings-{out.file_no.replace('/', '-')}", lines

    async def pendency(self, department_id: uuid.UUID | None = None) -> list[PendencyRow]:
        if not self.reader_all(E) and not self.college_ids():
            raise forbidden("efile:view_all required")
        rows = list(
            (
                await self.db.execute(select(Efile).where(Efile.institution_id == self.inst, Efile.status != "closed"))
            ).scalars()
        )
        outs = await self.outs(rows)
        staff = {
            s.user_id: s
            for s in (
                await self.db.execute(
                    select(Staff).where(
                        Staff.user_id.in_(
                            [o.current_holder_user_id for o in outs if o.current_holder_user_id] or [uuid.uuid4()]
                        )
                    )
                )
            ).scalars()
        }
        agg: dict[uuid.UUID | None, PendencyRow] = {}
        for o in outs:
            s = staff.get(o.current_holder_user_id) if o.current_holder_user_id else None
            if department_id and (s is None or s.department_id != department_id):
                continue
            row = agg.setdefault(
                o.current_holder_user_id,
                PendencyRow(
                    holder_user_id=o.current_holder_user_id,
                    holder_name=o.holder_name,
                    department_id=s.department_id if s else None,
                    files=0,
                    over_sla=0,
                    max_days=0,
                ),
            )
            row.files += 1
            row.over_sla += int(o.over_sla)
            row.max_days = max(row.max_days, o.pendency_days)
        return sorted(agg.values(), key=lambda r: (-r.over_sla, -r.max_days))

    async def pendency_scan(self) -> int:
        """Daily: files beyond the SLA → the holder is reminded and the reporting head alerted (once per day)."""
        rows = list(
            (
                await self.db.execute(select(Efile).where(Efile.institution_id == self.inst, Efile.status != "closed"))
            ).scalars()
        )
        today = str(await self.today())
        n = 0
        for o in await self.outs(rows):
            if not o.over_sla:
                continue
            m = await self.meta("efile", o.id)
            if m.get("escalated_on") == today:
                continue
            head = await self.reporting_head_user(o.current_holder_user_id)
            ctx = {"file_no": o.file_no, "subject": o.subject, "holder": o.holder_name or "", "days": o.pendency_days}
            await self._notify("efile.pending", [o.current_holder_user_id, head], ctx)
            m["escalated_on"] = today
            m.setdefault("escalations", []).append(
                {"on": today, "to": str(head) if head else None, "days": o.pendency_days}
            )
            await self.put_meta("efile", o.id, m)
            await self._emit(
                "efile.pending_escalated",
                {"efile_id": str(o.id), "holder": str(o.current_holder_user_id), "head": str(head) if head else None},
                ENTITY,
                o.id,
            )
            n += 1
        return n

    async def inbox_count(self) -> int:
        if self.actor_id is None:
            return 0
        return int(
            (
                await self.db.execute(
                    select(func.count()).where(
                        Efile.institution_id == self.inst,
                        Efile.current_holder_user_id == self.actor_id,
                        Efile.status != "closed",
                    )
                )
            ).scalar_one()
        )

    async def sla_days(self) -> int:
        return await self.gov_int("efile.pendency_sla_days")
