"""RTI requests — Prompts/33 §33.6 ``rti_service`` ({governance.rti}).

Receipt (``request_no`` from the ``rti`` sequence; applicant details; BPL → fee waived), ``due_on = received_on +
rti.response_days`` (a §6(3) transfer counts from ``transferred_on``), fee through a Phase 12 invoice
(``source_type='rti_fee'``, payer ``external``) or recorded cash / IPO / DD, PIO assignment with departments consulted,
consultations through e-File (``governance.efile`` on: a file is opened, linked to the request and forwarded),
the reply rendered with the Phase 26 ``rti_response`` template (additional fee for copies), first appeal within
``rti.appeal_days`` to the appellate authority and its decision (second appeal is an external note), close; daily
due-date reminders; quarterly / annual return for Phase 36. Applicant PII is masked for everyone but the PIOs
(``rti:manage`` / the assigned PIO) and the appellate authority.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.models.governance import RtiRequest
from app.schemas.governance import (
    RtiAppeal,
    RtiAppealDecision,
    RtiAssign,
    RtiClose,
    RtiConsult,
    RtiIn,
    RtiOut,
    RtiRespond,
    RtiReturnOut,
    RtiUpdate,
)
from app.services.documents.render_service import register_resolver
from app.services.governance.common import GovernanceBase, forbidden, is_auditor, not_found, now_utc, rule

ENTITY = "rti_request"
R = "rti"


def _mask(a: dict[str, Any]) -> dict[str, Any]:
    name = str(a.get("name") or "")
    return {"name": (name[:1] + "***") if name else "***", "is_bpl": bool(a.get("is_bpl"))}


class RtiService(GovernanceBase):
    audit_module = R

    def pio(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and p.has(R, "manage"))

    def appellate(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and p.has(R, "approve"))

    def can_read(self) -> bool:
        return self.pio() or self.appellate() or self.has_any(R, "view_all")

    async def _row(self, rid: uuid.UUID, *, lock: bool = False) -> RtiRequest:
        stmt = select(RtiRequest).where(RtiRequest.id == rid, RtiRequest.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("RTI request")
        if not self.can_read():
            sid = await self.my_staff_id()
            if sid is None or r.pio_staff_id != sid:
                raise not_found("RTI request")
        return r

    async def _is_assigned(self, r: RtiRequest) -> bool:
        sid = await self.my_staff_id()
        return sid is not None and r.pio_staff_id == sid

    async def require_pio(self, r: RtiRequest | None = None) -> None:
        self.require_writer()
        if self.pio() or (r is not None and await self._is_assigned(r)):
            return
        raise forbidden("rti:manage required (PIO)")

    async def outs(self, rows: list[RtiRequest]) -> list[RtiOut]:
        metas = await self.metas("rti", [str(r.id) for r in rows])
        names = await self.staff_names([r.pio_staff_id for r in rows])
        today = await self.today()
        sid = await self.my_staff_id()
        full = self.pio() or self.appellate()
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            show = full or (sid is not None and r.pio_staff_id == sid)
            out.append(
                RtiOut(
                    id=r.id,
                    request_no=r.request_no,
                    applicant=dict(r.applicant) if show else _mask(r.applicant or {}),
                    masked=not show,
                    received_on=r.received_on,
                    due_on=r.due_on,
                    days_left=(r.due_on - today).days if r.status in ("received", "assigned") else None,
                    late=bool(
                        (r.responded_on and r.responded_on > r.due_on)
                        or (r.status in ("received", "assigned") and today > r.due_on)
                    ),
                    subject=r.subject,
                    mode=m.get("mode"),
                    pio_staff_id=r.pio_staff_id,
                    pio_name=names.get(r.pio_staff_id) if r.pio_staff_id else None,
                    fee_paise=r.fee_paise,
                    fee_status=m.get("fee_status"),
                    fee_invoice_id=uuid.UUID(m["fee_invoice_id"]) if m.get("fee_invoice_id") else None,
                    response_url=r.response_url,
                    response_text=m.get("response_text") if show or r.status != "received" else None,
                    responded_on=r.responded_on,
                    status=r.status,
                    first_appeal=r.first_appeal,
                    consultations=list(m.get("consultations") or []),
                    created_at=r.created_at,
                )
            )
        return out

    async def list_requests(self, status: str | None = None, overdue: bool | None = None) -> list[RtiOut]:
        stmt = select(RtiRequest).where(RtiRequest.institution_id == self.inst)
        if not self.can_read():
            stmt = stmt.where(RtiRequest.pio_staff_id == (await self.my_staff_id() or uuid.uuid4()))
        if status:
            stmt = stmt.where(RtiRequest.status == status)
        if overdue:
            stmt = stmt.where(RtiRequest.status.in_(("received", "assigned")), RtiRequest.due_on < await self.today())
        rows = (await self.db.execute(stmt.order_by(RtiRequest.due_on))).scalars()
        return await self.outs(list(rows))

    async def get(self, rid: uuid.UUID) -> RtiOut:
        return (await self.outs([await self._row(rid)]))[0]

    async def create(self, body: RtiIn) -> RtiOut:
        await self.require_pio()
        received = body.received_on or await self.today()
        days = await self.gov_int("rti.response_days")
        start = body.transferred_on if body.mode == "transfer_6_3" and body.transferred_on else received
        fee = (
            0
            if body.applicant.is_bpl
            else (body.fee_paise if body.fee_paise is not None else await self.gov_int("rti.fee_paise"))
        )
        r = RtiRequest(
            institution_id=self.inst,
            request_no=await self.sequence("rti", "RTI"),
            applicant=body.applicant.model_dump(),
            received_on=received,
            due_on=start + timedelta(days=days),
            subject=body.subject,
            fee_paise=fee,
            status="received",
        )
        self.db.add(r)
        await self.db.flush()
        meta: dict[str, Any] = {"mode": body.mode, "fee_mode": "waived" if body.applicant.is_bpl else body.fee_mode}
        meta["fee_status"] = (
            "waived" if body.applicant.is_bpl or not fee else ("paid" if body.fee_mode != "invoice" else "invoiced")
        )
        if fee and body.fee_mode == "invoice" and not body.applicant.is_bpl:
            inv = await self._invoice(r, fee, "RTI application fee")
            meta["fee_invoice_id"] = str(inv) if inv else None
            if inv is None:
                meta["fee_status"] = "pending"
        await self.put_meta("rti", r.id, meta)
        await self._audit("create", ENTITY, r.id, None, {"request_no": r.request_no})
        await self._emit("rti.received", {"rti_id": str(r.id), "request_no": r.request_no}, ENTITY, r.id)
        await self._notify(
            "rti.received",
            await self.role_users("pio"),
            {"request_no": r.request_no, "received_on": str(r.received_on), "due_on": str(r.due_on)},
        )
        return (await self.outs([r]))[0]

    async def _invoice(self, r: RtiRequest, amount: int, label: str) -> uuid.UUID | None:
        try:
            from app.schemas.fees import InvoiceCreate, InvoiceItemIn
            from app.services.fees.invoice_service import InvoiceService

            async with self.db.begin_nested():
                inv = await InvoiceService(self.db, None, None, self.inst).create_invoice(
                    InvoiceCreate(
                        payer_type="external",
                        payer_id=r.id,
                        source_type="rti_fee",
                        source_id=r.id,
                        description=f"{label} · {r.request_no}"[:200],
                        items=[
                            InvoiceItemIn(
                                description=f"{label} · {r.request_no}"[:200], amount_paise=amount, head_code="OTHER"
                            )
                        ],
                        due_date=await self.today(),
                        allow_multiple=True,
                    ),
                    notify=False,
                )
            return inv.id
        except Exception:  # noqa: BLE001 - fees module off / no head: the fee is recorded as pending
            return None

    async def update(self, rid: uuid.UUID, body: RtiUpdate) -> RtiOut:
        r = await self._row(rid, lock=True)
        await self.require_pio(r)
        if body.subject is not None:
            r.subject = body.subject
        if body.applicant is not None:
            r.applicant = body.applicant.model_dump()
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def assign(self, rid: uuid.UUID, body: RtiAssign) -> RtiOut:
        r = await self._row(rid, lock=True)
        await self.require_pio()
        if r.status not in ("received", "assigned"):
            raise rule(f"The request is {r.status}", "INVALID_TRANSITION")
        r.pio_staff_id, r.status = body.pio_staff_id, "assigned"
        m = await self.meta("rti", r.id)
        m["departments_consulted"] = [str(d) for d in body.departments_consulted]
        await self.put_meta("rti", r.id, m)
        await self.db.flush()
        await self._emit("rti.assigned", {"rti_id": str(r.id), "pio_staff_id": str(body.pio_staff_id)}, ENTITY, r.id)
        await self._notify(
            "rti.assigned",
            [await self.staff_user(body.pio_staff_id)],
            {"request_no": r.request_no, "due_on": str(r.due_on)},
        )
        return (await self.outs([r]))[0]

    async def consult(self, rid: uuid.UUID, body: RtiConsult) -> RtiOut:
        """Information gathering through e-File: a file linked to the request is opened and forwarded."""
        r = await self._row(rid, lock=True)
        await self.require_pio(r)
        await self.require_feature("governance.efile")
        from app.schemas.governance import EfileCreate, EfileMove, LinkedEntity
        from app.services.governance.efile_service import EfileService

        es = EfileService(self.db, self.principal, self.request, self.inst)
        f = await es.create(
            EfileCreate(
                subject=f"RTI {r.request_no} — information sought"[:300],
                category="rti",
                priority="high",
                initial_noting=body.noting,
                linked_entity=LinkedEntity(entity_type="rti_request", entity_id=r.id, label=r.request_no),
            )
        )
        moved = await es.move(
            f.id,
            EfileMove(to_user_id=body.to_user_id, to_role=body.to_role, action="forward", noting=body.noting),  # type: ignore[arg-type]
        )
        m = await self.meta("rti", r.id)
        m.setdefault("consultations", []).append(
            {
                "efile_id": str(f.id),
                "file_no": f.file_no,
                "to_user_id": str(moved.current_holder_user_id) if moved.current_holder_user_id else None,
                "at": now_utc().isoformat(),
            }
        )
        await self.put_meta("rti", r.id, m)
        return (await self.outs([r]))[0]

    async def respond(self, rid: uuid.UUID, body: RtiRespond) -> RtiOut:
        r = await self._row(rid, lock=True)
        await self.require_pio(r)
        if r.status not in ("received", "assigned"):
            raise rule(f"The request is {r.status}", "INVALID_TRANSITION")
        today = await self.today()
        r.status, r.responded_on, r.response_url = "responded", today, body.response_url
        m = await self.meta("rti", r.id)
        m["response_text"] = body.response_text
        m["late"] = today > r.due_on
        if body.fee_additional_paise:
            m["fee_additional_paise"] = body.fee_additional_paise
            inv = await self._invoice(r, body.fee_additional_paise, "RTI additional fee (copies)")
            m["additional_invoice_id"] = str(inv) if inv else None
        await self.put_meta("rti", r.id, m)
        await self.db.flush()
        doc = await self.render_doc("rti_response", ENTITY, r.id)
        if doc is not None and not r.response_url:
            r.response_url = getattr(doc, "pdf_url", None)
            m = await self.meta("rti", r.id)
            m["response_document_id"] = str(doc.issued_document_id)
            await self.put_meta("rti", r.id, m)
        await self.db.flush()
        await self._emit(
            "rti.responded", {"rti_id": str(r.id), "late": today > r.due_on, "responded_on": str(today)}, ENTITY, r.id
        )
        return (await self.outs([r]))[0]

    async def appeal(self, rid: uuid.UUID, body: RtiAppeal) -> RtiOut:
        r = await self._row(rid, lock=True)
        await self.require_pio(r)
        if r.status not in ("responded", "assigned", "received"):
            raise rule(f"The request is {r.status}", "INVALID_TRANSITION")
        filed = body.filed_on or await self.today()
        window = await self.gov_int("rti.appeal_days")
        base = r.responded_on or r.due_on
        if filed > base + timedelta(days=window):
            raise rule("The first appeal is beyond the appeal window", "APPEAL_TIME_BARRED", 422)
        r.first_appeal = {
            "grounds": body.grounds,
            "filed_on": str(filed),
            "appellate_authority_staff_id": str(body.appellate_authority_staff_id)
            if body.appellate_authority_staff_id
            else None,
            "due_on": str(filed + timedelta(days=window)),
            "status": "pending",
        }
        r.status = "appealed"
        await self.db.flush()
        await self._emit("rti.appealed", {"rti_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def decide_appeal(self, rid: uuid.UUID, body: RtiAppealDecision) -> RtiOut:
        self.require_writer()
        r = await self._row(rid, lock=True)
        fa = dict(r.first_appeal or {})
        sid = await self.my_staff_id()
        named = fa.get("appellate_authority_staff_id")
        if not (self.appellate() or (named and sid and str(sid) == named)):
            raise forbidden("Only the appellate authority decides first appeals")
        if r.status != "appealed":
            raise rule("No pending appeal", "INVALID_TRANSITION")
        fa.update(
            {
                "status": "decided",
                "decision": body.decision,
                "remarks": body.remarks,
                "second_appeal_note": body.second_appeal_note,
                "decided_on": str(await self.today()),
                "decided_by": str(self.actor_id) if self.actor_id else None,
            }
        )
        r.first_appeal, r.status = fa, "closed"
        await self.db.flush()
        await self._emit("rti.decided", {"rti_id": str(r.id), "decision": body.decision}, ENTITY, r.id)
        await self._emit("rti.closed", {"rti_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def close(self, rid: uuid.UUID, body: RtiClose) -> RtiOut:
        r = await self._row(rid, lock=True)
        await self.require_pio(r)
        if r.status not in ("responded",):
            raise rule("Only replied requests can be closed", "INVALID_TRANSITION")
        r.status = "closed"
        await self.timeline("rti", r.id, "closed", remarks=body.remarks)
        await self.db.flush()
        await self._emit("rti.closed", {"rti_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def annual_return(self, period: str) -> RtiReturnOut:
        """``period`` = ``YYYY`` or ``YYYY-Qn`` (calendar quarters)."""
        year_s, _, q = period.partition("-")
        year = int(year_s)
        if q:
            qn = int(q.strip("Qq"))
            start, end = date(year, 3 * qn - 2, 1), (date(year, 3 * qn, 1) + timedelta(days=31)).replace(day=1)
        else:
            start, end = date(year, 1, 1), date(year + 1, 1, 1)
        rows = list(
            (
                await self.db.execute(
                    select(RtiRequest).where(
                        RtiRequest.institution_id == self.inst,
                        RtiRequest.received_on >= start,
                        RtiRequest.received_on < end,
                    )
                )
            ).scalars()
        )
        metas = await self.metas("rti", [str(r.id) for r in rows])
        disposed = [r for r in rows if r.status in ("responded", "closed", "appealed")]
        within = [r for r in disposed if r.responded_on and r.responded_on <= r.due_on]
        fees = sum(int(r.fee_paise or 0) for r in rows) + sum(
            int(metas.get(str(r.id), {}).get("fee_additional_paise") or 0) for r in rows
        )
        return RtiReturnOut(
            period=period,
            received=len(rows),
            disposed=len(disposed),
            within_time=len(within),
            within_time_pct=round(100 * len(within) / len(disposed), 1) if disposed else 0.0,
            appeals=sum(1 for r in rows if r.first_appeal),
            pending=sum(1 for r in rows if r.status in ("received", "assigned")),
            fees_collected_paise=fees,
            bpl_waivers=sum(1 for r in rows if (r.applicant or {}).get("is_bpl")),
        )

    async def due_reminders(self) -> int:
        today = await self.today()
        rows = (
            await self.db.execute(
                select(RtiRequest).where(
                    RtiRequest.institution_id == self.inst,
                    RtiRequest.status.in_(("received", "assigned")),
                    RtiRequest.due_on <= today + timedelta(days=5),
                )
            )
        ).scalars()
        n = 0
        for r in rows:
            users = [await self.staff_user(r.pio_staff_id)] if r.pio_staff_id else await self.role_users("pio")
            await self._notify(
                "rti.due", users, {"request_no": r.request_no, "due_on": str(r.due_on), "days": (r.due_on - today).days}
            )
            n += 1
        return n


@register_resolver(ENTITY)
async def _rti_ctx(svc: Any, rid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.models.platform import InstitutionSetting

    r = (await svc.db.execute(select(RtiRequest).where(RtiRequest.id == rid))).scalar_one()
    row = (
        await svc.db.execute(
            select(InstitutionSetting.value).where(
                InstitutionSetting.institution_id == r.institution_id,
                InstitutionSetting.category == "governance_meta",
                InstitutionSetting.key == f"rti:{r.id}",
            )
        )
    ).scalar_one_or_none()
    m = row if isinstance(row, dict) else {}
    a = r.applicant or {}
    return (
        {
            "rti": {
                "request_no": r.request_no,
                "received_on": r.received_on.strftime("%d-%m-%Y"),
                "applicant": ", ".join(x for x in (a.get("name"), a.get("address")) if x),
                "subject": r.subject,
                "response": str(m.get("response_text") or "").replace("\n", "<br>"),
                "fee_additional": f"{int(m.get('fee_additional_paise') or 0) / 100:.2f}"
                if m.get("fee_additional_paise")
                else "",
                "appellate": "the First Appellate Authority",
                "appeal_days": 30,
            },
            "title": f"RTI reply {r.request_no}",
            "body": "",
        },
        None,
        None,
    )
