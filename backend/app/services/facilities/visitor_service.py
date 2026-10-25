"""Visitor & gate passes — Prompts/25 §25.6 ``visitor_service`` ({facilities.visitor_gate}).

Passes are pre-registered by hosts (staff; students when ``facilities:book`` is granted) or issued at the gate by
``facilities:manage`` holders (security / receptionist). ``pass_code`` (``visitor`` sequence) doubles as the QR payload.
Gate scans (``in`` / ``out``) are recorded by gate staff only; ``inside`` lists who is on campus for evacuation; expired
passes are refused (409). Blacklisted phones (``facilities.visitor_blacklist``) are refused at issue. DPDP: the
``visitor.pii_purge`` job blanks the visitor's name / phone / id proof after ``visitor_pii_retention_days``.
Visibility: host / creator (self), all for gate staff (``facilities:manage``) and readers (``view_all``).
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from app.models.facilities import VisitorPass
from app.schemas.facilities import FacGateScan, FacVisitorPassCreate, FacVisitorPassOut
from app.services.facilities.common import FacilitiesBase, forbidden, not_found, now_utc, rule


class VisitorService(FacilitiesBase):
    audit_module = "facilities"

    def _gate(self) -> bool:
        return self.can("facilities", "manage")

    def _visible(self) -> Any:
        return self.unit_predicate(
            "facilities",
            self_cols=(VisitorPass.host_user_id, VisitorPass.created_by),
            college_col=VisitorPass.college_id,
        )

    async def outs(self, rows: Sequence[VisitorPass]) -> list[FacVisitorPassOut]:
        names = await self.user_names([r.host_user_id for r in rows])
        out = []
        for r in rows:
            o = FacVisitorPassOut.model_validate(r)
            o.host_name = names.get(r.host_user_id) if r.host_user_id else None
            o.qr = f"VP:{r.pass_code}" if r.pass_code else None
            out.append(o)
        return out

    async def row(self, pid: uuid.UUID) -> VisitorPass:
        r = (
            await self.db.execute(
                select(VisitorPass).where(
                    VisitorPass.id == pid, VisitorPass.institution_id == self.inst, self._visible()
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Visitor pass")
        return r

    async def list_passes(
        self, *, status: str | None = None, on: date | None = None, mine: bool = False
    ) -> list[FacVisitorPassOut]:
        stmt = select(VisitorPass).where(VisitorPass.institution_id == self.inst)
        stmt = (
            stmt.where(or_(VisitorPass.host_user_id == self.actor_id, VisitorPass.created_by == self.actor_id))
            if mine
            else stmt.where(self._visible())
        )
        if status:
            stmt = stmt.where(VisitorPass.status == status)
        if on:
            from app.core.tenancy import institution_tz

            tz = institution_tz(await self.institution())
            d0 = datetime.combine(on, datetime.min.time(), tzinfo=tz)
            stmt = stmt.where(VisitorPass.valid_from < d0 + timedelta(days=1), VisitorPass.valid_to >= d0)
        rows = (await self.db.execute(stmt.order_by(VisitorPass.valid_from.desc()).limit(500))).scalars().all()
        return await self.outs(rows)

    async def get(self, pid: uuid.UUID) -> FacVisitorPassOut:
        return (await self.outs([await self.row(pid)]))[0]

    async def issue(self, body: FacVisitorPassCreate) -> FacVisitorPassOut:
        self.require("facilities:manage", "facilities:book")
        self.require_writer()
        black = await self.setting("facilities", "visitor_blacklist")
        if isinstance(black, list) and body.visitor.phone in {str(x) for x in black}:
            raise rule("This visitor is not allowed on campus", "VISITOR_BLACKLISTED")
        host = body.host_user_id
        if not self._gate():
            if host and host != self.actor_id:
                raise forbidden("You pre-register visitors for yourself")
            host = self.actor_id
        hours = await self.int_setting("facilities", "visitor_pass_validity_hours", 8)
        vf = body.valid_from or now_utc()
        vt = body.valid_to or (vf + timedelta(hours=hours))
        if vt <= vf:
            raise rule("valid_to must be after valid_from", "BAD_WINDOW", status=422)
        r = VisitorPass(
            institution_id=self.inst,
            college_id=body.college_id,
            visitor=body.visitor.model_dump(),
            host_user_id=host,
            purpose=body.purpose,
            valid_from=vf,
            valid_to=vt,
            vehicle_no=body.vehicle_no,
            id_proof=body.id_proof,
            pass_code=(await self.sequence("visitor", "VP")).replace("/", "")[:20],
            status="issued",
            created_by=self.actor_id,
        )
        self.db.add(r)
        await self.db.flush()
        await self._audit("create", "visitor_pass", r.id, None, {"pass_code": r.pass_code})
        await self._emit("visitor.pass_issued", {"pass_id": str(r.id)}, "visitor_pass", r.id)
        return (await self.outs([r]))[0]

    async def scan(self, body: FacGateScan) -> FacVisitorPassOut:
        if not self._gate():
            raise forbidden("Only gate staff scan visitor passes")
        code = body.pass_code.removeprefix("VP:")
        r = (
            await self.db.execute(
                select(VisitorPass)
                .where(VisitorPass.institution_id == self.inst, VisitorPass.pass_code == code)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Visitor pass")
        now = now_utc()
        if body.direction == "in":
            if r.status not in ("issued", "exited"):
                raise rule(f"The pass is {r.status}", "PASS_NOT_VALID", current=r.status)
            if now > r.valid_to or r.status == "expired":
                r.status = "expired"
                await self.db.flush()
                raise rule("The pass has expired", "PASS_EXPIRED")
            if now < r.valid_from - timedelta(minutes=30):
                raise rule("The pass is not valid yet", "PASS_NOT_YET_VALID")
            r.status, r.gate_in_at = "inside", now
            if body.photo_url:
                r.visitor = {**(r.visitor or {}), "gate_photo_url": body.photo_url}
            await self._emit("visitor.arrived", {"pass_id": str(r.id)}, "visitor_pass", r.id)
            await self._notify(
                "visitor.arrived",
                [r.host_user_id],
                {"visitor": (r.visitor or {}).get("name", "Visitor"), "at": now.isoformat()},
            )
        else:
            if r.status != "inside":
                raise rule("The visitor is not inside", "NOT_INSIDE")
            r.status, r.gate_out_at = "exited", now
            await self._emit("visitor.exited", {"pass_id": str(r.id)}, "visitor_pass", r.id)
        await self.db.flush()
        await self._audit(f"gate_{body.direction}", "visitor_pass", r.id, None, {"pass_code": r.pass_code})
        return (await self.outs([r]))[0]

    async def inside(self) -> list[FacVisitorPassOut]:
        if not (self._gate() or self.can("facilities", "view_all")):
            raise forbidden("Gate staff only")
        rows = (
            (
                await self.db.execute(
                    select(VisitorPass)
                    .where(VisitorPass.institution_id == self.inst, VisitorPass.status == "inside")
                    .order_by(VisitorPass.gate_in_at)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def register(self, on: date) -> list[dict[str, Any]]:
        if not (self._gate() or self.can("facilities", "view_all")):
            raise forbidden("Gate staff only")
        return [
            {
                "pass_code": o.pass_code,
                "visitor": (o.visitor or {}).get("name"),
                "phone": (o.visitor or {}).get("phone"),
                "organisation": (o.visitor or {}).get("organisation"),
                "host": o.host_name,
                "purpose": o.purpose,
                "in": o.gate_in_at.isoformat() if o.gate_in_at else None,
                "out": o.gate_out_at.isoformat() if o.gate_out_at else None,
                "status": o.status,
            }
            for o in await self.list_passes(on=on)
        ]

    async def expire_passes(self) -> int:
        rows = (
            (
                await self.db.execute(
                    select(VisitorPass).where(
                        VisitorPass.institution_id == self.inst,
                        VisitorPass.status == "issued",
                        VisitorPass.valid_to < now_utc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            r.status = "expired"
            await self._emit("visitor.expired", {"pass_id": str(r.id)}, "visitor_pass", r.id)
        await self.db.flush()
        return len(rows)

    async def purge_pii(self) -> int:
        days = await self.int_setting("facilities", "visitor_pii_retention_days", 90)
        rows = (
            (
                await self.db.execute(
                    select(VisitorPass).where(
                        VisitorPass.institution_id == self.inst,
                        VisitorPass.created_at < now_utc() - timedelta(days=days),
                        VisitorPass.visitor["purged"].astext.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            r.visitor = {"name": "[purged]", "phone": None, "purged": True}
            r.id_proof = None
            r.vehicle_no = None
        await self.db.flush()
        if rows:
            await self._audit("pii_purge", "visitor_pass", None, None, {"count": len(rows), "retention_days": days})
        return len(rows)
