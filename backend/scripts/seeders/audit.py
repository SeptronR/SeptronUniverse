"""``audit`` demo seeder (Prompts/37 §37.2) — ``seed_demo_institution.py --only audit``.

Writes (rows go through the live ``audit_logs`` hash-chain trigger, oldest first, so the chain verifies):

* 50 000 audit rows across modules / users over the last 90 days — record ids of real students / staff where the
  module has them (department / college scoping), 200 ``view_pii`` reads (registrar on students), 30 impersonated
  writes (platform super admin), ``exams:decode`` rows for the seeded exam papers (one from outside the allow-list);
* login history: successes, failures, a lockout for the accountant from one IP, a 35-failure burst from one IP inside
  15 minutes (→ ``login_failures_per_ip`` anomaly), and 20 rows older than 365 days (retention preview);
* one custody gap (a bundle ``received`` without a dispatch) on the first seeded exam paper;
* 5 college-level setting overrides on the second college, a legal hold on the first batch, signed digests for the
  last 7 days, one anomaly scan and — in development — the corrupted dev copy of the chain (never the live chain).

Idempotent: the bulk rows are written once (marker ``audit_meta seed:phase37``); digests / scan re-run harmlessly.
"""

import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text

ROWS = 50_000
BATCH = 2_000
MODULES: list[tuple[str, tuple[str, ...], str | None, int]] = [
    # module, actions, record_type, weight
    ("students", ("create", "update", "view", "export"), "student", 14),
    ("fees", ("collect", "create", "update", "refund"), "fee_invoice", 12),
    ("attendance", ("mark", "update", "condone"), "class_session", 14),
    ("hr", ("update", "create", "view"), "staff", 8),
    ("exams", ("create", "update", "publish", "lock"), "exam_session", 6),
    ("results", ("compute", "verify", "approve", "publish"), "result_processing_run", 4),
    ("library", ("issue", "return", "create"), "book_issue", 8),
    ("hostel", ("allocate", "update"), "hostel_allocation", 4),
    ("reports", ("run", "download", "preview"), "report", 8),
    ("settings", ("update",), "institution_settings", 2),
    ("users", ("update", "session_revoke", "reset_password"), "user", 6),
    ("auth", ("login", "logout"), "user", 10),
    ("grievances", ("create", "update"), "grievance", 2),
    ("placement", ("create", "update"), "placement_drive", 2),
]


