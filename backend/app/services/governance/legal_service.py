"""Legal case register — Prompts/33 §33.6 ``legal_service`` ({governance.legal}).

``case_no`` unique per institution (given, else ``legal`` sequence), court / type / parties / counsel (fee recorded and
announced as ``legal.counsel_fee_recorded`` for Phase 23 expenses), institution-as-petitioner / respondent tagging,
hearings log (``legal:<id>.hearings``) with next-hearing reminders at ``legal.hearing_reminder_days``, outcomes /
judgements, appeals as linked cases. Confidential: only ``legal:manage`` (legal officer) writes and reads documents;
``legal:view_all`` (registrar / principal / auditor) read the register; the owner reads their case. Everyone else 403.
Status counts feed Phase 32 (7.x) and Phase 36 through ``summary``.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.governance import LegalCase
from app.schemas.governance import HearingUpdate, LegalCaseIn, LegalCaseOut, LegalCaseUpdate, LegalOutcome
from app.services.governance.common import GovernanceBase, forbidden, is_auditor, not_found, now_utc, rule

ENTITY = "legal_case"
L = "legal"


class LegalService(GovernanceBase):
    audit_module = L

    def officer(self) -> bool:
        p = self.principal
        return self.system() or (not is_auditor(p) and p.has(L, "manage"))

    def can_read(self) -> bool:
        return self.officer() or self.has_any(L, "view_all")

    def require_officer(self) -> None:
        self.require_writer()
        if not self.officer():
            raise forbidden("legal:manage required")

    async def _row(self, cid: uuid.UUID, *, lock: bool = False) -> LegalCase:
        stmt = select(LegalCase).where(LegalCase.id == cid, LegalCase.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Legal case")
        if not self.can_read():
            sid = await self.my_staff_id()
            if sid is None or r.owner_staff_id != sid:
                raise forbidden("Legal cases are confidential")
        return r

    async def outs(self, rows: list[LegalCase]) -> list[LegalCaseOut]:
        metas = await self.metas("legal", [str(r.id) for r in rows])
        names = await self.staff_names([r.owner_staff_id for r in rows])
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            out.append(
                LegalCaseOut(
                    id=r.id,
                    case_no=r.case_no,
                    court=r.court,
                    case_type=r.case_type,
                    parties=r.parties,
                    institution_role=m.get("institution_role"),
                    counsel=r.counsel,
                    filed_on=r.filed_on,
                    next_hearing=r.next_hearing,
                    status=r.status,
                    outcome=r.outcome,
                    owner_staff_id=r.owner_staff_id,
                    owner_name=names.get(r.owner_staff_id) if r.owner_staff_id else None,
                    hearings=list(m.get("hearings") or []),
                    appeal_of_case_id=uuid.UUID(m["appeal_of"]) if m.get("appeal_of") else None,
                    documents_count=len(r.documents or []),
                    created_at=r.created_at,
                )
            )
        return out

    async def list_cases(self, status: str | None = None, q: str | None = None) -> list[LegalCaseOut]:
        stmt = select(LegalCase).where(LegalCase.institution_id == self.inst)
        if not self.can_read():
            sid = await self.my_staff_id()
            if sid is None:
                raise forbidden("Legal cases are confidential")
            stmt = stmt.where(LegalCase.owner_staff_id == sid)
        if status:
            stmt = stmt.where(LegalCase.status == status)
        if q:
            stmt = stmt.where(LegalCase.case_no.ilike(f"%{q}%") | LegalCase.court.ilike(f"%{q}%"))
        rows = (await self.db.execute(stmt.order_by(LegalCase.next_hearing.asc().nulls_last()))).scalars()
        return await self.outs(list(rows))

    async def get(self, cid: uuid.UUID) -> LegalCaseOut:
        return (await self.outs([await self._row(cid)]))[0]

    async def create(self, body: LegalCaseIn) -> LegalCaseOut:
        self.require_officer()
        case_no = body.case_no or await self.sequence("legal", "LC")
        if (
            await self.db.execute(
                select(LegalCase.id).where(LegalCase.institution_id == self.inst, LegalCase.case_no == case_no)
            )
        ).first():
            raise rule("Case number already registered", "DUPLICATE_CASE_NO")
        r = LegalCase(
            institution_id=self.inst,
            case_no=case_no,
            court=body.court,
            case_type=body.case_type,
            parties=body.parties,
            counsel=body.counsel,
            filed_on=body.filed_on,
            next_hearing=body.next_hearing,
            status="hearing" if body.next_hearing else "open",
            documents=list(body.documents),
            owner_staff_id=body.owner_staff_id or await self.my_staff_id(),
        )
        self.db.add(r)
        await self.db.flush()
        meta: dict[str, Any] = {"institution_role": body.institution_role, "hearings": []}
        if body.appeal_of_case_id:
            parent = await self._row(body.appeal_of_case_id, lock=True)
            parent.status = "appeal"
            meta["appeal_of"] = str(parent.id)
            pm = await self.meta("legal", parent.id)
            pm.setdefault("appeals", []).append(str(r.id))
            await self.put_meta("legal", parent.id, pm)
        if body.counsel_fee_paise:
            meta["counsel_fee_paise"] = body.counsel_fee_paise
            await self._emit(
                "legal.counsel_fee_recorded",
                {"case_id": str(r.id), "amount_paise": body.counsel_fee_paise, "counsel": body.counsel},
                ENTITY,
                r.id,
            )
        await self.put_meta("legal", r.id, meta)
        await self._audit("create", ENTITY, r.id, None, {"case_no": r.case_no, "court": r.court})
        await self._emit("legal.case_created", {"case_id": str(r.id), "case_no": r.case_no}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def update(self, cid: uuid.UUID, body: LegalCaseUpdate) -> LegalCaseOut:
        self.require_officer()
        r = await self._row(cid, lock=True)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(r, k, v)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def hearing(self, cid: uuid.UUID, body: HearingUpdate) -> LegalCaseOut:
        self.require_officer()
        r = await self._row(cid, lock=True)
        if r.status == "closed":
            raise rule("The case is closed", "CASE_CLOSED")
        m = await self.meta("legal", r.id)
        m.setdefault("hearings", []).append(
            {
                "held_on": str(body.held_on),
                "notes": body.notes,
                "next_hearing": str(body.next_hearing) if body.next_hearing else None,
                "by": str(self.actor_id) if self.actor_id else None,
                "at": now_utc().isoformat(),
            }
        )
        await self.put_meta("legal", r.id, m)
        r.next_hearing = body.next_hearing
        if r.status == "open":
            r.status = "hearing"
        await self.db.flush()
        await self._emit(
            "legal.hearing_updated",
            {"case_id": str(r.id), "next_hearing": str(body.next_hearing) if body.next_hearing else None},
            ENTITY,
            r.id,
        )
        return (await self.outs([r]))[0]

    async def outcome(self, cid: uuid.UUID, body: LegalOutcome) -> LegalCaseOut:
        self.require_officer()
        r = await self._row(cid, lock=True)
        r.outcome, r.status = body.outcome, body.status
        if body.status in ("judgement", "closed"):
            r.next_hearing = None
        await self.db.flush()
        await self._audit("outcome", ENTITY, r.id, None, {"status": r.status})
        await self._emit("legal.outcome", {"case_id": str(r.id), "status": r.status}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def documents(self, cid: uuid.UUID) -> list[dict[str, Any]]:
        if not self.officer():
            raise forbidden("Case documents need legal:manage")
        r = await self._row(cid)
        return list(r.documents or [])

    async def calendar(self, days: int = 60) -> list[dict[str, Any]]:
        today = await self.today()
        stmt = select(LegalCase).where(
            LegalCase.institution_id == self.inst,
            LegalCase.next_hearing.is_not(None),
            LegalCase.next_hearing >= today,
            LegalCase.next_hearing <= today + timedelta(days=days),
        )
        if not self.can_read():
            stmt = stmt.where(LegalCase.owner_staff_id == (await self.my_staff_id() or uuid.uuid4()))
        rows = (await self.db.execute(stmt.order_by(LegalCase.next_hearing))).scalars()
        return [
            {
                "case_id": str(r.id),
                "case_no": r.case_no,
                "court": r.court,
                "date": str(r.next_hearing),
                "status": r.status,
            }
            for r in rows
        ]

    async def summary(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(LegalCase.status, func.count())
                .where(LegalCase.institution_id == self.inst)
                .group_by(LegalCase.status)
            )
        ).all()
        return {k: int(v) for k, v in rows}

    async def hearing_reminders(self) -> int:
        today = await self.today()
        offsets = await self.gov_setting("legal.hearing_reminder_days")
        days = [int(x) for x in (offsets if isinstance(offsets, list) else [7, 1])]
        n = 0
        for d in days:
            rows = (
                await self.db.execute(
                    select(LegalCase).where(
                        LegalCase.institution_id == self.inst,
                        LegalCase.next_hearing == today + timedelta(days=d),
                        LegalCase.status != "closed",
                    )
                )
            ).scalars()
            for r in rows:
                users = await self.role_users("legal_officer")
                if r.owner_staff_id:
                    users.append(await self.staff_user(r.owner_staff_id))  # type: ignore[arg-type]
                await self._notify(
                    "legal.hearing_reminder",
                    users,
                    {"case_no": r.case_no, "court": r.court or "", "next_hearing": str(r.next_hearing)},
                )
                n += 1
        return n
