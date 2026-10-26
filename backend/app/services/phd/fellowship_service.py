"""Fellowships — Prompts/31 §31.6 ``fellowship_service`` ({phd.fellowships}).

A fellowship (``scholar_fellowships``: JRF / SRF / institution / project) takes its monthly amount from
``phd.rules.fellowship_defaults`` unless given, HRA (``hra_pct`` of the stipend when ``hra_applicable``) and a yearly
contingency grant; funding source UGC / CSIR / institution / project (→ the Phase 23 grant head). Status
``active | held | closed``.

The monthly run (job ``phd.fellowship_run``) locks each active fellowship ``FOR UPDATE`` and creates one
``fellowship_disbursements(month)`` row: eligible = active, scholar not discontinued / awarded, full-time, no overdue
progress report beyond the grace, not inside a leave with a hold rule, max duration not exceeded — otherwise the row
is ``held`` with the reason. Releasing a hold adds the held amount as arrears to the next run. ``pending → approved``
(research cell) → payment: ``/disbursements/pay`` stamps ``payroll_ref`` and emits ``phd.fellowship_payment_requested``
(route ``phd.fellowship_payment_route``: Phase 23 payout batch with ``expense_records(source_type='fellowship')`` or a
Phase 06 payroll earning); ``accounting.expense_paid`` / ``payroll.paid`` (or the desk) mark ``paid``. Contingency
claims (bills) are separate disbursements of kind ``contingency`` within the yearly grant. JRF → SRF after
``jrf_to_srf_months`` with a DC recommendation creates a new SRF row (the JRF row closes).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.phd import DcMeeting, FellowshipDisbursement, ResearchScholar, ScholarFellowship
from app.schemas.phd import (
    ContingencyClaim,
    DisbursementHold,
    DisbursementPay,
    DisbursementRunResult,
    FellowshipCreate,
    FellowshipOut,
    FellowshipUpdate,
    PhdDisbursementOut,
)
from app.services.phd.common import PhdBase, add_months, forbidden, months_between, not_found, now_utc, rule, rupees

ENTITY = "scholar_fellowship"


def month_start(d: date) -> date:
    return d.replace(day=1)


class FellowshipService(PhdBase):
    def payer(self) -> bool:
        """Research cell (``phd:fellowship``) or accounts (``accounting:manage|post``)."""
        p = self.principal
        return self.cell("fellowship") or (p is not None and any(p.has("accounting", a) for a in ("manage", "post")))

    def money_reader(self) -> bool:
        p = self.principal
        return self.cell("fellowship") or (
            p is not None
            and (p.has("phd", "fellowship") or any(p.has("accounting", a) for a in ("view_all", "manage", "post")))
        )

    async def outs(self, rows: list[ScholarFellowship]) -> list[FellowshipOut]:
        metas = await self.metas("fellowship", [r.id for r in rows])
        rules = await self.rules()
        used: dict[Any, int] = (
            dict(
                (
                    await self.db.execute(
                        select(
                            FellowshipDisbursement.fellowship_id,
                            func.coalesce(func.sum(FellowshipDisbursement.amount_paise), 0),
                        )
                        .where(
                            FellowshipDisbursement.fellowship_id.in_([r.id for r in rows]),
                            FellowshipDisbursement.month >= date((await self.today()).year, 1, 1),
                            FellowshipDisbursement.status != "held",
                            FellowshipDisbursement.payroll_ref.like("CNT%"),
                        )
                        .group_by(FellowshipDisbursement.fellowship_id)
                    )
                )
                .tuples()
                .all()
            )
            if rows
            else {}
        )
        out = []
        for r in rows:
            m = metas.get(str(r.id)) or {}
            out.append(
                FellowshipOut(
                    id=r.id,
                    scholar_id=r.scholar_id,
                    fellowship_type=r.fellowship_type,
                    monthly_paise=r.monthly_paise,
                    hra_paise=await self._hra(r, rules, m),
                    from_on=r.from_on,
                    to_on=r.to_on,
                    contingency_paise=r.contingency_paise,
                    contingency_used_paise=int(used.get(r.id, 0) or 0),
                    hra_applicable=r.hra_applicable,
                    funding_source=r.funding_source,
                    status=r.status,
                )
            )
        return out

    async def _hra(self, f: ScholarFellowship, rules: dict[str, Any], m: dict[str, Any] | None = None) -> int:
        if not f.hra_applicable:
            return 0
        pct = (m or {}).get("hra_pct")
        if pct is None:
            pct = ((rules.get("fellowship_defaults") or {}).get(f.fellowship_type) or {}).get("hra_pct", 0)
        return int(f.monthly_paise * float(pct or 0) / 100)

    async def current_out(self, s: ResearchScholar) -> FellowshipOut | None:
        f = (
            await self.db.execute(
                select(ScholarFellowship)
                .where(ScholarFellowship.scholar_id == s.id)
                .order_by(ScholarFellowship.from_on.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return (await self.outs([f]))[0] if f is not None else None

    async def for_scholar(self, sid: uuid.UUID) -> list[FellowshipOut]:
        s = await self.scholar(sid)
        rows = list(
            (
                await self.db.execute(
                    select(ScholarFellowship)
                    .where(ScholarFellowship.scholar_id == s.id)
                    .order_by(ScholarFellowship.from_on)
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def create(
        self, sid: uuid.UUID, body: FellowshipCreate, *, upgrade_from: uuid.UUID | None = None
    ) -> FellowshipOut:
        if upgrade_from is None:
            self.require_cell("fellowship")
        s = await self.scholar_raw(sid, lock=True)
        if s.status in ("awarded", "discontinued"):
            raise rule(f"The scholar is {s.status}", "SCHOLAR_CLOSED")
        if s.mode == "part_time":
            raise rule("Part-time scholars hold no fellowship", "PART_TIME", 409)
        if body.fellowship_type.value == "none":
            raise rule("Choose a fellowship type", "TYPE_REQUIRED", 422)
        active = (
            (
                await self.db.execute(
                    select(ScholarFellowship).where(
                        ScholarFellowship.scholar_id == s.id, ScholarFellowship.status != "closed"
                    )
                )
            )
            .scalars()
            .all()
        )
        if active and upgrade_from is None:
            raise rule("The scholar already holds an active fellowship", "FELLOWSHIP_EXISTS")
        rules = await self.rules()
        d = (rules.get("fellowship_defaults") or {}).get(body.fellowship_type.value) or {}
        cont = body.contingency_paise
        if cont is None:
            cont = int((rules.get("contingency_yearly_paise") or {}).get(body.fellowship_type.value) or 0)
        f = ScholarFellowship(
            institution_id=self.inst,
            scholar_id=s.id,
            fellowship_type=body.fellowship_type.value,
            monthly_paise=int(body.monthly_paise if body.monthly_paise is not None else d.get("monthly_paise") or 0),
            from_on=body.from_on,
            to_on=body.to_on,
            contingency_paise=cont,
            hra_applicable=body.hra_applicable,
            funding_source=body.funding_source,
        )
        self.db.add(f)
        s.fellowship_type = f.fellowship_type
        await self.db.flush()
        if upgrade_from:
            await self.put_meta("fellowship", f.id, {"upgraded_from": str(upgrade_from)})
        await self._emit(
            "phd.fellowship_created",
            {
                "fellowship_id": str(f.id),
                "scholar_id": str(s.id),
                "type": f.fellowship_type,
                "monthly_paise": f.monthly_paise,
            },
            ENTITY,
            f.id,
        )
        return (await self.outs([f]))[0]

    async def _row(self, fid: uuid.UUID, *, lock: bool = False) -> ScholarFellowship:
        stmt = select(ScholarFellowship).where(
            ScholarFellowship.id == fid, ScholarFellowship.institution_id == self.inst
        )
        if lock:
            stmt = stmt.with_for_update()
        f = (await self.db.execute(stmt)).scalar_one_or_none()
        if f is None:
            raise not_found("Fellowship")
        return f

    async def update(self, fid: uuid.UUID, body: FellowshipUpdate) -> FellowshipOut:
        self.require_cell("fellowship")
        f = await self._row(fid, lock=True)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(f, k, v)
        await self.db.flush()
        return (await self.outs([f]))[0]

    # ---- disbursements ------------------------------------------------------------------------------------------------
    async def disb_outs(self, rows: list[FellowshipDisbursement]) -> list[PhdDisbursementOut]:
        if not rows:
            return []
        fs = {
            f.id: f
            for f in (
                await self.db.execute(
                    select(ScholarFellowship).where(ScholarFellowship.id.in_({r.fellowship_id for r in rows}))
                )
            ).scalars()
        }
        scholars = {
            s.id: s
            for s in (
                await self.db.execute(
                    select(ResearchScholar).where(ResearchScholar.id.in_({f.scholar_id for f in fs.values()}))
                )
            ).scalars()
        }
        cards = await self.enrollment_cards([s.student_program_enrollment_id for s in scholars.values()])
        metas = await self.metas("disb", [r.id for r in rows])
        out = []
        for r in rows:
            f = fs.get(r.fellowship_id)
            s = scholars.get(f.scholar_id) if f else None
            m = metas.get(str(r.id)) or {}
            out.append(
                PhdDisbursementOut(
                    id=r.id,
                    fellowship_id=r.fellowship_id,
                    scholar_id=s.id if s else None,
                    scholar_name=(cards.get(s.student_program_enrollment_id) or {}).get("name") if s else None,
                    fellowship_type=f.fellowship_type if f else None,
                    month=r.month,
                    amount_paise=r.amount_paise,
                    kind=m.get("kind") or "stipend",
                    status=r.status,
                    hold_reason=m.get("hold_reason"),
                    payroll_ref=None if (r.payroll_ref or "").startswith("CNT") else r.payroll_ref,
                    paid_at=r.paid_at,
                )
            )
        return out

    async def _eligibility(self, s: ResearchScholar, f: ScholarFellowship, month: date) -> str | None:
        from app.services.phd.progress_service import ProgressService

        if s.status in ("discontinued", "awarded"):
            return f"scholar {s.status}"
        if s.mode == "part_time":
            return "part-time scholar"
        if f.to_on and f.to_on < month:
            return "fellowship tenure ended"
        if s.max_duration_end and s.max_duration_end < month:
            return "maximum duration exceeded"
        if await ProgressService(self.db, None, institution_id=self.inst).overdue(s):
            return "progress report overdue"
        sm = await self.meta("scholar", s.id)
        for lv in sm.get("leaves") or []:
            if not (lv.get("hold") and lv.get("from_on") and lv.get("to_on")):
                continue
            if date.fromisoformat(lv["from_on"]) <= month <= date.fromisoformat(lv["to_on"]):
                return f"on {lv.get('type') or 'other'} leave"
        if (sm.get("cancellation_review") or {}).get("reason") == "unsatisfactory_progress":
            return "unsatisfactory progress (cancellation review)"
        return None

    async def run(self, month: date) -> DisbursementRunResult:
        """Monthly run — one disbursement per active fellowship (idempotent per ``(fellowship_id, month)``)."""
        self.require_cell("fellowship")
        mo = month_start(month)
        created = held = skipped = arrears_total = 0
        rules = await self.rules()
        rows = (
            (
                await self.db.execute(
                    select(ScholarFellowship)
                    .where(
                        ScholarFellowship.institution_id == self.inst,
                        ScholarFellowship.status == "active",
                        ScholarFellowship.from_on < add_months(mo, 1),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for f in rows:
            exists = (
                await self.db.execute(
                    select(FellowshipDisbursement.id).where(
                        FellowshipDisbursement.fellowship_id == f.id, FellowshipDisbursement.month == mo
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                skipped += 1
                continue
            s = await self.scholar_raw(f.scholar_id)
            reason = await self._eligibility(s, f, mo)
            m = await self.meta("fellowship", f.id)
            amount = f.monthly_paise + await self._hra(f, rules, m)
            arrears = int(m.pop("arrears_paise", 0) or 0) if reason is None else 0
            d = FellowshipDisbursement(
                institution_id=self.inst,
                fellowship_id=f.id,
                month=mo,
                amount_paise=amount + arrears,
                status="held" if reason else "pending",
            )
            self.db.add(d)
            await self.db.flush()
            await self.put_meta(
                "disb", d.id, {"kind": "stipend", "hold_reason": reason, "arrears_paise": arrears, "base_paise": amount}
            )
            if arrears:
                await self.put_meta("fellowship", f.id, m)
                arrears_total += arrears
            if reason:
                held += 1
                await self._emit("phd.fellowship_held", {"disbursement_id": str(d.id), "reason": reason}, ENTITY, f.id)
            else:
                created += 1
                await self._emit(
                    "phd.fellowship_disbursement_pending",
                    {"disbursement_id": str(d.id), "fellowship_id": str(f.id), "amount_paise": d.amount_paise},
                    ENTITY,
                    f.id,
                )
        await self.db.flush()
        return DisbursementRunResult(month=mo, created=created, held=held, skipped=skipped, arrears_paise=arrears_total)

    async def disbursements(
        self, *, month: date | None = None, status: str | None = None, limit: int = 200, offset: int = 0
    ) -> tuple[list[PhdDisbursementOut], int]:
        if not self.money_reader():
            raise forbidden("phd:fellowship or accounting:view_all required")
        stmt = select(FellowshipDisbursement).where(FellowshipDisbursement.institution_id == self.inst)
        if month:
            stmt = stmt.where(FellowshipDisbursement.month == month_start(month))
        if status:
            stmt = stmt.where(FellowshipDisbursement.status == status)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(FellowshipDisbursement.month.desc(), FellowshipDisbursement.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
        )
        return await self.disb_outs(rows), total

    async def _disb(self, did: uuid.UUID) -> FellowshipDisbursement:
        d = (
            await self.db.execute(
                select(FellowshipDisbursement)
                .where(FellowshipDisbursement.id == did, FellowshipDisbursement.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if d is None:
            raise not_found("Disbursement")
        return d

    async def approve(self, did: uuid.UUID) -> PhdDisbursementOut:
        self.require_cell("fellowship")
        d = await self._disb(did)
        if d.status != "pending":
            raise rule(f"A {d.status} disbursement cannot be approved", "NOT_PENDING")
        d.status = "approved"
        await self.db.flush()
        await self._emit("phd.fellowship_approved", {"disbursement_id": str(d.id)}, ENTITY, d.fellowship_id)
        return (await self.disb_outs([d]))[0]

    async def hold(self, did: uuid.UUID, body: DisbursementHold) -> PhdDisbursementOut:
        self.require_cell("fellowship")
        d = await self._disb(did)
        if d.status == "paid":
            raise rule("A paid disbursement cannot be held", "ALREADY_PAID")
        d.status = "held"
        m = await self.meta("disb", d.id)
        m["hold_reason"] = body.reason
        await self.put_meta("disb", d.id, m)
        await self.db.flush()
        await self._emit(
            "phd.fellowship_held", {"disbursement_id": str(d.id), "reason": body.reason}, ENTITY, d.fellowship_id
        )
        return (await self.disb_outs([d]))[0]

    async def release(self, did: uuid.UUID) -> PhdDisbursementOut:
        """A held stipend is released as arrears on the next run (the held row stays as the record)."""
        self.require_cell("fellowship")
        d = await self._disb(did)
        if d.status != "held":
            raise rule("Only a held disbursement is released", "NOT_HELD")
        m = await self.meta("disb", d.id)
        if m.get("released"):
            raise rule("Already released", "ALREADY_RELEASED")
        m["released"] = now_utc().isoformat()
        await self.put_meta("disb", d.id, m)
        fm = await self.meta("fellowship", d.fellowship_id)
        fm["arrears_paise"] = int(fm.get("arrears_paise") or 0) + int(m.get("base_paise") or d.amount_paise)
        await self.put_meta("fellowship", d.fellowship_id, fm)
        await self.db.flush()
        return (await self.disb_outs([d]))[0]

    async def contingency(self, did: uuid.UUID, body: ContingencyClaim) -> PhdDisbursementOut:
        """A contingency claim against the fellowship of disbursement ``did`` (``/disbursements/{id}/contingency``)."""
        self.require_writer()
        base = await self._disb(did)
        f = await self._row(base.fellowship_id, lock=True)
        s = await self.scholar(f.scholar_id)
        if not (await self.is_self(s) or self.cell("fellowship")):
            raise forbidden("The scholar or the research cell claims contingency")
        out = (await self.outs([f]))[0]
        if out.contingency_used_paise + body.amount_paise > int(f.contingency_paise or 0):
            raise rule("The claim exceeds the yearly contingency grant", "CONTINGENCY_EXCEEDED", 422)
        today = await self.today()
        # one row per month per fellowship is the table's key — a claim books on the next free day-of-month slot
        slot = month_start(today) + timedelta(days=1)
        while (
            await self.db.execute(
                select(FellowshipDisbursement.id).where(
                    FellowshipDisbursement.fellowship_id == f.id, FellowshipDisbursement.month == slot
                )
            )
        ).scalar_one_or_none():
            slot += timedelta(days=1)
            if slot.month != today.month:
                raise rule("Too many claims this month", "CLAIM_LIMIT", 429)
        d = FellowshipDisbursement(
            institution_id=self.inst,
            fellowship_id=f.id,
            month=slot,
            amount_paise=body.amount_paise,
            status="pending",
            payroll_ref=f"CNT{uuid.uuid4().hex[:8].upper()}",
        )
        self.db.add(d)
        await self.db.flush()
        await self.put_meta("disb", d.id, {"kind": "contingency", "description": body.description, "bills": body.bills})
        return (await self.disb_outs([d]))[0]

    async def pay(self, body: DisbursementPay) -> list[PhdDisbursementOut]:
        """Approved rows → payment batch: ``payroll_ref`` stamped and ``phd.fellowship_payment_requested`` emitted."""
        self.require_writer()
        if not self.payer():
            raise forbidden("phd:fellowship or accounting:post required")
        route = str(await self.setting("phd", "fellowship_payment_route") or "payout")
        rows = list(
            (
                await self.db.execute(
                    select(FellowshipDisbursement)
                    .where(
                        FellowshipDisbursement.id.in_(body.disbursement_ids),
                        FellowshipDisbursement.institution_id == self.inst,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        if any(r.status != "approved" for r in rows):
            raise rule("Only approved disbursements are paid", "NOT_APPROVED")
        outs = await self.disb_outs(rows)
        for r, o in zip(rows, outs, strict=True):
            m = await self.meta("disb", r.id)
            m["payment"] = {"reference": body.reference, "route": route, "requested_at": now_utc().isoformat()}
            await self.put_meta("disb", r.id, m)
            if not (r.payroll_ref or "").startswith("CNT"):
                r.payroll_ref = body.reference[:60]
            await self._emit(
                "phd.fellowship_payment_requested",
                {
                    "disbursement_id": str(r.id),
                    "scholar_id": str(o.scholar_id) if o.scholar_id else None,
                    "amount_paise": r.amount_paise,
                    "route": route,
                    "source_type": "fellowship",
                    "source_id": str(r.id),
                    "reference": body.reference,
                },
                ENTITY,
                r.fellowship_id,
            )
            if body.paid_on is not None:
                await self.mark_paid(r)
        await self.db.flush()
        return await self.disb_outs(rows)

    async def mark_paid(self, r: FellowshipDisbursement) -> None:
        if r.status == "paid":
            return
        r.status, r.paid_at = "paid", now_utc()
        await self.db.flush()
        await self._emit("phd.fellowship_paid", {"disbursement_id": str(r.id)}, ENTITY, r.fellowship_id)
        f = await self._row(r.fellowship_id)
        s = await self.scholar_raw(f.scholar_id)
        await self._notify(
            "phd.fellowship_disbursed",
            [await self.scholar_user(s)],
            {"month": r.month.strftime("%b %Y"), "amount": rupees(r.amount_paise), "status": "paid"},
        )

    async def on_paid(self, source_id: uuid.UUID) -> None:
        r = (
            await self.db.execute(
                select(FellowshipDisbursement).where(FellowshipDisbursement.id == source_id).with_for_update()
            )
        ).scalar_one_or_none()
        if r is not None and r.status == "approved":
            await self.mark_paid(r)

    async def me(self) -> list[PhdDisbursementOut]:
        s = await self.require_my_scholar()
        rows = list(
            (
                await self.db.execute(
                    select(FellowshipDisbursement)
                    .join(ScholarFellowship, ScholarFellowship.id == FellowshipDisbursement.fellowship_id)
                    .where(ScholarFellowship.scholar_id == s.id)
                    .order_by(FellowshipDisbursement.month.desc())
                )
            ).scalars()
        )
        return await self.disb_outs(rows)

    async def statement(self, sid: uuid.UUID, year: int | None = None) -> list[dict[str, Any]]:
        """Agency statement rows (UGC / CSIR formats share the columns)."""
        s = await self.scholar(sid)
        rows = list(
            (
                await self.db.execute(
                    select(FellowshipDisbursement)
                    .join(ScholarFellowship, ScholarFellowship.id == FellowshipDisbursement.fellowship_id)
                    .where(ScholarFellowship.scholar_id == s.id)
                    .order_by(FellowshipDisbursement.month)
                )
            ).scalars()
        )
        return [o.model_dump(mode="json") for o in await self.disb_outs(rows) if year is None or o.month.year == year]

    # ---- Beat ---------------------------------------------------------------------------------------------------------
    async def upgrade_check(self) -> int:
        """Monthly: JRF held ≥ ``jrf_to_srf_months`` with an approved DC meeting recommending SRF → SRF row."""
        today = await self.today()
        months = await self.rule_int("jrf_to_srf_months")
        n = 0
        for f in (
            (
                await self.db.execute(
                    select(ScholarFellowship).where(
                        ScholarFellowship.institution_id == self.inst,
                        ScholarFellowship.fellowship_type == "jrf",
                        ScholarFellowship.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        ):
            if months_between(f.from_on, today) < months:
                continue
            recommended = False
            for mt in (
                await self.db.execute(
                    select(DcMeeting).where(DcMeeting.scholar_id == f.scholar_id, DcMeeting.status == "approved")
                )
            ).scalars():
                if "srf" in (mt.minutes or "").lower() or any(
                    "srf" in str(r.get("text", "")).lower() for r in mt.recommendations or []
                ):
                    recommended = True
            if not recommended:
                continue
            f.status, f.to_on = "closed", today
            await self.db.flush()
            await self.create(
                f.scholar_id,
                FellowshipCreate(
                    fellowship_type="srf",
                    from_on=month_start(today),
                    hra_applicable=f.hra_applicable,
                    funding_source=f.funding_source,
                ),
                upgrade_from=f.id,
            )
            n += 1
        return n

    async def close_for(self, s: ResearchScholar) -> None:
        for f in (
            await self.db.execute(
                select(ScholarFellowship).where(
                    ScholarFellowship.scholar_id == s.id, ScholarFellowship.status != "closed"
                )
            )
        ).scalars():
            f.status, f.to_on = "closed", await self.today()
        await self.db.flush()
