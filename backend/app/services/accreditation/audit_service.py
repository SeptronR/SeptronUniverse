"""Audit registers — Prompts/32 §32.6 ``audit_service`` ({accreditation.audit_registers}) and the
``audit_register_repository``.

Registers per audit type / period (academic & administrative, green / energy / environment, gender, financial
statutory, AG) with the report upload and the JSON finding list (``no, text, owner_staff_id, due_on, status,
action_taken``); a register closes when every finding is closed. Phase 33 ``audit_paras`` link to the
``financial_statutory | ag`` registers. Finding owners (HOD) see and update the registers holding their findings;
IQAC / institution readers see all. Weekly overdue-finding reminders."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.models.accreditation import AuditRegister
from app.schemas.accreditation import (
    AuditDashboardOut,
    AuditFinding,
    AuditRegisterIn,
    AuditRegisterOut,
    AuditRegisterUpdate,
    FindingUpdate,
)
from app.services.accreditation.common import AccreditationBase, forbidden, not_found, rule


class AuditService(AccreditationBase):
    def require_reader(self) -> None:
        if not (self.can(self.module, "view") or self.can(self.module, "view_all") or self.can(self.module, "manage")):
            raise forbidden("accreditation:view required")

    async def _owner_ids(self) -> set[str]:
        """Staff whose findings the caller may see: self, plus department staff for HODs."""
        out: set[str] = set()
        me = await self.my_staff_id()
        if me:
            out.add(str(me))
        depts = await self.resolved_dept_ids()
        if depts:
            out.update(str(s) for s in await self.dept_staff_ids(depts))
        return out

    def out(self, r: AuditRegister) -> AuditRegisterOut:
        findings = [AuditFinding(**f) for f in r.findings or []]
        return AuditRegisterOut(
            id=r.id,
            audit_type=r.audit_type,
            period_label=r.period_label,
            auditor=r.auditor,
            report_url=r.report_url,
            findings=findings,
            status=r.status,
            open_findings=sum(1 for f in findings if f.status != "closed"),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )

    async def query(
        self, audit_type: str | None = None, period: str | None = None, status: str | None = None
    ) -> list[AuditRegisterOut]:
        self.require_reader()
        stmt = select(AuditRegister).where(AuditRegister.institution_id == self.inst)
        if audit_type:
            stmt = stmt.where(AuditRegister.audit_type == audit_type)
        if period:
            stmt = stmt.where(AuditRegister.period_label == period)
        if status:
            stmt = stmt.where(AuditRegister.status == status)
        rows = list((await self.db.execute(stmt.order_by(AuditRegister.created_at.desc()))).scalars().all())
        if not (self.reader_all() or self.iqac()):
            owners = await self._owner_ids()
            rows = [r for r in rows if any(str(f.get("owner_staff_id")) in owners for f in r.findings or [])]
        return [self.out(r) for r in rows]

    async def row(self, aid: uuid.UUID, *, lock: bool = False) -> AuditRegister:
        stmt = select(AuditRegister).where(AuditRegister.id == aid, AuditRegister.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Audit register")
        if not (self.reader_all() or self.iqac()):
            owners = await self._owner_ids()
            if not any(str(f.get("owner_staff_id")) in owners for f in r.findings or []):
                raise not_found("Audit register")
        return r

    async def get(self, aid: uuid.UUID) -> AuditRegisterOut:
        self.require_reader()
        return self.out(await self.row(aid))

    def _findings(self, existing: list[dict[str, Any]], new: list[Any]) -> list[dict[str, Any]]:
        out = list(existing)
        nxt = max((int(f.get("no") or 0) for f in out), default=0)
        for f in new:
            nxt += 1
            out.append(
                {
                    "no": nxt,
                    "text": f.text,
                    "owner_staff_id": str(f.owner_staff_id) if f.owner_staff_id else None,
                    "due_on": f.due_on.isoformat() if f.due_on else None,
                    "status": "open",
                    "action_taken": None,
                }
            )
        return out

    async def _notify_owners(self, r: AuditRegister, findings: list[dict[str, Any]]) -> None:
        for f in findings:
            if f.get("owner_staff_id"):
                await self._notify(
                    "accreditation.audit_finding_assigned",
                    [await self.staff_user(uuid.UUID(f["owner_staff_id"]))],
                    {
                        "audit": r.audit_type,
                        "period": r.period_label,
                        "finding": f["text"][:200],
                        "due_on": f.get("due_on") or "",
                    },
                )

    async def create(self, body: AuditRegisterIn) -> AuditRegisterOut:
        self.require_iqac()
        r = AuditRegister(
            institution_id=self.inst,
            audit_type=body.audit_type.value,
            period_label=body.period_label,
            auditor=body.auditor,
            report_url=body.report_url,
            findings=self._findings([], body.findings),
            status="open",
        )
        self.db.add(r)
        await self.db.flush()
        await self._notify_owners(r, r.findings or [])
        await self._emit(
            "accreditation.audit_register_created",
            {"audit_register_id": str(r.id), "audit_type": r.audit_type},
            "audit_register",
            r.id,
        )
        return self.out(r)

    async def update(self, aid: uuid.UUID, body: AuditRegisterUpdate) -> AuditRegisterOut:
        self.require_iqac()
        r = await self.row(aid, lock=True)
        if body.auditor is not None:
            r.auditor = body.auditor
        if body.report_url is not None:
            r.report_url = body.report_url
        if body.add_findings:
            before = len(r.findings or [])
            r.findings = self._findings(list(r.findings or []), body.add_findings)
            await self._notify_owners(r, (r.findings or [])[before:])
            r.status = "in_progress" if r.status == "closed" else r.status
        if body.status is not None:
            if body.status.value == "closed" and any(f.get("status") != "closed" for f in r.findings or []):
                raise rule("Close every finding before closing the register", "OPEN_FINDINGS")
            r.status = body.status.value
        await self.db.flush()
        return self.out(r)

    async def update_finding(self, aid: uuid.UUID, no: int, body: FindingUpdate) -> AuditRegisterOut:
        self.require_writer()
        r = await self.row(aid, lock=True)
        findings = [dict(f) for f in r.findings or []]
        target = next((f for f in findings if int(f.get("no") or 0) == no), None)
        if target is None:
            raise not_found(f"Finding {no}")
        owners = await self._owner_ids()
        if not (self.iqac() or str(target.get("owner_staff_id")) in owners):
            raise forbidden("Only the finding owner or IQAC updates a finding")
        if (body.owner_staff_id is not None or body.due_on is not None) and not self.iqac():
            raise forbidden("Only IQAC reassigns or reschedules findings")
        if body.status is not None:
            target["status"] = body.status.value
        if body.action_taken is not None:
            target["action_taken"] = body.action_taken
        if body.owner_staff_id is not None:
            target["owner_staff_id"] = str(body.owner_staff_id)
        if body.due_on is not None:
            target["due_on"] = body.due_on.isoformat()
        r.findings = findings
        if all(f.get("status") == "closed" for f in findings):
            r.status = "closed"
        elif r.status == "open" and any(f.get("status") != "open" for f in findings):
            r.status = "in_progress"
        await self.db.flush()
        await self._emit(
            "accreditation.audit_finding_updated",
            {"audit_register_id": str(r.id), "no": no, "status": target["status"]},
            "audit_register",
            r.id,
        )
        return self.out(r)

    async def dashboard(self) -> AuditDashboardOut:
        items = await self.query()
        today = await self.today()
        by_type: dict[str, int] = {}
        opened = overdue = closed = 0
        for r in items:
            by_type[r.audit_type] = by_type.get(r.audit_type, 0) + 1
            for f in r.findings:
                if f.status == "closed":
                    closed += 1
                else:
                    opened += 1
                    overdue += 1 if f.due_on and f.due_on < today else 0
        return AuditDashboardOut(
            registers=len(items),
            by_type=by_type,
            findings_open=opened,
            findings_overdue=overdue,
            findings_closed=closed,
        )

    async def finding_reminders(self) -> int:
        today = await self.today()
        n = 0
        for r in (
            await self.db.execute(
                select(AuditRegister).where(AuditRegister.institution_id == self.inst, AuditRegister.status != "closed")
            )
        ).scalars():
            for f in r.findings or []:
                if (
                    f.get("status") != "closed"
                    and f.get("owner_staff_id")
                    and f.get("due_on")
                    and date.fromisoformat(f["due_on"]) <= today
                ):
                    await self._notify(
                        "accreditation.audit_finding_assigned",
                        [await self.staff_user(uuid.UUID(f["owner_staff_id"]))],
                        {
                            "audit": r.audit_type,
                            "period": r.period_label,
                            "finding": str(f.get("text"))[:200],
                            "due_on": f["due_on"],
                        },
                    )
                    n += 1
        return n
