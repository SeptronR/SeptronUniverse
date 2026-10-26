"""Statutory / AG audit paras — Prompts/33 §33.6 ``audit_para_service`` ({governance.audit_paras}).

Paras hang off a Phase 32 ``audit_registers`` row whose ``audit_type`` is ``financial_statutory`` or ``ag`` (other
types → 422 ``AUDIT_TYPE``): description, amount, owner (finance / department staff), replies with attachments
(``para:<id>.replies``; the latest reply also in ``reply_text``), status ``open → replied → settled | dropped``,
compliance report per register, ageing dashboard (0–30 / 31–90 / 91–180 / 180+ days), open paras offered to the
Finance Committee agenda, NAAC 6.4.x evidence through ``audit_para.settled``. Writers: ``governance:audit_paras``
(accountant / finance officer) and ``governance:manage``; owners reply to their paras; readers ``view_all``.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.enums.governance import PARA_AUDIT_TYPES
from app.models.accreditation import AuditRegister
from app.models.governance import AuditPara
from app.schemas.governance import (
    AuditParaIn,
    AuditParaOut,
    AuditParaUpdate,
    ParaDashboard,
    ParaReply,
    ParaStatusUpdate,
)
from app.services.governance.common import GovernanceBase, forbidden, is_auditor, not_found, now_utc, rule

ENTITY = "audit_para"


class AuditParaService(GovernanceBase):
    def manager(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and (p.has("governance", "audit_paras") or self.admin()))

    def can_read(self) -> bool:
        return self.manager() or self.reader_all()

    def require_manager(self) -> None:
        self.require_writer()
        if not self.manager():
            raise forbidden("governance:audit_paras required")

    async def register(self, rid: uuid.UUID) -> AuditRegister:
        r = (
            await self.db.execute(
                select(AuditRegister).where(AuditRegister.id == rid, AuditRegister.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Audit register")
        if r.audit_type not in PARA_AUDIT_TYPES:
            raise rule("Paras are tracked for financial statutory / AG audits only", "AUDIT_TYPE", 422)
        return r

    async def _row(self, pid: uuid.UUID, *, lock: bool = False) -> AuditPara:
        stmt = select(AuditPara).where(AuditPara.id == pid, AuditPara.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Audit para")
        if not self.can_read():
            sid = await self.my_staff_id()
            if sid is None or r.owner_staff_id != sid:
                raise not_found("Audit para")
        return r

    async def outs(self, rows: list[AuditPara]) -> list[AuditParaOut]:
        regs = {
            r.id: r
            for r in (
                await self.db.execute(
                    select(AuditRegister).where(
                        AuditRegister.id.in_({x.audit_register_id for x in rows} or {uuid.uuid4()})
                    )
                )
            ).scalars()
        }
        metas = await self.metas("para", [str(r.id) for r in rows])
        names = await self.staff_names([r.owner_staff_id for r in rows])
        today = await self.today()
        out = []
        for r in rows:
            reg = regs.get(r.audit_register_id)
            m = metas.get(str(r.id), {})
            out.append(
                AuditParaOut(
                    id=r.id,
                    audit_register_id=r.audit_register_id,
                    audit_type=reg.audit_type if reg else None,
                    period_label=reg.period_label if reg else None,
                    para_no=r.para_no,
                    description=r.description,
                    amount_paise=r.amount_paise,
                    owner_staff_id=r.owner_staff_id,
                    owner_name=names.get(r.owner_staff_id) if r.owner_staff_id else None,
                    reply_text=r.reply_text,
                    replies=list(m.get("replies") or []),
                    status=r.status,
                    due_on=date.fromisoformat(m["due_on"]) if m.get("due_on") else None,
                    age_days=(today - r.created_at.date()).days,
                    created_at=r.created_at,
                )
            )
        return out

    async def list_paras(
        self, audit_register_id: uuid.UUID | None = None, status: str | None = None, mine: bool = False
    ) -> list[AuditParaOut]:
        stmt = select(AuditPara).where(AuditPara.institution_id == self.inst)
        if mine or not self.can_read():
            stmt = stmt.where(AuditPara.owner_staff_id == (await self.my_staff_id() or uuid.uuid4()))
        if audit_register_id:
            stmt = stmt.where(AuditPara.audit_register_id == audit_register_id)
        if status:
            stmt = stmt.where(AuditPara.status == status)
        rows = (await self.db.execute(stmt.order_by(AuditPara.created_at))).scalars()
        return await self.outs(list(rows))

    async def open_paras(self, limit: int = 20) -> list[AuditParaOut]:
        rows = (
            await self.db.execute(
                select(AuditPara)
                .where(AuditPara.institution_id == self.inst, AuditPara.status.in_(("open", "replied")))
                .order_by(AuditPara.created_at)
                .limit(limit)
            )
        ).scalars()
        return await self.outs(list(rows))

    async def get(self, pid: uuid.UUID) -> AuditParaOut:
        return (await self.outs([await self._row(pid)]))[0]

    async def create(self, body: AuditParaIn) -> AuditParaOut:
        self.require_manager()
        reg = await self.register(body.audit_register_id)
        if (
            await self.db.execute(
                select(AuditPara.id).where(AuditPara.audit_register_id == reg.id, AuditPara.para_no == body.para_no)
            )
        ).first():
            raise rule("Para number already recorded for this audit", "DUPLICATE_PARA")
        r = AuditPara(
            institution_id=self.inst,
            audit_register_id=reg.id,
            para_no=body.para_no,
            description=body.description,
            amount_paise=body.amount_paise,
            owner_staff_id=body.owner_staff_id,
            status="open",
        )
        self.db.add(r)
        await self.db.flush()
        if body.due_on:
            await self.put_meta("para", r.id, {"due_on": str(body.due_on)})
        await self._audit("create", ENTITY, r.id, None, {"para_no": r.para_no, "register": str(reg.id)})
        await self._emit("audit_para.created", {"para_id": str(r.id), "audit_register_id": str(reg.id)}, ENTITY, r.id)
        if r.owner_staff_id:
            await self._notify(
                "audit_para.assigned",
                [await self.staff_user(r.owner_staff_id)],
                {"para_no": r.para_no, "audit": f"{reg.audit_type} {reg.period_label}"},
            )
        return (await self.outs([r]))[0]

    async def update(self, pid: uuid.UUID, body: AuditParaUpdate) -> AuditParaOut:
        self.require_manager()
        r = await self._row(pid, lock=True)
        data = body.model_dump(exclude_unset=True)
        due = data.pop("due_on", None)
        for k, v in data.items():
            setattr(r, k, v)
        if due is not None:
            m = await self.meta("para", r.id)
            m["due_on"] = str(due)
            await self.put_meta("para", r.id, m)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def reply(self, pid: uuid.UUID, body: ParaReply) -> AuditParaOut:
        self.require_writer()
        r = await self._row(pid, lock=True)
        sid = await self.my_staff_id()
        if not (self.manager() or (sid is not None and r.owner_staff_id == sid)):
            raise forbidden("Only the para owner or finance replies")
        if r.status in ("settled", "dropped"):
            raise rule(f"The para is {r.status}", "INVALID_TRANSITION")
        m = await self.meta("para", r.id)
        m.setdefault("replies", []).append(
            {
                "text": body.reply_text,
                "attachments": list(body.attachments),
                "by": str(self.actor_id) if self.actor_id else None,
                "at": now_utc().isoformat(),
            }
        )
        await self.put_meta("para", r.id, m)
        r.reply_text, r.status = body.reply_text, "replied"
        await self.db.flush()
        await self._emit("audit_para.replied", {"para_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def set_status(self, pid: uuid.UUID, body: ParaStatusUpdate) -> AuditParaOut:
        self.require_manager()
        r = await self._row(pid, lock=True)
        if r.status in ("settled", "dropped") and body.status != r.status:
            raise rule(f"The para is {r.status}", "INVALID_TRANSITION")
        old = r.status
        r.status = body.status
        await self.timeline("para", r.id, f"status:{body.status}", remarks=body.remarks)
        await self.db.flush()
        await self._audit("status", ENTITY, r.id, {"status": old}, {"status": r.status})
        if r.status == "settled":
            await self._emit("audit_para.settled", {"para_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def dashboard(self) -> ParaDashboard:
        if not self.can_read():
            raise forbidden("governance:audit_paras or view_all required")
        rows = list((await self.db.execute(select(AuditPara).where(AuditPara.institution_id == self.inst))).scalars())
        today = await self.today()
        by_status: dict[str, int] = {}
        ageing = {"0-30": 0, "31-90": 0, "91-180": 0, "180+": 0}
        amount = 0
        for r in rows:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            if r.status in ("open", "replied"):
                age = (today - r.created_at.date()).days
                ageing["0-30" if age <= 30 else "31-90" if age <= 90 else "91-180" if age <= 180 else "180+"] += 1
                amount += int(r.amount_paise or 0)
        per = (
            await self.db.execute(
                select(
                    AuditRegister.id,
                    AuditRegister.audit_type,
                    AuditRegister.period_label,
                    AuditPara.status,
                    func.count(),
                )
                .join(AuditPara, AuditPara.audit_register_id == AuditRegister.id)
                .where(AuditRegister.institution_id == self.inst)
                .group_by(AuditRegister.id, AuditRegister.audit_type, AuditRegister.period_label, AuditPara.status)
            )
        ).all()
        regs: dict[uuid.UUID, dict[str, Any]] = {}
        for rid, t, period, status, n in per:
            regs.setdefault(
                rid, {"audit_register_id": str(rid), "audit_type": t, "period_label": period, "counts": {}}
            )["counts"][status] = int(n)
        return ParaDashboard(
            by_status=by_status, ageing=ageing, amount_open_paise=amount, by_register=list(regs.values())
        )

    async def due_reminders(self) -> int:
        cutoff = now_utc() - timedelta(days=30)
        rows = (
            await self.db.execute(
                select(AuditPara).where(
                    AuditPara.institution_id == self.inst,
                    AuditPara.status == "open",
                    AuditPara.created_at <= cutoff,
                    AuditPara.owner_staff_id.is_not(None),
                )
            )
        ).scalars()
        today = await self.today()
        n = 0
        for r in rows:
            await self._notify(
                "audit_para.due",
                [await self.staff_user(r.owner_staff_id)],
                {
                    "para_no": r.para_no,
                    "audit": str(r.audit_register_id)[:8],
                    "days": (today - r.created_at.date()).days,
                },
            )
            n += 1
        return n
