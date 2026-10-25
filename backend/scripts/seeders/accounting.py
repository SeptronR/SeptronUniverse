"""``accounting`` demo seeder (Prompts/23 §23.2) — ``seed_demo_institution.py --only accounting``.

Enables the accounting features, makes sure the IN chart exists, generates the automatic postings from the seeded fee
payments / refunds, paid vendor bills and paid payroll (idempotent by source, through ``PostingService.replay``), then
~300 manual income / expense records across statuses, budgets for the current year per department (utilisation
40–110 %), 5 grant ledgers (the first with ``faculty.1`` as PI) with receipts and head-wise expenses, 3 bank
reconciliations (one open with 4 unmatched rows) and 2 voucher exports. Idempotent: skipped when budget heads exist.
"""

import random
import uuid
from datetime import timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("accounting", after=["fees", "hr", "inventory"])
async def seed_accounting(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.enums.accounting import GRANT_HEADS
    from app.models.academic import AcademicYear
    from app.models.accounting import (
        AccountingExport,
        BankReconciliation,
        BudgetHead,
        ExpenseRecord,
        GrantLedger,
        IncomeRecord,
    )
    from app.models.fees import FeePayment, LedgerAccount
    from app.models.hr import Staff
    from app.models.platform import Department, Institution, InstitutionSetting, User
    from app.services.accounting.chart_service import seed_chart_sql
    from app.services.accounting.posting_service import PostingService
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(23)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(BudgetHead).where(BudgetHead.institution_id == inst.id))
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "accounting.core",
        "accounting.budgets",
        "accounting.grants_ledger",
        "accounting.gst_reports",
        "accounting.tally_export",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 23)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   accounting: {key} not enabled ({exc})")

    conn = await db.connection()
    added = await conn.run_sync(lambda c: seed_chart_sql(c, inst.id))
    ctx.count("ledger_accounts", added)
    today = today_for(inst)
    accts = {
        a.code: a
        for a in (await db.execute(select(LedgerAccount).where(LedgerAccount.institution_id == inst.id))).scalars()
    }

    # ---- automatic postings from the seeded sources ------------------------------------------------------------------------
    first_pay = (
        await db.execute(select(func.min(FeePayment.payment_date)).where(FeePayment.institution_id == inst.id))
    ).scalar_one() or today - timedelta(days=365)
    poster = PostingService(db, None, institution_id=inst.id)
    out = await poster.replay(first_pay, today)
    ctx.count("auto_postings", sum(out.values()))

    # ---- budgets ---------------------------------------------------------------------------------------------------------
    year = (
        await db.execute(
            select(AcademicYear)
            .where(AcademicYear.institution_id == inst.id)
            .order_by(AcademicYear.is_current.desc(), AcademicYear.start_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if year is None:
        print("   accounting: no academic year — run the institution seeder first")
        return
    depts = list((await db.execute(select(Department).where(Department.institution_id == inst.id))).scalars())
    heads: list[BudgetHead] = []
    for d in depts:
        for name, code, alloc in (
            ("Consumables", "5300", 600000_00 // 100),
            ("Lab equipment", "1430", 2500000_00 // 100),
            ("Travel", "5700", 150000_00 // 100),
            ("Events & seminars", "5800", 300000_00 // 100),
        ):
            allocated = int(alloc * 100 * rng.uniform(0.6, 1.4))
            pct = rng.uniform(0.4, 1.1)
            h = BudgetHead(
                institution_id=inst.id,
                academic_year_id=year.id,
                college_id=d.college_id,
                department_id=d.id,
                name=f"{d.code} {name}",
                ledger_account_id=accts[code].id if code in accts else None,
                allocated_paise=allocated,
                utilised_paise=int(allocated * pct * 0.8),
                committed_paise=int(allocated * pct * 0.2),
                status="approved",
            )
            db.add(h)
            heads.append(h)
    db.add(
        BudgetHead(
            institution_id=inst.id,
            academic_year_id=year.id,
            name="Institution utilities",
            ledger_account_id=accts["5600"].id if "5600" in accts else None,
            allocated_paise=1200000000,
            utilised_paise=700000000,
            status="approved",
        )
    )
    await db.flush()
    ctx.count("budget_heads", len(heads) + 1)

    # ---- manual income / expenses (~300) -----------------------------------------------------------------------------------
    accountant = (
        await db.execute(select(User.id).where(User.institution_id == inst.id, User.username == "accountant"))
    ).scalar_one_or_none()
    hod = (
        await db.execute(select(User.id).where(User.institution_id == inst.id, User.username == "hod.cse"))
    ).scalar_one_or_none()
    inc_codes = [c for c in ("4520", "4530", "4550", "4590", "4540") if c in accts]
    for k in range(80):
        db.add(
            IncomeRecord(
                institution_id=inst.id,
                ledger_account_id=accts[rng.choice(inc_codes)].id,
                amount_paise=rng.randint(5000, 500000) * 100,
                received_on=today - timedelta(days=rng.randint(1, 300)),
                source_type="manual",
                description=rng.choice(
                    ["Hall rent", "FD interest", "Donation from alumni", "Library fines", "Scrap sale", "Workshop fee"]
                ),
                reference_no=f"MR{k + 1:04d}",
                payment_mode=rng.choice(["bank", "bank", "cash", "upi"]),
                recorded_by=accountant,
            )
        )
    exp_codes = [c for c in ("5300", "5310", "5320", "5500", "5600", "5700", "5800", "5910", "5990") if c in accts]
    statuses = ["recorded"] * 25 + ["submitted"] * 30 + ["approved"] * 40 + ["paid"] * 115 + ["rejected"] * 10
    for k, st in enumerate(statuses):
        h = rng.choice(heads) if heads and k % 2 == 0 else None
        amount = rng.randint(1000, 90000) * 100
        db.add(
            ExpenseRecord(
                institution_id=inst.id,
                college_id=h.college_id if h else None,
                department_id=h.department_id if h else None,
                ledger_account_id=(
                    h.ledger_account_id if h and h.ledger_account_id else accts[rng.choice(exp_codes)].id
                ),
                budget_head_id=h.id if h else None,
                amount_paise=amount,
                spent_on=today - timedelta(days=rng.randint(1, 250)),
                payee=rng.choice(
                    ["Kaveri Electricals", "BESCOM", "KSRTC", "Sri Stationers", "Local vendor", "Audit firm LLP"]
                ),
                description=rng.choice(
                    [
                        "Lab maintenance",
                        "Electricity bill",
                        "Staff travel",
                        "Seminar expenses",
                        "Office supplies",
                        "Statutory audit",
                    ]
                ),
                reference_no=f"EX{k + 1:04d}",
                document_url="uploads/demo/voucher.pdf" if amount > 1000000 else None,
                status=st,
                recorded_by=hod if h and k % 3 == 0 else accountant,
            )
        )
    await db.flush()
    ctx.count("income_records", 80)
    ctx.count("expense_records", len(statuses))

    # ---- grants -------------------------------------------------------------------------------------------------------------
    pi = (
        await db.execute(
            select(Staff.id)
            .join(User, User.id == Staff.user_id)
            .where(User.institution_id == inst.id, User.username == "faculty.1")
        )
    ).scalar_one_or_none()
    agencies = ["DST-SERB", "AICTE", "UGC", "DBT", "ISRO RESPOND"]
    for g_no in range(5):
        sanctioned = rng.choice([1000000, 2500000, 4000000, 750000]) * 100
        alloc = [int(sanctioned * w) for w in (0.35, 0.3, 0.12, 0.08, 0.1, 0.05)]
        heads_json = [
            {"name": n, "allocated_paise": a, "utilised_paise": 0} for n, a in zip(GRANT_HEADS, alloc, strict=False)
        ]
        received = int(sanctioned * rng.choice([0.4, 0.6, 1.0]))
        g = GrantLedger(
            institution_id=inst.id,
            name=f"{agencies[g_no]} project {g_no + 1}",
            funding_agency=agencies[g_no],
            sanctioned_paise=sanctioned,
            received_paise=received,
            budget_heads=heads_json,
        )
        db.add(g)
        await db.flush()
        db.add(
            IncomeRecord(
                institution_id=inst.id,
                ledger_account_id=accts["4510"].id,
                amount_paise=received,
                received_on=today - timedelta(days=200),
                source_type="grant_receipt",
                source_id=g.id,
                description=f"Grant instalment · {g.name}",
                payment_mode="bank",
            )
        )
        used = 0
        for h in heads_json:
            spend = int(h["allocated_paise"] * rng.uniform(0.1, 0.6))
            if used + spend > received:
                break
            h["utilised_paise"] = spend
            used += spend
            db.add(
                ExpenseRecord(
                    institution_id=inst.id,
                    ledger_account_id=accts["5990"].id,
                    amount_paise=spend,
                    spent_on=today - timedelta(days=rng.randint(10, 150)),
                    payee=f"[grant:{g.id}]",
                    description=f"{h['name']} · project spend",
                    status="paid",
                )
            )
        g.budget_heads, g.utilised_paise = heads_json, used
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="accounting_meta",
                key=f"grant:{g.id}",
                value={"pi_staff_id": str(pi) if pi and g_no == 0 else None, "reallocation_allowed": g_no != 3},
                value_type="json",
            )
        )  # noqa: PLR2004
    await db.flush()
    ctx.count("grant_ledgers", 5)

    # ---- reconciliations + exports -------------------------------------------------------------------------------------------
    pays = list(
        (
            await db.execute(
                select(FeePayment)
                .where(FeePayment.institution_id == inst.id, FeePayment.status == "success")
                .order_by(FeePayment.payment_date.desc())
                .limit(30)
            )
        ).scalars()
    )
    for n, (ago, status) in enumerate(((60, "reconciled"), (30, "reconciled"), (2, "open"))):
        items = []
        for p in pays[n * 8 : n * 8 + 6]:
            items.append(
                {
                    "id": uuid.uuid4().hex[:12],
                    "row": {
                        "date": p.payment_date.isoformat(),
                        "description": f"NEFT {p.receipt_number}",
                        "reference": p.utr or p.reference_no,
                        "amount_paise": p.amount_paise,
                    },
                    "status": "matched",
                    "matched_type": "fee_payment",
                    "matched_id": str(p.id),
                    "remark": None,
                }
            )
        if status == "open":
            for j, amt in enumerate((-35400, 128000, -2360, 500000)):
                items.append(
                    {
                        "id": uuid.uuid4().hex[:12],
                        "row": {
                            "date": (today - timedelta(days=3 + j)).isoformat(),
                            "description": rng.choice(["BANK CHARGES", "UNKNOWN CREDIT", "SMS CHARGES", "CHQ DEP"]),
                            "reference": f"STMT{j}",
                            "amount_paise": amt,
                        },
                        "status": "unmatched",
                        "matched_type": None,
                        "matched_id": None,
                        "remark": None,
                    }
                )
        unmatched = sum(i["row"]["amount_paise"] for i in items if i["status"] == "unmatched")
        db.add(
            BankReconciliation(
                institution_id=inst.id,
                bank_account="SBI current A/c ••1234",
                statement_date=today - timedelta(days=ago),
                statement_balance_paise=rng.randint(10**8, 10**9),
                ledger_balance_paise=rng.randint(10**8, 10**9),
                difference_paise=unmatched,
                items=items,
                status=status,
                reconciled_by=accountant if status == "reconciled" else None,
            )
        )
    for target, months in (("tally", 2), ("csv", 1)):
        start = (today.replace(day=1) - timedelta(days=30 * months)).replace(day=1)
        db.add(
            AccountingExport(
                institution_id=inst.id,
                target=target,
                period_from=start,
                period_to=start + timedelta(days=27),
                status="ready",
                file_url=f"demo/accounting-exports/{target}-{start}.{'xml' if target == 'tally' else 'csv'}",
                requested_by=accountant,
            )
        )
    await db.flush()
    ctx.count("bank_reconciliations", 3)
    ctx.count("accounting_exports", 2)