@seeder("audit", after=["reports", "post_result"])
async def seed_audit(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.db.session import bind_tenant, set_tenant
    from app.models.platform import Institution
    from app.schemas.audit import LegalHoldIn, LegalHoldScope
    from app.schemas.settings import SettingItem
    from app.services.audit.chain_service import ChainService
    from app.services.audit.retention_service import RetentionService
    from app.services.audit.security_service import SecurityService
    from app.services.auth_service import load_principal
    from app.services.settings_service import SettingsService

    db = ctx.db
    rng = random.Random(37)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    inst_id = inst.id
    bind_tenant(db, inst_id)
    await set_tenant(db, inst_id)

    async def holders(slug: str) -> list[uuid.UUID]:
        rows = await db.execute(
            text(
                "SELECT DISTINCT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id JOIN users u ON u.id = ur.user_id "
                "WHERE r.slug = :s AND (ur.institution_id = :i OR r.institution_id = :i) AND u.deleted_at IS NULL "
                "AND u.is_active ORDER BY ur.user_id"
            ),
            {"s": slug, "i": inst_id},
        )
        return [r[0] for r in rows.all()]

    async def principal_of(slug: str) -> Any:
        users = await holders(slug)
        if not users:
            return None
        p = await load_principal(db, users[0])
        bind_tenant(db, inst_id)
        await set_tenant(db, inst_id)
        return p

    admin = await principal_of("institution_admin")
    if admin is None:
        print("   audit: no institution_admin user — run the base seed first; skipped")
        return

    async def ids(sql: str, limit: int = 2000) -> list[uuid.UUID]:
        return [r[0] for r in (await db.execute(text(f"{sql} LIMIT {limit}"), {"i": inst_id})).all()]

    users = await ids("SELECT id FROM users WHERE institution_id = :i AND deleted_at IS NULL")
    students = await ids("SELECT id FROM students WHERE institution_id = :i")
    staff = await ids("SELECT id FROM staff WHERE institution_id = :i")
    registrar = (await holders("registrar") or [admin.id])[0]
    accountant = (await holders("accountant") or [admin.id])[0]
    supers = [r[0] for r in (await db.execute(text("SELECT id FROM users WHERE is_super_admin LIMIT 1"))).all()]
    if not users:
        print("   audit: no users — skipped")
        return

    marker = (
        await db.execute(
            text(
                "SELECT 1 FROM institution_settings WHERE institution_id = :i AND category = 'audit_meta' AND key = 'seed:phase37'"
            ),
            {"i": inst_id},
        )
    ).first()
    now = datetime.now(UTC)
    if marker is None:
        # ---- 50 000 audit rows, oldest first (the trigger links each row to the previous one) ----------------------
        weights = [w for *_, w in MODULES]
        stamps = sorted(now - timedelta(seconds=rng.randint(60, 90 * 86400)) for _ in range(ROWS))
        rows: list[dict[str, Any]] = []
        pii_at = set(rng.sample(range(ROWS), 200))
        imp_at = set(rng.sample(range(ROWS), 30))
        for n, at in enumerate(stamps):
            module, actions, rtype, _ = rng.choices(MODULES, weights)[0]
            action = rng.choice(actions)
            rid: uuid.UUID | None = uuid.uuid4()
            new: dict[str, Any] = {}
            uid = rng.choice(users)
            imp = None
            if rtype == "student" and students:
                rid = rng.choice(students)
            elif rtype == "staff" and staff:
                rid = rng.choice(staff)
            if module == "fees" and action == "collect":
                new = {"amount_paise": rng.randint(1000, 90000) * 100, "number": f"RCP/2026/{n:06d}"}
            elif module == "students" and action == "update":
                new = {"phone": f"98{rng.randint(10000000, 99999999)}"}
                rows_old = {"phone": f"97{rng.randint(10000000, 99999999)}"}
                new["_old"] = rows_old
            elif module == "reports":
                new = {
                    "key": rng.choice(["students.register", "fees.collection_register", "attendance.shortfall"]),
                    "params": {},
                }
            elif module == "settings":
                new = {"fees.late_fee_grace_days": rng.randint(0, 10)}
            if n in pii_at and students:
                module, action, rtype, rid, uid = "students", "view_pii", "student", rng.choice(students), registrar
                new = {"fields": ["aadhaar"] if rng.random() < 0.6 else ["aadhaar", "phone"]}
            if n in imp_at and supers:
                imp = supers[0]
                action = "update"
            old = new.pop("_old", None)
            rows.append(
                {
                    "i": inst_id,
                    "u": uid,
                    "imp": imp,
                    "m": module,
                    "a": action,
                    "rt": rtype,
                    "rid": rid,
                    "old": json.dumps(old) if old else None,
                    "new": json.dumps(new) if new else None,
                    "ip": f"10.{rng.randint(0, 3)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                    "at": at,
                }
            )
        for k in range(0, len(rows), BATCH):
            await db.execute(
                text(
                    "INSERT INTO audit_logs (institution_id, user_id, impersonator_id, module, action, record_type, record_id, "
                    "old_values, new_values, ip, user_agent, request_id, hash, occurred_at) VALUES (:i, :u, :imp, :m, :a, :rt, "
                    ":rid, CAST(:old AS jsonb), CAST(:new AS jsonb), CAST(:ip AS inet), 'demo-seed', NULL, 'seed', :at)"
                ),
                rows[k : k + BATCH],
            )
            await db.commit()
            bind_tenant(db, inst_id)
            await set_tenant(db, inst_id)
        ctx.count("audit_logs", len(rows))

        # ---- decode events for the seeded exam papers --------------------------------------------------------------
        papers = await ids("SELECT p.id FROM exam_papers p WHERE p.institution_id = :i ORDER BY p.created_at", 5)
        coe = (await holders("controller_of_examinations") or [admin.id])[0]
        allow = (
            await db.execute(
                text(
                    "SELECT host(cidr) FROM ip_allowlists WHERE institution_id = :i AND purpose = 'exam_decode' AND is_active LIMIT 1"
                ),
                {"i": inst_id},
            )
        ).first()
        for j, pid in enumerate(papers):
            ip = allow[0] if allow and j else "203.0.113.77"
            await db.execute(
                text(
                    "INSERT INTO audit_logs (institution_id, user_id, module, action, record_type, record_id, new_values, ip, hash, occurred_at) "
                    "VALUES (:i, :u, 'exams', 'exams:decode', 'exam_paper', :p, CAST(:n AS jsonb), CAST(:ip AS inet), 'seed', now())"
                ),
                {"i": inst_id, "u": coe, "p": pid, "n": json.dumps({"decoded": rng.randint(20, 60)}), "ip": ip},
            )
            ctx.count("decode_events")
        # ---- custody gap: a bundle received without being dispatched ------------------------------------------------
        bundle = (
            await db.execute(
                text(
                    "SELECT b.id FROM answer_script_bundles b WHERE b.institution_id = :i ORDER BY b.created_at LIMIT 1"
                ),
                {"i": inst_id},
            )
        ).first()
        if bundle and staff:
            await db.execute(
                text(
                    "INSERT INTO script_custody_log (institution_id, bundle_id, action, to_staff_id, at, location, remarks) VALUES (:i, :b, 'received', :s, now(), 'Valuation camp', 'dev-seeded missing handover')"
                ),
                {"i": inst_id, "b": bundle[0], "s": staff[0]},
            )
            ctx.count("custody_gaps")

        # ---- login history ----------------------------------------------------------------------------------------
        lh: list[dict[str, Any]] = []
        for _ in range(300):
            lh.append(
                {
                    "u": rng.choice(users),
                    "o": "success",
                    "ip": f"10.1.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                    "at": now - timedelta(minutes=rng.randint(10, 60 * 24 * 60)),
                }
            )
        for _ in range(60):
            lh.append(
                {
                    "u": rng.choice(users),
                    "o": "bad_password",
                    "ip": f"10.2.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
                    "at": now - timedelta(minutes=rng.randint(10, 60 * 24 * 60)),
                }
            )
        for k in range(5):
            lh.append(
                {
                    "u": accountant,
                    "o": "locked" if k == 4 else "bad_password",
                    "ip": "198.51.100.23",
                    "at": now - timedelta(hours=3, minutes=5 - k),
                }
            )
        for _ in range(20):
            lh.append(
                {
                    "u": rng.choice(users),
                    "o": "success",
                    "ip": "10.9.9.9",
                    "at": now - timedelta(days=400 + rng.randint(0, 60)),
                }
            )
        await db.execute(
            text(
                "INSERT INTO login_history (institution_id, user_id, identifier, outcome, ip, user_agent, occurred_at) VALUES "
                "(:i, :u, :ident, :o, CAST(:ip AS inet), 'demo-seed', :at)"
            ),
            [{**r, "i": inst_id, "ident": "demo" if r["u"] is None else None} for r in lh],
        )
        ctx.count("login_history", len(lh))
        await db.execute(
            text(
                "INSERT INTO institution_settings (institution_id, college_id, category, key, value, value_type) VALUES "
                "(:i, NULL, 'audit_meta', 'seed:phase37', CAST(:v AS jsonb), 'json')"
            ),
            {"i": inst_id, "v": json.dumps({"rows": ROWS, "at": now.isoformat()})},
        )
        await db.commit()
        bind_tenant(db, inst_id)
        await set_tenant(db, inst_id)

    # ---- 5 college-level overrides on the second college --------------------------------------------------------
    colleges = await ids("SELECT id FROM colleges WHERE institution_id = :i ORDER BY code", 5)
    if len(colleges) >= 2:
        items = [
            SettingItem(category="fees", key="late_fee_grace_days", value=5, college_id=colleges[1]),
            SettingItem(category="attendance", key="qr_ttl_seconds", value=180, college_id=colleges[1]),
            SettingItem(category="academics", key="attendance_min_pct_default", value=70, college_id=colleges[1]),
            SettingItem(category="timetable", key="mark_missed_sessions", value=False, college_id=colleges[1]),
            SettingItem(category="registration", key="default_max_seats", value=90, college_id=colleges[1]),
        ]
        await SettingsService(db, admin).bulk_update(items, None, reason="demo seed (Phase 37)")
        ctx.count("college_overrides", len(items))
        await db.commit()
        bind_tenant(db, inst_id)
        await set_tenant(db, inst_id)

    # ---- legal hold on the first batch ---------------------------------------------------------------------------
    retention = RetentionService(db, admin, institution_id=inst_id)
    if not await retention.legal_holds(active_only=True):
        batch = (
            await db.execute(
                text("SELECT id, code FROM batches WHERE institution_id = :i ORDER BY code LIMIT 1"), {"i": inst_id}
            )
        ).first()
        if batch:
            await retention.add_hold(
                LegalHoldIn(
                    data_class="message_logs",
                    scope=LegalHoldScope(batch_id=batch[0]),
                    reason=f"Pending litigation — batch {batch[1]}",
                )
            )
            ctx.count("legal_holds")
    await db.commit()
    bind_tenant(db, inst_id)
    await set_tenant(db, inst_id)

    # ---- digests for the last 7 days, anomaly scan, dev corrupted copy ---------------------------------------------
    chain = ChainService(db, admin, institution_id=inst_id)
    today = await chain.today()
    for k in range(1, 8):
        await chain.sign_day(today - timedelta(days=k))
        ctx.count("chain_digests")
    await db.commit()
    bind_tenant(db, inst_id)
    await set_tenant(db, inst_id)
    # the 35-failure burst from one IP sits next to the scan so it falls inside the 15-minute window
    recent = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM login_history WHERE institution_id = :i AND ip = '192.0.2.150' AND occurred_at > now() - interval '15 minutes'"
            ),
            {"i": inst_id},
        )
    ).scalar_one()
    if recent < 30:
        await db.execute(
            text(
                "INSERT INTO login_history (institution_id, identifier, outcome, ip, user_agent, occurred_at) "
                "SELECT :i, 'demo', 'bad_password', '192.0.2.150', 'demo-seed', now() - make_interval(secs => g * 15) "
                "FROM generate_series(1, 35) g"
            ),
            {"i": inst_id},
        )
        ctx.count("login_history", 35)
    ctx.count("anomalies", await SecurityService(db, admin, institution_id=inst_id).scan())
    await db.commit()
    bind_tenant(db, inst_id)
    await set_tenant(db, inst_id)
    from app.core.config import settings as app_settings

    if app_settings.APP_ENV == "development":
        out = await chain.dev_corrupt_copy()
        print(
            f"   audit: dev corrupted copy verified ok={out.ok} first_broken={out.first_broken.id if out.first_broken else None}"
        )
        await db.commit()
