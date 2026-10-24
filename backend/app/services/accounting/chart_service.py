"""Chart of accounts — Prompts/23 §23.6 ``chart_service`` (``accounting.core``).

Hierarchical accounts (code unique per institution; the type is inherited from the parent unless given), deactivation
blocked while postings exist, ``external_ref`` for Tally / Zoho ledger names, import from the IN pack template
(``app/enums/accounting.IN_CHART``, Phase 12 codes kept) or CSV ``code,name,type,parent_code``; mappings (fee heads →
accounts are ``fee_heads.ledger_account_id``; system keys / inventory categories / payroll in ``accounting.mappings``).
Balances per period: income records credit their account, expense records debit theirs.
"""

import csv
import io
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.accounting import IN_CHART
from app.models.accounting import ExpenseRecord, IncomeRecord
from app.models.fees import FeeHead, LedgerAccount
from app.schemas.accounting import AcctAccountIn, AcctAccountOut, AcctAccountUpdate
from app.services.accounting.common import AccountingBase, rule
from app.services.students.common import snap


def seed_chart_sql(conn: Any, institution_id: Any) -> int:
    """Insert the IN chart for a tenant on a sync connection (migration / seeder); returns rows added."""
    from sqlalchemy import text

    added = 0
    for code, name, kind, parent in IN_CHART:
        res = conn.execute(
            text(
                "INSERT INTO ledger_accounts (institution_id, code, name, account_type, parent_id) VALUES (:i, :c, :n, :t, "
                "(SELECT id FROM ledger_accounts WHERE institution_id = :i AND code = :p)) ON CONFLICT (institution_id, code) DO NOTHING"
            ),
            {"i": institution_id, "c": code, "n": name, "t": kind, "p": parent},
        )
        added += res.rowcount or 0
        if parent:
            conn.execute(
                text(
                    "UPDATE ledger_accounts SET parent_id = (SELECT id FROM ledger_accounts WHERE institution_id = :i AND code = :p) "
                    "WHERE institution_id = :i AND code = :c AND parent_id IS NULL"
                ),
                {"i": institution_id, "c": code, "p": parent},
            )
    # Phase 12 fee-head children of 4000 keep their codes; make sure they hang under 4000
    conn.execute(
        text(
            "UPDATE ledger_accounts SET parent_id = (SELECT id FROM ledger_accounts WHERE institution_id = :i AND code = '4000') "
            "WHERE institution_id = :i AND code LIKE '40_0' AND code <> '4000' AND parent_id IS NULL"
        ),
        {"i": institution_id},
    )
    return added


