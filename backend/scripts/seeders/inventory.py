"""``inventory`` demo seeder (Prompts/22 §22.2) — ``seed_demo_institution.py --only inventory``.

Enables the inventory features and creates the demo users ``inv.mgr`` (inventory manager), ``store.central`` /
``store.cse`` (store keepers of the central and the CSE store) and the supplier portal users ``vendor.a`` / ``vendor.b``
(passwords go to ``LOCAL_TEST_CREDENTIALS.md`` only). Then 40 suppliers, 6 stores (central, CSE, ECE, MBA, chemistry
lab, hostel), 300 items (30 hazardous with safety data) with opening stock, 80 indents in every status, three quotations
for the approved indents above the three-quote threshold, 25 POs (5 partially received) with GRNs, ~500 issue
transactions, 400 assets (200 labelled, 20 condemned), 2 audit cycles and 30 vendor bills. Idempotent: skipped when
suppliers exist.
"""

import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

USERS = [
    # (username, display, role slug, scope, credential label, employee id)
    ("inv.mgr", "Inventory Manager", "inventory_manager", "institution", "inv_mgr", "S9101"),
    ("store.central", "Central Store Keeper", "store_keeper", "self", "store_central", "S9102"),
    ("store.cse", "CSE Store Keeper", "store_keeper", "self", "store_cse", "S9103"),
]
ITEM_NAMES = {
    "Stationery": ["A4 paper ream", "Ball pen (blue)", "Whiteboard marker", "Stapler", "File folder", "Notebook 200p"],
    "Lab consumables": [
        "Test tube 15 ml",
        "Beaker 250 ml",
        "Filter paper",
        "Pipette tips",
        "Petri dish",
        "Glass slide",
    ],
    "Chemicals": ["Hydrochloric acid", "Sulphuric acid", "Acetone", "Ethanol 99%", "Sodium hydroxide", "Methanol"],
    "IT hardware": [
        "Desktop computer",
        "Laptop",
        "LED monitor 24in",
        "Network switch 24p",
        "Projector",
        "Laser printer",
    ],
    "Furniture": ["Student desk", "Office chair", "Steel almirah", "Lab stool", "Conference table", "Bookshelf"],
    "Electrical": ["LED tube light", "Extension board", "MCB 16A", "Ceiling fan", "Copper wire 1.5mm", "Switch board"],
    "Cleaning": ["Floor cleaner 5L", "Hand wash 500ml", "Broom", "Mop", "Garbage bags", "Toilet cleaner"],
    "Sports": ["Football", "Cricket bat", "Badminton racket", "Shuttle cock tube", "Volleyball", "Chess set"],
    "Library": ["Book jacket", "Barcode labels", "Book stand", "Library card", "Spine labels", "Book tape"],
}