class ChartService(AccountingBase):
    async def balances(self, date_from: date | None, date_to: date | None) -> dict[uuid.UUID, tuple[int, int]]:
        def rng(col: Any, q: Any) -> Any:
            if date_from:
                q = q.where(col >= date_from)
            if date_to:
                q = q.where(col <= date_to)
            return q

        out: dict[uuid.UUID, tuple[int, int]] = {}
        for aid, amt in (
            await self.db.execute(
                rng(
                    IncomeRecord.received_on,
                    select(IncomeRecord.ledger_account_id, func.coalesce(func.sum(IncomeRecord.amount_paise), 0)).where(
                        IncomeRecord.institution_id == self.inst
                    ),
                ).group_by(IncomeRecord.ledger_account_id)
            )
        ).all():
            d, c = out.get(aid, (0, 0))
            out[aid] = (d, c + int(amt))
        for aid, amt in (
            await self.db.execute(
                rng(
                    ExpenseRecord.spent_on,
                    select(
                        ExpenseRecord.ledger_account_id, func.coalesce(func.sum(ExpenseRecord.amount_paise), 0)
                    ).where(ExpenseRecord.institution_id == self.inst, ExpenseRecord.status.in_(("approved", "paid"))),
                ).group_by(ExpenseRecord.ledger_account_id)
            )
        ).all():
            d, c = out.get(aid, (0, 0))
            out[aid] = (d + int(amt), c)
        return out

    def _out(self, a: LedgerAccount, bal: dict[uuid.UUID, tuple[int, int]]) -> AcctAccountOut:
        d, c = bal.get(a.id, (0, 0))
        natural_debit = a.account_type in ("asset", "expense")
        return AcctAccountOut(
            id=a.id,
            code=a.code,
            name=a.name,
            account_type=a.account_type,
            parent_id=a.parent_id,
            external_ref=a.external_ref,
            is_active=a.is_active,
            debit_paise=d,
            credit_paise=c,
            balance_paise=(d - c) if natural_debit else (c - d),
        )

    async def accounts(self) -> list[AcctAccountOut]:
        self.require("view_all", "manage", "view")
        rows = (
            await self.db.execute(
                select(LedgerAccount).where(LedgerAccount.institution_id == self.inst).order_by(LedgerAccount.code)
            )
        ).scalars()
        bal = await self.balances(None, None)
        return [self._out(a, bal) for a in rows]

    async def tree(self, date_from: date | None = None, date_to: date | None = None) -> list[AcctAccountOut]:
        self.require("view_all", "manage")
        rows = list(
            (
                await self.db.execute(
                    select(LedgerAccount).where(LedgerAccount.institution_id == self.inst).order_by(LedgerAccount.code)
                )
            ).scalars()
        )
        bal = await self.balances(date_from, date_to)
        nodes = {a.id: self._out(a, bal) for a in rows}
        roots: list[AcctAccountOut] = []
        for a in rows:
            n = nodes[a.id]
            if a.parent_id and a.parent_id in nodes:
                nodes[a.parent_id].children.append(n)
            else:
                roots.append(n)

        def roll(n: AcctAccountOut) -> tuple[int, int]:
            d, c = n.debit_paise, n.credit_paise
            for ch in n.children:
                cd, cc = roll(ch)
                d, c = d + cd, c + cc
            n.debit_paise, n.credit_paise = d, c
            n.balance_paise = (d - c) if n.account_type in ("asset", "expense") else (c - d)
            return d, c

        for r in roots:
            roll(r)
        return roots

    async def get(self, account_id: uuid.UUID) -> AcctAccountOut:
        self.require("view_all", "manage")
        a = (
            await self.db.execute(
                select(LedgerAccount).where(LedgerAccount.id == account_id, LedgerAccount.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Ledger account not found")
        return self._out(a, await self.balances(None, None))

    async def create(self, body: AcctAccountIn) -> AcctAccountOut:
        self.require("manage")
        if (
            await self.db.execute(
                select(LedgerAccount.id).where(
                    LedgerAccount.institution_id == self.inst, LedgerAccount.code == body.code
                )
            )
        ).first():
            raise rule("Account code already used", "DUPLICATE_CODE")
        kind = body.account_type
        if body.parent_id:
            parent = await self.account_by_id(body.parent_id)
            kind = kind or parent.account_type  # type: ignore[assignment]
        if kind is None:
            raise APIError(
                422, ErrorCode.VALIDATION, "account_type is required for a top-level account", {"field": "account_type"}
            )
        a = LedgerAccount(
            institution_id=self.inst,
            code=body.code,
            name=body.name,
            account_type=kind,
            parent_id=body.parent_id,
            external_ref=body.external_ref,
        )
        self.db.add(a)
        await self.db.flush()
        await self._audit("create", "ledger_account", a.id, None, snap(a, ("code", "name", "account_type")))
        return self._out(a, {})

    async def has_postings(self, account_id: uuid.UUID) -> bool:
        inc = (
            await self.db.execute(select(IncomeRecord.id).where(IncomeRecord.ledger_account_id == account_id).limit(1))
        ).first()
        exp = (
            await self.db.execute(
                select(ExpenseRecord.id).where(ExpenseRecord.ledger_account_id == account_id).limit(1)
            )
        ).first()
        return bool(inc or exp)

    async def update(self, account_id: uuid.UUID, body: AcctAccountUpdate) -> AcctAccountOut:
        self.require("manage")
        a = (
            await self.db.execute(
                select(LedgerAccount).where(LedgerAccount.id == account_id, LedgerAccount.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Ledger account not found")
        data = body.model_dump(exclude_unset=True)
        if data.get("is_active") is False and a.is_active and await self.has_postings(a.id):
            raise rule("The account has postings and cannot be deactivated", "ACCOUNT_IN_USE")
        old = snap(a, ("name", "external_ref", "is_active"))
        for k, v in data.items():
            setattr(a, k, v)
        await self.db.flush()
        await self._audit("update", "ledger_account", a.id, old, snap(a, ("name", "external_ref", "is_active")))
        return self._out(a, await self.balances(None, None))

    async def import_chart(self, template: str | None, csv_text: str | None) -> dict[str, int]:
        self.require("manage")
        conn = await self.db.connection()
        added = 0
        if template:
            added += await conn.run_sync(lambda c: seed_chart_sql(c, self.inst))
        if csv_text:
            for row in csv.DictReader(io.StringIO(csv_text)):
                code = (row.get("code") or "").strip()
                if not code:
                    continue
                exists = (
                    await self.db.execute(
                        select(LedgerAccount.id).where(
                            LedgerAccount.institution_id == self.inst, LedgerAccount.code == code
                        )
                    )
                ).first()
                if exists:
                    continue
                parent = None
                if row.get("parent_code"):
                    parent = (
                        await self.db.execute(
                            select(LedgerAccount).where(
                                LedgerAccount.institution_id == self.inst,
                                LedgerAccount.code == row["parent_code"].strip(),
                            )
                        )
                    ).scalar_one_or_none()
                kind = (row.get("type") or (parent.account_type if parent else "expense")).strip()
                self.db.add(
                    LedgerAccount(
                        institution_id=self.inst,
                        code=code,
                        name=(row.get("name") or code).strip()[:120],
                        account_type=kind,
                        parent_id=parent.id if parent else None,
                    )
                )
                added += 1
            await self.db.flush()
        await self._audit("import", "ledger_account", None, None, {"added": added, "template": template})
        return {"added": added}

    async def get_mappings(self) -> dict[str, Any]:
        self.require("view_all", "manage")
        heads = (
            await self.db.execute(
                select(FeeHead.id, FeeHead.code, FeeHead.name, FeeHead.ledger_account_id).where(
                    FeeHead.institution_id == self.inst
                )
            )
        ).all()
        return {
            "system": await self.mappings(),
            "fee_heads": [
                {"id": str(i), "code": c, "name": n, "ledger_account_id": str(a) if a else None} for i, c, n, a in heads
            ],
        }

    async def put_mappings(self, mappings: dict[str, Any]) -> dict[str, Any]:
        from app.models.platform import InstitutionSetting

        self.require("manage")
        for fh in mappings.pop("fee_heads", []) or []:
            head = (
                await self.db.execute(
                    select(FeeHead).where(FeeHead.id == uuid.UUID(str(fh["id"])), FeeHead.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if head is not None:
                head.ledger_account_id = (
                    uuid.UUID(str(fh["ledger_account_id"])) if fh.get("ledger_account_id") else None
                )
        system = mappings.get("system", mappings)
        merged = {**(await self.mappings()), **system}
        row = (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == "accounting",
                    InstitutionSetting.key == "mappings",
                )
            )
        ).scalar_one_or_none()
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=self.inst,
                    college_id=None,
                    category="accounting",
                    key="mappings",
                    value=merged,
                    value_type="json",
                    updated_by=self.actor_id,
                )
            )
        else:
            row.value, row.updated_by = merged, self.actor_id
        await self.db.flush()
        await self._audit("mappings", "ledger_account", None, None, {"keys": sorted(system)})
        return await self.get_mappings()