@seeder("inventory", after=["students", "hr", "fees", "timetable"])
async def seed_inventory(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password, _phone

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import hash_password
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.enums.inventory import DEFAULT_CATEGORIES
    from app.models.hr import Staff
    from app.models.inventory import (
        Asset,
        AssetAudit,
        GoodsReceipt,
        Indent,
        InventoryCategory,
        Item,
        PurchaseOrder,
        PurchaseOrderItem,
        Quotation,
        StockLevel,
        StockTransaction,
        Store,
        Supplier,
        VendorBill,
    )
    from app.models.platform import College, Department, Institution, InstitutionSetting, Role, User, UserRole
    from app.models.timetable import Room
    from app.services.feature_service import FeatureService
    from app.services.inventory.asset_service import asset_token

    db = ctx.db
    rng = random.Random(22)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(Supplier).where(Supplier.institution_id == inst.id))
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "inventory.core",
        "inventory.procurement",
        "inventory.vendor_portal",
        "inventory.lab_consumables",
        "inventory.assets",
        "inventory.asset_qr",
        "inventory.bills",
        "inventory.vendor_store",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 22)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   inventory: {key} not enabled ({exc})")

    today = today_for(inst)
    now = datetime.now(UTC)
    roles = {r.slug: r for r in (await db.execute(select(Role).where(Role.institution_id == inst.id))).scalars()}
    depts = {
        d.code: d for d in (await db.execute(select(Department).where(Department.institution_id == inst.id))).scalars()
    }
    colleges = list(
        (await db.execute(select(College).where(College.institution_id == inst.id).order_by(College.code))).scalars()
    )
    rooms = list((await db.execute(select(Room.id).where(Room.institution_id == inst.id).limit(60))).scalars())

    async def user(username: str, display: str, slug: str, scope: str, label: str, user_type: str = "staff") -> User:
        u = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == username))
        ).scalar_one_or_none()
        if u is None:
            pwd = _password()
            u = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@{ctx.profile['slug']}.septronuniverse.in",
                phone=_phone(username),
                display_name=display,
                user_type=user_type,
                password_hash=hash_password(pwd),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
            )
            db.add(u)
            await db.flush()
            ctx.count("users")
            ctx.credentials.append((label, username, pwd))
        if (
            slug in roles
            and (
                await db.execute(select(UserRole).where(UserRole.user_id == u.id, UserRole.role_id == roles[slug].id))
            ).scalar_one_or_none()
            is None
        ):
            db.add(
                UserRole(institution_id=inst.id, user_id=u.id, role_id=roles[slug].id, scope_type=scope, scope_id=None)
            )
            ctx.count("user_roles")
        return u

    staff: dict[str, Staff] = {}
    for username, display, slug, scope, label, emp in USERS:
        if slug not in roles:
            print(f"   inventory: role {slug} missing — run alembic upgrade (0022) first")
            return
        u = await user(username, display, slug, scope, label)
        st = (await db.execute(select(Staff).where(Staff.user_id == u.id))).scalar_one_or_none()
        if st is None:
            first, _, last = display.partition(" ")
            st = Staff(
                institution_id=inst.id,
                college_id=colleges[0].id if colleges else None,
                user_id=u.id,
                employee_id=emp,
                first_name=first,
                last_name=last or None,
                department_id=depts["CSE"].id if username == "store.cse" and "CSE" in depts else None,
                phone=u.phone,
                staff_category="non_teaching",
            )
            db.add(st)
            await db.flush()
            ctx.count("staff")
        staff[username] = st
    requesters = list(
        (
            await db.execute(
                select(User.id, Staff.department_id)
                .join(Staff, Staff.user_id == User.id)
                .where(User.institution_id == inst.id, Staff.department_id.is_not(None))
                .limit(30)
            )
        ).all()
    )
    custodians = list(
        (await db.execute(select(Staff.id, Staff.department_id).where(Staff.institution_id == inst.id).limit(80))).all()
    )

    # ---- categories, suppliers, stores, items ---------------------------------------------------------------------------
    cats: dict[str, InventoryCategory] = {
        c.name: c
        for c in (
            await db.execute(select(InventoryCategory).where(InventoryCategory.institution_id == inst.id))
        ).scalars()
    }
    for name, consumable in DEFAULT_CATEGORIES:
        if name not in cats:
            cats[name] = InventoryCategory(institution_id=inst.id, name=name, is_consumable=consumable)
            db.add(cats[name])
    await db.flush()

    suppliers: list[Supplier] = []
    prefixes = ["Sri", "Om", "Vijaya", "Kaveri", "National", "Global", "Prime", "Metro", "Sapthagiri", "Deccan"]
    kinds = ["Traders", "Enterprises", "Scientific", "Systems", "Furnishers", "Agencies", "Corporation", "Suppliers"]
    for n in range(40):
        pan = f"{''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(5))}{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}"
        s = Supplier(
            institution_id=inst.id,
            name=f"{prefixes[n % 10]} {kinds[n % 8]} {n + 1}",
            code=f"SUP{n + 1:03d}",
            gstin=f"29{pan}1Z{rng.randint(0, 9)}",
            pan=pan,
            contact={
                "email": f"sales{n + 1}@supplier{n + 1}.example.in",
                "phone": f"+9180400{n:05d}",
                "supplier_type": rng.choice(["company", "firm", "individual"]),
            },
            address={"city": "Bengaluru", "state": "KA"},
            categories=[rng.choice(list(ITEM_NAMES))],
            bank_details_encrypted=json.dumps(
                {"account_no": f"50100{n:07d}", "ifsc": "HDFC0001234", "bank": "HDFC Bank"}
            ),
            rating=Decimal(str(round(rng.uniform(2.5, 5), 2))),
            status="registered" if n in (38, 39) else ("blacklisted" if n == 37 else "active"),
        )
        db.add(s)
        suppliers.append(s)
    await db.flush()
    for i, uname in enumerate(("vendor.a", "vendor.b")):
        vu = await user(uname, suppliers[i].name, "vendor", "self", uname.replace(".", "_"), user_type="external")
        suppliers[i].portal_user_id = vu.id
        suppliers[i].contact = {**(suppliers[i].contact or {}), "email": vu.email}
    ctx.count("suppliers", len(suppliers))

    store_specs = [
        ("Central Store", "central", None, staff["store.central"].id),
        ("CSE Department Store", "department", "CSE", staff["store.cse"].id),
        ("ECE Department Store", "department", "ECE", None),
        ("MBA Department Store", "department", "MBA", None),
        ("Chemistry Lab Store", "lab", None, staff["store.central"].id),
        ("Hostel Store", "hostel", None, None),
    ]
    stores: list[Store] = []
    for name, kind, dcode, keeper in store_specs:
        dept = depts.get(dcode) if dcode else None
        st = Store(
            institution_id=inst.id,
            college_id=(dept.college_id if dept else (colleges[0].id if colleges else None)),
            department_id=dept.id if dept else None,
            name=name,
            store_type=kind,
            keeper_staff_id=keeper,
        )
        db.add(st)
        stores.append(st)
    await db.flush()
    ctx.count("stores", len(stores))

    items: list[Item] = []
    n = 0
    for cat, names in ITEM_NAMES.items():
        for base in names:
            variants = 6 if cat not in ("Chemicals",) else 5
            for v in range(variants):
                n += 1
                if n > 300:  # noqa: PLR2004
                    break
                hazardous = cat == "Chemicals"
                consumable = cats[cat].is_consumable
                cost = rng.randint(2000, 90000) if consumable else rng.randint(300000, 7500000)
                it = Item(
                    institution_id=inst.id,
                    category_id=cats[cat].id,
                    item_code=f"ITM{n:05d}",
                    name=f"{base}" + (f" (grade {chr(65 + v)})" if v else ""),
                    unit="l" if hazardous else ("nos" if not consumable else rng.choice(["nos", "pack", "box"])),
                    is_consumable=consumable,
                    is_hazardous=hazardous,
                    safety_data={
                        "hazard_class": rng.choice(["corrosive", "flammable", "toxic"]),
                        "storage": "Ventilated chemical cabinet",
                        "msds_url": "https://example.org/msds",
                        "disposal": "Neutralise before disposal",
                        "expiry": (today + timedelta(days=rng.randint(10, 400))).isoformat(),
                    }
                    if hazardous
                    else None,
                    min_stock_level=Decimal(rng.choice([5, 10, 20, 50])) if consumable else None,
                    reorder_qty=Decimal(rng.choice([20, 50, 100])) if consumable else None,
                    unit_cost_paise=cost,
                    gst_rate=Decimal(rng.choice(["5", "12", "18"])),
                )
                db.add(it)
                items.append(it)
    await db.flush()
    ctx.count("items", len(items))
    consumables = [i for i in items if i.is_consumable]
    durables = [i for i in items if not i.is_consumable]

    # opening stock (receipt transactions) and levels
    txns = 0
    for st in stores:
        pool = rng.sample(consumables, min(len(consumables), 60 if st.store_type == "central" else 25))
        for it in pool:
            qty = Decimal(rng.randint(0, 150))
            if qty == 0 and rng.random() < 0.5:  # noqa: PLR2004
                qty = Decimal(rng.randint(1, 4))
            db.add(StockLevel(institution_id=inst.id, store_id=st.id, item_id=it.id, quantity=qty))
            db.add(
                StockTransaction(
                    institution_id=inst.id,
                    store_id=st.id,
                    item_id=it.id,
                    txn_type="receipt",
                    quantity=qty,
                    unit_cost_paise=it.unit_cost_paise,
                    reference_type="opening",
                    remarks="Opening balance",
                    performed_by=None,
                    occurred_at=now - timedelta(days=200),
                )
            )
            txns += 1
    await db.flush()
    levels = {
        (lv.store_id, lv.item_id): lv
        for lv in (await db.execute(select(StockLevel).where(StockLevel.institution_id == inst.id))).scalars()
    }

    # issues (~500)
    for _ in range(500):
        (sid, iid), lv = rng.choice(list(levels.items()))
        if lv.quantity < 2:  # noqa: PLR2004
            continue
        q = Decimal(rng.randint(1, max(1, int(lv.quantity) // 4)))
        lv.quantity -= q
        st = next(s for s in stores if s.id == sid)
        dept_id = st.department_id or rng.choice(list(depts.values())).id
        it = next(i for i in items if i.id == iid)
        db.add(
            StockTransaction(
                institution_id=inst.id,
                store_id=sid,
                item_id=iid,
                txn_type="issue",
                quantity=-q,
                unit_cost_paise=it.unit_cost_paise,
                issued_to_type="department",
                issued_to_id=dept_id,
                remarks="[safety_ack] lab issue" if it.is_hazardous else None,
                occurred_at=now - timedelta(days=rng.randint(1, 180)),
            )
        )
        txns += 1
    await db.flush()
    ctx.count("stock_transactions", txns)

    # ---- indents ---------------------------------------------------------------------------------------------------------
    statuses = (
        ["draft"] * 10
        + ["submitted"] * 12
        + ["hod_approved"] * 8
        + ["approved"] * 25
        + ["rejected"] * 7
        + ["fulfilled"] * 12
        + ["closed"] * 6
    )
    indents: list[Indent] = []
    for k, status in enumerate(statuses):
        uid, dept_id = (
            rng.choice(requesters)
            if requesters
            else (staff["store.cse"].user_id, depts["CSE"].id if "CSE" in depts else None)
        )
        lines = []
        for it in rng.sample(items, rng.randint(1, 4)):
            qty = rng.randint(1, 20) if it.is_consumable else rng.randint(1, 10)
            lines.append(
                {
                    "item_id": str(it.id),
                    "name": it.name,
                    "qty": qty,
                    "unit": it.unit,
                    "est_unit_cost_paise": it.unit_cost_paise,
                    "issued": qty if status == "fulfilled" else 0,
                    "procured": 0,
                }
            )
        if k % 9 == 0:
            lines.append(
                {
                    "item_id": None,
                    "free_text": "Custom lab fixture",
                    "qty": 1,
                    "unit": "nos",
                    "est_unit_cost_paise": 450000,
                    "issued": 0,
                    "procured": 0,
                }
            )
        ind = Indent(
            institution_id=inst.id,
            indent_number=f"IND/{today.year}/{k + 1:05d}",
            department_id=dept_id,
            store_id=stores[0].id,
            requested_by=uid,
            purpose=rng.choice(
                [
                    "Semester lab requirement",
                    "Department office supplies",
                    "New lab setup",
                    "Replacement of damaged items",
                    "Seminar hall upgrade",
                ]
            ),
            priority="emergency" if k == 30 else rng.choice(["normal", "normal", "high", "low"]),
            items=lines,
            estimated_paise=int(sum(Decimal(str(x["qty"])) * Decimal(x["est_unit_cost_paise"] or 0) for x in lines)),
            status=status,
            created_at=now - timedelta(days=rng.randint(2, 120)),
        )
        db.add(ind)
        indents.append(ind)
    await db.flush()
    ctx.count("indents", len(indents))

    # quotations for approved indents above the three-quote threshold
    active_sup = [s for s in suppliers if s.status == "active"]
    quotes = 0
    approved = [i for i in indents if i.status == "approved"]
    for ind in approved:
        if (ind.estimated_paise or 0) <= 2500000:  # noqa: PLR2004
            continue
        for s in rng.sample(active_sup, 3):
            lines = [
                {
                    "line": n_,
                    "item_id": x.get("item_id"),
                    "qty": x["qty"],
                    "unit_price_paise": int((x["est_unit_cost_paise"] or 100000) * rng.uniform(0.85, 1.15)),
                    "tax_rate": 18,
                }
                for n_, x in enumerate(ind.items)
            ]
            db.add(
                Quotation(
                    institution_id=inst.id,
                    indent_id=ind.id,
                    supplier_id=s.id,
                    reference=f"Q-{s.code}-{ind.indent_number[-5:]}",
                    items=lines,
                    total_paise=int(
                        sum(Decimal(str(x["qty"])) * x["unit_price_paise"] * Decimal("1.18") for x in lines)
                    ),
                    valid_until=today + timedelta(days=30),
                )
            )
            quotes += 1
    await db.flush()
    ctx.count("quotations", quotes)

    # ---- POs + GRNs ------------------------------------------------------------------------------------------------------
    pos: list[PurchaseOrder] = []
    grns = 0
    po_sources = (approved + [i for i in indents if i.status == "closed"])[:25]
    for k, ind in enumerate(po_sources):
        s = rng.choice(suppliers[:2]) if k < 6 else rng.choice(active_sup)
        lines = [x for x in ind.items if x.get("item_id")]
        if not lines:
            continue
        status = "received" if k % 5 else "partially_received"
        if k >= 20:  # noqa: PLR2004
            status = rng.choice(["approved", "sent"])
        p = PurchaseOrder(
            institution_id=inst.id,
            po_number=f"PO/{today.year}/{k + 1:05d}",
            supplier_id=s.id,
            indent_id=ind.id,
            order_date=today - timedelta(days=60 - k),
            expected_date=today - timedelta(days=30 - k),
            terms="Delivery to the central store; payment 30 days after GRN.",
            status=status,
            created_by=staff["inv.mgr"].user_id,
        )
        db.add(p)
        await db.flush()
        sub = tax = 0
        grn_lines = []
        for x in lines:
            it = next(i for i in items if str(i.id) == x["item_id"])
            price = int(it.unit_cost_paise or 10000)
            qty = Decimal(str(x["qty"]))
            recv = qty if status == "received" else (qty // 2 if status == "partially_received" else Decimal(0))
            pi = PurchaseOrderItem(
                institution_id=inst.id,
                po_id=p.id,
                item_id=it.id,
                quantity=qty,
                unit_price_paise=price,
                tax_rate=it.gst_rate,
                received_qty=recv,
            )
            db.add(pi)
            await db.flush()
            sub += int(qty * price)
            tax += int(qty * price * (it.gst_rate or 0) / 100)
            if recv > 0:
                grn_lines.append(
                    {
                        "po_item_id": str(pi.id),
                        "item_id": str(it.id),
                        "item": it.name,
                        "qty_received": float(recv),
                        "qty_rejected": 0.0,
                        "accepted": float(recv),
                        "unit_price_paise": price,
                        "is_consumable": it.is_consumable,
                    }
                )
                if it.is_consumable:
                    key = (stores[0].id, it.id)
                    if key in levels:
                        levels[key].quantity += recv
                    else:
                        levels[key] = StockLevel(
                            institution_id=inst.id, store_id=stores[0].id, item_id=it.id, quantity=recv
                        )
                        db.add(levels[key])
            x["procured"] = float(qty)
        p.subtotal_paise, p.tax_paise, p.total_paise = sub, tax, sub + tax
        if grn_lines:
            g = GoodsReceipt(
                institution_id=inst.id,
                grn_number=f"GRN/{today.year}/{grns + 1:05d}",
                po_id=p.id,
                store_id=stores[0].id,
                received_on=today - timedelta(days=25 - k),
                received_by=staff["store.central"].user_id,
                invoice_no=f"INV-{s.code}-{k + 1}",
                items=grn_lines,
            )
            db.add(g)
            await db.flush()
            grns += 1
            for gl in grn_lines:
                db.add(
                    StockTransaction(
                        institution_id=inst.id,
                        store_id=stores[0].id,
                        item_id=uuid.UUID(gl["item_id"]),
                        txn_type="receipt",
                        quantity=Decimal(str(gl["accepted"])),
                        unit_cost_paise=gl["unit_price_paise"],
                        reference_type="grn",
                        reference_id=g.id,
                    )
                )
            if k < 30 and status == "received":  # noqa: PLR2004
                db.add(
                    VendorBill(
                        institution_id=inst.id,
                        supplier_id=s.id,
                        po_id=p.id,
                        grn_id=g.id,
                        bill_number=f"B-{s.code}-{k + 1:03d}",
                        bill_date=g.received_on,
                        due_date=g.received_on + timedelta(days=30),
                        subtotal_paise=sub,
                        tax_paise=tax,
                        tds_paise=int(sub * 0.02) if sub > 3000000 else 0,  # noqa: PLR2004
                        total_paise=sub + tax,
                        status=rng.choice(["received", "verified", "approved", "paid", "paid", "on_hold"]),
                    )
                )
        ind.items = [dict(x) for x in ind.items]
        pos.append(p)
    await db.flush()
    # pad the bills to 30 with stand-alone service bills
    bills = (
        await db.execute(select(func.count()).select_from(VendorBill).where(VendorBill.institution_id == inst.id))
    ).scalar_one()
    for k in range(max(0, 30 - bills)):
        s = rng.choice(active_sup)
        sub = rng.randint(200000, 4000000)
        db.add(
            VendorBill(
                institution_id=inst.id,
                supplier_id=s.id,
                bill_number=f"SB-{s.code}-{k + 1:03d}",
                bill_date=today - timedelta(days=rng.randint(1, 120)),
                due_date=today - timedelta(days=rng.randint(-20, 90)),
                subtotal_paise=sub,
                tax_paise=int(sub * 0.18),
                tds_paise=int(sub * 0.02) if sub > 3000000 else 0,  # noqa: PLR2004
                total_paise=int(sub * 1.18),
                status=rng.choice(["received", "verified", "approved", "paid"]),
            )
        )
    await db.flush()
    ctx.count("purchase_orders", len(pos))
    ctx.count("goods_receipts", grns)
    ctx.count("vendor_bills", 30)

    # ---- assets ----------------------------------------------------------------------------------------------------------
    assets: list[Asset] = []
    for k in range(400):
        it = rng.choice(durables) if durables else None
        cust_id, cust_dept = rng.choice(custodians) if custodians else (None, None)
        cat = "IT hardware" if it and it.category_id == cats["IT hardware"].id else "Furniture"
        cost = int(it.unit_cost_paise or 500000) if it else 500000
        bought = today - timedelta(days=rng.randint(30, 2000))
        years = (today - bought).days / 365
        rate = Decimal("33.33") if cat == "IT hardware" else Decimal("10")
        method = "slm" if cat == "IT hardware" else "wdv"
        value = (
            max(cost * 0.05, cost * (1 - float(rate) / 100 * years))
            if method == "slm"
            else cost * (1 - float(rate) / 100) ** years
        )
        a = Asset(
            institution_id=inst.id,
            college_id=colleges[0].id if colleges else None,
            asset_tag=f"AST{k + 1:06d}",
            name=it.name if it else "Asset",
            category=cat,
            item_id=it.id if it else None,
            serial_no=f"SN{rng.randint(10**7, 10**8)}",
            location_room_id=rng.choice(rooms) if rooms else None,
            custodian_staff_id=cust_id,
            department_id=cust_dept,
            purchase_date=bought,
            cost_paise=cost,
            po_id=rng.choice(pos).id if pos and k % 4 == 0 else None,
            warranty_until=bought + timedelta(days=rng.choice([365, 730, 1095])),
            depreciation_method=method,
            depreciation_rate=rate,
            current_value_paise=int(value),
            is_bookable=cat == "IT hardware" and k % 10 == 0,
            status="condemned" if k < 20 else rng.choice(["in_use"] * 8 + ["idle", "under_repair"]),  # noqa: PLR2004
        )
        db.add(a)
        assets.append(a)
    await db.flush()
    for a in assets[:200]:
        a.qr_code_url = f"/assets/scan/{asset_token(a.id)}"
    ctx.count("assets", len(assets))

    # two audit cycles (CSE department) — the second leaves two assets missing in both
    cse_assets = [a for a in assets if "CSE" in depts and a.department_id == depts["CSE"].id] or assets[:40]
    for cycle_no, ago in ((1, 200), (2, 15)):
        cid = uuid.uuid4()
        on = today - timedelta(days=ago)
        scanned = {}
        missing = [str(a.id) for a in cse_assets[:2]]
        for a in cse_assets:
            if str(a.id) in missing:
                db.add(
                    AssetAudit(
                        institution_id=inst.id,
                        asset_id=a.id,
                        audited_on=on,
                        found=False,
                        remarks=f"cycle:{cid} | missing",
                    )
                )
                continue
            cond = rng.choice(["good", "good", "fair", "poor"])
            db.add(
                AssetAudit(
                    institution_id=inst.id,
                    asset_id=a.id,
                    audited_on=on,
                    found=True,
                    condition=cond,
                    remarks=f"cycle:{cid}",
                    scanned_qr=True,
                )
            )
            scanned[str(a.id)] = cond
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="inventory_meta",
                key=f"audit_cycle:{cid}",
                value={
                    "name": f"CSE asset audit #{cycle_no}",
                    "scope": {
                        "department_id": str(depts["CSE"].id) if "CSE" in depts else None,
                        "location_room_id": None,
                        "category": None,
                    },
                    "started_on": on.isoformat(),
                    "completed_on": on.isoformat(),
                    "status": "completed",
                    "expected": [str(a.id) for a in cse_assets],
                    "scanned": scanned,
                    "missing": missing,
                    "flagged": missing if cycle_no == 2 else [],  # noqa: PLR2004
                },
                value_type="json",
            )
        )
    await db.flush()
    ctx.count("asset_audits", 2 * len(cse_assets))
