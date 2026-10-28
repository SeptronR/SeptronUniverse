"""``saas`` demo seeder (Prompts/38 §38.2) — ``seed_demo_institution.py --only saas``.

Runs on the platform session (cross-tenant) after ``base`` (the profile tenant, e.g. ``demo-uni``):

* platform users ``superadmin`` (when none exists), ``superadmin.2`` (four-eyes) and ``support.agent``
  (``support_agent`` role; on-call for the support desk);
* 6 institutions across types / plans / statuses — the profile tenant (university, ``university`` plan, active),
  a second university (monthly), ``demo-college`` (autonomous, ``professional``, admin ``inst.admin.c`` and two
  ``source='override'`` flags), a second autonomous college in ``grace`` with overdue invoices, an affiliated college
  on a ``trial`` ending in 5 days and a ``suspended`` standalone college;
* 12 months of invoices per tenant (saas_meta ledger, numbers from the platform sequence; the last ones overdue on the
  grace tenant) and 12 months of usage meters (+ cost / AI tokens extras);
* integration connections with health checks (an SMS provider failing on most tenants → outage on the health page),
  40 support tickets across statuses / priorities (some SLA-breached), 30 feedback entries, 5 platform
  announcements, 8 pending registrations, 20 demo requests, 12 impersonation logs and one platform alert (chain break).

Passwords go to ``LOCAL_TEST_CREDENTIALS.md`` (git-ignored) only. Idempotent: the bulk data is written once (marker
``platform_settings['seed:phase38']``); platform users / tenants are get-or-create.
"""

import random
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text

TENANTS: list[dict[str, Any]] = [
    # slug, name, type, plan, status, subscription status, cycle, admin username
    {
        "slug": "demo-uni-2",
        "name": "Septron State University",
        "type": "university",
        "plan": "university",
        "status": "active",
        "sub": "active",
        "cycle": "monthly",
        "admin": "inst.admin.u2",
    },
    {
        "slug": "demo-college",
        "name": "Septron Autonomous College",
        "type": "autonomous_college",
        "plan": "professional",
        "status": "active",
        "sub": "active",
        "cycle": "yearly",
        "admin": "inst.admin.c",
    },
    {
        "slug": "demo-college-2",
        "name": "Riverside Autonomous College",
        "type": "autonomous_college",
        "plan": "standard",
        "status": "active",
        "sub": "grace",
        "cycle": "monthly",
        "admin": "inst.admin.r",
    },
    {
        "slug": "demo-aff-trial",
        "name": "Hillview Affiliated College",
        "type": "affiliated_college",
        "plan": "standard",
        "status": "active",
        "sub": "trial",
        "cycle": "yearly",
        "admin": "inst.admin.h",
    },
    {
        "slug": "demo-suspended",
        "name": "Lakeside Standalone College",
        "type": "standalone_college",
        "plan": "starter",
        "status": "suspended",
        "sub": "expired",
        "cycle": "monthly",
        "admin": "inst.admin.l",
    },
]
TICKET_SUBJECTS = [
    ("login", "Students cannot sign in after password reset"),
    ("billing", "GST number missing on last invoice"),
    ("data", "Bulk student import rejects DOB column"),
    ("integration", "SMS delivery delayed by several hours"),
    ("exams", "Hall tickets show the wrong exam centre"),
    ("mobile", "App crashes on the attendance screen"),
    ("other", "Request for a custom report"),
    ("exams", "Revaluation fee not reflecting"),
    ("data", "Duplicate guardian records after import"),
    ("billing", "Request to move to the yearly cycle"),
]


def _pw() -> str:
    return secrets.token_urlsafe(12)


@seeder("saas", after=["base"])
async def seed_saas(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.security import hash_password
    from app.db.session import PlatformSessionLocal
    from app.models.platform import College, FeedbackEntry, Institution, InstitutionProfile, Role, User, UserRole
    from app.models.saas import (
        DemoRequest,
        ImpersonationLog,
        InstitutionSubscription,
        PendingRegistration,
        PlatformAnnouncement,
        SubscriptionPlan,
        SupportTicket,
        UsageMeter,
    )
    from app.services.feature_service import FeatureService
    from app.services.rbac_service import RbacService
    from app.services.saas.common import PlatformBase
    from app.services.saas.dashboard_service import PlatformDashboardService
    from app.services.saas.registration_service import SystemPlatformActor
    from app.services.saas.subscription_service import SubscriptionService, cache_subscription_state, fy_label

    rng = random.Random(38)
    today = datetime.now(UTC).date()
    now = datetime.now(UTC)
    async with PlatformSessionLocal() as db:
        base = PlatformBase(db, None)
        actor = SystemPlatformActor()
        plans = {p.code: p for p in (await db.execute(select(SubscriptionPlan))).scalars()}

        # ---- platform users -------------------------------------------------------------------------------------
        async def platform_user(username: str, name: str, super_admin: bool) -> User:
            u = (
                await db.execute(select(User).where(User.institution_id.is_(None), User.username == username))
            ).scalar_one_or_none()
            if u is None:
                pw = _pw()
                u = User(
                    institution_id=None,
                    username=username,
                    email=f"{username.replace('.', '_')}@platform.septronuniverse.in",
                    display_name=name,
                    user_type="staff",
                    password_hash=hash_password(pw),
                    is_verified=True,
                    is_super_admin=super_admin,
                    must_change_password=False,
                    locale="en-IN",
                    timezone="Asia/Kolkata",
                )
                db.add(u)
                await db.flush()
                ctx.count("platform_users")
                ctx.credentials.append(("super_admin" if super_admin else "support_agent", username, pw))
            return u

        has_super = (
            await db.execute(select(User.id).where(User.is_super_admin.is_(True), User.deleted_at.is_(None)))
        ).first()
        sa1 = (
            await platform_user("superadmin", "Platform Super Admin", True)
            if not has_super
            else (
                await db.execute(
                    select(User)
                    .where(User.is_super_admin.is_(True), User.deleted_at.is_(None))
                    .order_by(User.created_at)
                )
            )
            .scalars()
            .first()
        )
        await platform_user("superadmin.2", "Second Super Admin", True)
        agent = await platform_user("support.agent", "Support Agent", False)
        role = (
            await db.execute(select(Role).where(Role.institution_id.is_(None), Role.slug == "support_agent"))
        ).scalar_one()
        if not (
            await db.execute(select(UserRole.id).where(UserRole.user_id == agent.id, UserRole.role_id == role.id))
        ).first():
            db.add(
                UserRole(
                    institution_id=None, user_id=agent.id, role_id=role.id, scope_type="institution", scope_id=None
                )
            )
        await base.pput("support.oncall", [str(agent.id)])

        # ---- tenants ----------------------------------------------------------------------------------------------
        profile_inst = (
            await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))
        ).scalar_one()
        tenants: list[tuple[Institution, dict[str, Any]]] = [
            (profile_inst, {"plan": "university", "sub": "active", "cycle": "yearly", "status": "active"})
        ]
        for t in TENANTS:
            inst = (await db.execute(select(Institution).where(Institution.slug == t["slug"]))).scalar_one_or_none()
            if inst is None:
                inst = Institution(
                    name=t["name"],
                    slug=t["slug"],
                    institution_type=t["type"],
                    regulatory_pack="IN",
                    timezone="Asia/Kolkata",
                    locale="en-IN",
                    currency="INR",
                    status=t["status"],
                    gstin=f"29AAB{rng.randint(1000, 9999)}C1Z{rng.randint(1, 9)}",
                    parent_university_name="Septron Demo University" if t["type"] == "affiliated_college" else None,
                )
                db.add(inst)
                await db.flush()
                db.add(InstitutionProfile(institution_id=inst.id))
                if t["type"] != "university":
                    db.add(
                        College(
                            institution_id=inst.id,
                            code="MAIN",
                            name=t["name"],
                            slug=f"{t['slug']}-main",
                            college_type="main",
                            is_main=True,
                        )
                    )
                await RbacService(db).seed_institution_roles(inst.id)
                await db.flush()
                admin_role = (
                    await db.execute(
                        select(Role).where(Role.institution_id == inst.id, Role.slug == "institution_admin")
                    )
                ).scalar_one()
                pw = _pw()
                admin = User(
                    institution_id=inst.id,
                    username=t["admin"],
                    email=f"{t['admin']}@{t['slug']}.septronuniverse.in",
                    display_name=f"Admin ({t['name']})",
                    user_type="staff",
                    password_hash=hash_password(pw),
                    is_verified=True,
                    must_change_password=False,
                    locale="en-IN",
                    timezone="Asia/Kolkata",
                )
                db.add(admin)
                await db.flush()
                db.add(
                    UserRole(
                        institution_id=inst.id,
                        user_id=admin.id,
                        role_id=admin_role.id,
                        scope_type="institution",
                        scope_id=None,
                    )
                )
                ctx.credentials.append((f"institution_admin ({t['slug']})", t["admin"], pw))
                ctx.count("institutions")
            tenants.append((inst, t))

        # subscriptions (latest row per tenant) + plan defaults
        for inst, t in tenants:
            plan = plans[t["plan"]]
            sub = (
                (
                    await db.execute(
                        select(InstitutionSubscription)
                        .where(InstitutionSubscription.institution_id == inst.id)
                        .order_by(InstitutionSubscription.starts_on.desc())
                    )
                )
                .scalars()
                .first()
            )
            if sub is None or (inst.id != profile_inst.id and sub.plan_id != plan.id):
                cycle_days = 30 if t["cycle"] == "monthly" else 365
                starts = today - timedelta(days=330) if t["sub"] != "trial" else today - timedelta(days=25)
                if t["sub"] == "trial":
                    ends = today + timedelta(days=5)
                elif t["cycle"] == "monthly":
                    ends = today.replace(day=1) + timedelta(days=cycle_days)
                else:
                    ends = starts + timedelta(days=cycle_days)
                sub = InstitutionSubscription(
                    institution_id=inst.id,
                    plan_id=plan.id,
                    starts_on=starts,
                    ends_on=ends,
                    billing_cycle=t["cycle"],
                    status=t["sub"],
                    grace_until=today + timedelta(days=9) if t["sub"] == "grace" else None,
                    amount_paise=0
                    if t["sub"] == "trial"
                    else (plan.price_paise_monthly if t["cycle"] == "monthly" else plan.price_paise_yearly),
                )
                db.add(sub)
                await db.flush()
                ctx.count("institution_subscriptions")
            await FeatureService(db, actor).apply_plan_defaults(inst.id)
            await SubscriptionService(db, actor).apply_locked_settings(inst.id, plan)
            await cache_subscription_state(inst.id, sub.status)
        await db.commit()

        marker = await base.pget("seed:phase38")
        if marker:
            print("   saas: bulk data already seeded (seed:phase38)")  # noqa: T201
            return

        # two overrides on demo-college survive plan changes (Phase 38 verification step 5)
        college = next(i for i, t in tenants if t.get("slug") == "demo-college")
        from app.repositories.feature_flag_repository import FeatureFlagRepository

        flags = FeatureFlagRepository(db)
        for key, on in (("placement.core", True), ("hostel.core", False)):
            await flags.upsert(college.id, key, platform_enabled=on, source="override", set_by=sa1.id if sa1 else None)
            await flags.log_change(
                college.id,
                key,
                None,
                {"platform_enabled": on, "source": "override"},
                sa1.id if sa1 else None,
                "demo override",
            )

        # ---- invoices (12 months) + usage meters ------------------------------------------------------------------
        billing = await base.setting("billing")
        invoices = 0
        for inst, t in tenants:
            plan = plans[t["plan"]]
            if t["sub"] == "trial":
                continue
            monthly = int(plan.price_paise_monthly or 0)
            for back in range(11, -1, -1):
                month = (today.replace(day=1) - timedelta(days=back * 30)).replace(day=1)
                issued = month + timedelta(days=1)
                due = issued + timedelta(days=int(billing.get("due_days") or 15))
                if t["cycle"] == "yearly" and back not in (11,):
                    continue
                amount = monthly if t["cycle"] == "monthly" else int(plan.price_paise_yearly or 0)
                gst = round(amount * 0.18)
                seq = await base.next_sequence(f"inv:{fy_label(issued)}")
                number = f"{billing.get('invoice_prefix') or 'INV'}/{fy_label(issued)}/{seq}"
                overdue = t["sub"] in ("grace", "expired") and back <= 1 or (inst.id == profile_inst.id and back == 0)
                status = ("overdue" if due < today else "issued") if overdue else "paid"
                await base.tput(
                    inst.id,
                    f"invoice:{number}",
                    {
                        "number": number,
                        "institution_id": str(inst.id),
                        "institution_name": inst.name,
                        "institution_gstin": inst.gstin,
                        "subscription_id": None,
                        "period": f"{month:%Y-%m}",
                        "kind": "subscription",
                        "plan": plan.code,
                        "lines": [
                            {"description": f"{plan.name} — {t['cycle']} ({month:%b %Y})", "amount_paise": amount}
                        ],
                        "amount_paise": amount,
                        "gst_pct": 18,
                        "gst_paise": gst,
                        "total_paise": amount + gst,
                        "status": status,
                        "issued_on": str(issued),
                        "due_on": str(due),
                        "paid_on": str(issued + timedelta(days=rng.randint(1, 12))) if status == "paid" else None,
                        "payment_ref": f"pay_demo_{rng.randint(10**7, 10**8)}" if status == "paid" else None,
                        "pdf_key": None,
                        "dunning": [{"stage": "due", "at": str(due)}] if status == "overdue" else [],
                    },
                )
                invoices += 1
        ctx.count("invoices", invoices)

        meters = 0
        for idx, (inst, t) in enumerate(tenants):
            size = [4200, 9000, 2600, 1800, 900, 600][idx]
            for back in range(11, -1, -1):
                month = (today.replace(day=1) - timedelta(days=back * 30)).replace(day=1)
                growth = 1 + (11 - back) * 0.01
                values = {
                    "active_students": int(size * growth),
                    "active_staff": int(size * 0.08 * growth),
                    "storage_bytes": int(size * 1.8 * 1024**2 * growth),
                    "sms_sent": int(size * rng.uniform(0.8, 2.5)),
                    "whatsapp_sent": int(size * rng.uniform(0.2, 0.9)),
                    "emails_sent": int(size * rng.uniform(1, 4)),
                    "api_calls": int(size * rng.uniform(60, 140)),
                }
                row = (
                    await db.execute(
                        select(UsageMeter).where(UsageMeter.institution_id == inst.id, UsageMeter.period_month == month)
                    )
                ).scalar_one_or_none()
                if row is None:
                    db.add(UsageMeter(institution_id=inst.id, period_month=month, **values))
                    meters += 1
                rates = await base.setting("usage.rates")
                ai = int(size * rng.uniform(5, 40))
                cost = (
                    values["sms_sent"] * rates["sms_paise"]
                    + values["whatsapp_sent"] * rates["whatsapp_paise"]
                    + values["emails_sent"] * rates["email_paise"]
                    + round(ai / 1000 * rates["ai_token_paise_per_1k"])
                )
                plan = plans[t["plan"]]
                over = []
                if plan.sms_credits and values["sms_sent"] > plan.sms_credits * 0.8:
                    over.append(
                        {
                            "metric": "sms_sent",
                            "used": values["sms_sent"],
                            "limit": plan.sms_credits,
                            "pct": round(values["sms_sent"] * 100 / plan.sms_credits, 1),
                            "source": "plan",
                        }
                    )
                await base.tput(
                    inst.id,
                    f"usage:{month:%Y-%m}",
                    {"ai_tokens": ai, "cost_paise": cost, "overage": over, "alerted": []},
                )
        ctx.count("usage_meters", meters)

        # ---- integration connections + health (SMS provider failing on most tenants → outage) ----------------------
        conns = 0
        for idx, (inst, _) in enumerate(tenants):
            for capability, provider, failing in (
                ("sms", "msg91", idx in (1, 2, 3, 4)),
                ("email", "smtp", False),
                ("payment", "razorpay", idx == 5),
            ):
                exists = (
                    await db.execute(
                        text(
                            "SELECT id FROM integration_connections WHERE institution_id = :i AND capability = :c AND provider = :p"
                        ),
                        {"i": inst.id, "c": capability, "p": provider},
                    )
                ).first()
                if exists:
                    continue
                cid = uuid.uuid4()
                await db.execute(
                    text(
                        "INSERT INTO integration_connections (id, institution_id, capability, provider, label, is_sandbox, status, last_health_at, last_error) "
                        "VALUES (:id, :i, :c, :p, :l, TRUE, :s, :t, :e)"
                    ),
                    {
                        "id": cid,
                        "i": inst.id,
                        "c": capability,
                        "p": provider,
                        "l": "primary",
                        "s": "failed" if failing else "healthy",
                        "t": now - timedelta(minutes=7),
                        "e": "HTTP 503 from provider" if failing else None,
                    },
                )
                for k in range(6):
                    ok = not failing or k > 3
                    await db.execute(
                        text(
                            "INSERT INTO integration_health_checks (institution_id, connection_id, checked_at, ok, latency_ms, detail) VALUES (:i, :c, :t, :ok, :l, :d)"
                        ),
                        {
                            "i": inst.id,
                            "c": cid,
                            "t": now - timedelta(minutes=15 * k + 7),
                            "ok": ok and not (failing and k < 3),
                            "l": rng.randint(80, 900),
                            "d": None if ok else "HTTP 503",
                        },
                    )
                conns += 1
        ctx.count("integration_connections", conns)

        # ---- support tickets ------------------------------------------------------------------------------------------
        admins: dict[uuid.UUID, uuid.UUID] = {}
        for inst, _ in tenants:
            row = (
                await db.execute(
                    text(
                        "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id "
                        "WHERE u.institution_id = :i AND r.slug = 'institution_admin' ORDER BY u.created_at LIMIT 1"
                    ),
                    {"i": inst.id},
                )
            ).first()
            if row:
                admins[inst.id] = row[0]
        sla = await base.setting("support.sla_hours")
        statuses = ["open"] * 10 + ["in_progress"] * 9 + ["waiting"] * 6 + ["resolved"] * 7 + ["closed"] * 8
        priorities = ["urgent", "high", "normal", "normal", "low"]
        for n in range(40):
            inst, _ = tenants[n % len(tenants)]
            category, subject = TICKET_SUBJECTS[n % len(TICKET_SUBJECTS)]
            priority = priorities[n % len(priorities)]
            status = statuses[n]
            created = now - timedelta(hours=rng.randint(2, 24 * 40))
            due = created + timedelta(hours=int(sla[priority]))
            breached = status in ("open", "in_progress") and due < now
            raiser = admins.get(inst.id)
            thread = [
                {
                    "id": uuid.uuid4().hex[:12],
                    "by": str(raiser) if raiser else None,
                    "at": (created + timedelta(minutes=5)).isoformat(),
                    "text": "Details attached; please check urgently.",
                    "attachments": [],
                    "internal": False,
                    "side": "tenant",
                },
            ]
            if status != "open":
                thread.append(
                    {
                        "id": uuid.uuid4().hex[:12],
                        "by": str(agent.id),
                        "at": (created + timedelta(hours=2)).isoformat(),
                        "text": "Thanks — we are looking into it.",
                        "attachments": [],
                        "internal": False,
                        "side": "platform",
                    }
                )
                thread.append(
                    {
                        "id": uuid.uuid4().hex[:12],
                        "by": str(agent.id),
                        "at": (created + timedelta(hours=3)).isoformat(),
                        "text": "Internal: reproduced on staging; linked to the import validator.",
                        "attachments": [],
                        "internal": True,
                        "side": "platform",
                    }
                )
            year = created.year
            number = f"SPT/{year}/{await base.next_sequence(f'spt:{year}')}"
            db.add(
                SupportTicket(
                    institution_id=inst.id,
                    ticket_number=number,
                    raised_by=raiser,
                    subject=subject,
                    description=f"{subject}. Reported from the admin console.",
                    priority=priority,
                    module=category if category in ("exams", "billing") else None,
                    status=status,
                    assigned_to=agent.id if status != "open" or n % 3 == 0 else None,
                    messages={
                        "thread": thread,
                        "meta": {
                            "category": category,
                            "sla_due_at": due.isoformat(),
                            "breached": breached,
                            "csat": rng.randint(3, 5) if status == "closed" else None,
                        },
                    },
                    created_at=created,
                    resolved_at=created + timedelta(hours=rng.randint(4, 72))
                    if status in ("resolved", "closed")
                    else None,
                )
            )
        ctx.count("support_tickets", 40)

        # ---- feedback ---------------------------------------------------------------------------------------------------
        users = (
            await db.execute(
                text(
                    "SELECT id, institution_id FROM users WHERE institution_id IS NOT NULL AND deleted_at IS NULL ORDER BY created_at LIMIT 60"
                )
            )
        ).all()
        pages = [
            "/admin/fees/collect",
            "/student/results",
            "/admin/students",
            "/staff/attendance",
            "/admin/exams",
            "/student/fees",
        ]
        cats = ["bug", "idea", "question", "praise"]
        fstat = ["new"] * 12 + ["triaged"] * 8 + ["planned"] * 5 + ["done"] * 3 + ["declined"] * 2
        for n in range(30):
            uid, iid = users[n % len(users)]
            db.add(
                FeedbackEntry(
                    institution_id=iid,
                    user_id=uid,
                    page=pages[n % len(pages)],
                    category=cats[n % len(cats)],
                    rating=(n % 5) + 1,
                    message=[
                        "Export takes too long",
                        "Love the new dashboard",
                        "How do I change my term?",
                        "Button overlaps on mobile",
                        "Please add bulk edit",
                    ][n % 5],
                    client=["web", "mobile", "pwa"][n % 3],
                    status=fstat[n],
                    created_at=now - timedelta(days=rng.randint(0, 60)),
                )
            )
        ctx.count("feedback_entries", 30)

        # ---- announcements ----------------------------------------------------------------------------------------------
        for title, body_, aud, channels, kind, start, end in (
            (
                "Release 38: billing & support desk",
                "Invoices, usage and the support desk are now in the admin console.",
                {"type": "all", "values": []},
                ["banner", "inapp"],
                "release",
                now - timedelta(days=2),
                now + timedelta(days=12),
            ),
            (
                "University plan: affiliation webinar",
                "Join the affiliation-management webinar on Friday.",
                {"type": "plan", "values": ["university"]},
                ["banner", "email"],
                "info",
                now - timedelta(days=1),
                now + timedelta(days=5),
            ),
            (
                "Scheduled maintenance",
                "The platform is read-only on Sunday 02:00–03:00 IST.",
                {"type": "all", "values": []},
                ["banner"],
                "maintenance",
                now,
                now + timedelta(days=4),
            ),
            (
                "Autonomous colleges: exam module tips",
                "Five tips for running autonomous examinations.",
                {"type": "institution_type", "values": ["autonomous_college"]},
                ["banner", "inapp"],
                "info",
                now - timedelta(days=3),
                now + timedelta(days=10),
            ),
            (
                "Old notice (ended)",
                "This window already ended.",
                {"type": "all", "values": []},
                ["banner"],
                "info",
                now - timedelta(days=20),
                now - timedelta(days=10),
            ),
        ):
            db.add(
                PlatformAnnouncement(
                    title=title,
                    body=body_,
                    audience={**aud, "channels": channels, "kind": kind},
                    starts_at=start,
                    ends_at=end,
                    is_active=True,
                    created_by=sa1.id if sa1 else None,
                )
            )
        ctx.count("platform_announcements", 5)

        # ---- registrations / demo requests ---------------------------------------------------------------------------------
        regs = [
            ("pending", True),
            ("pending", False),
            ("verified", False),
            ("verified", True),
            ("paid", False),
            ("provisioned", True),
            ("failed", True),
            ("expired", False),
        ]
        for n, (status, trial) in enumerate(regs):
            r = PendingRegistration(
                institution_name=f"Prospect College {n + 1}",
                institution_type=["autonomous_college", "affiliated_college", "standalone_college", "university"][
                    n % 4
                ],
                slug=f"prospect-{n + 1}",
                admin_name=f"Prospect Admin {n + 1}",
                admin_email=f"admin{n + 1}@prospect{n + 1}.example.in",
                admin_phone=f"98450{n:05d}",
                plan_id=plans["standard"].id,
                status=status,
                payment_ref="pay_demo_reg" if status in ("paid", "provisioned") and not trial else None,
                created_at=now - timedelta(hours=8 * (n + 1) + (100 if status == "expired" else 0)),
            )
            db.add(r)
            await db.flush()
            meta: dict[str, Any] = {
                "trial": trial,
                "plan": "standard",
                "history": [{"at": now.isoformat(), "to": status}],
            }
            if status == "failed":
                meta["error"] = "Slug collides with a reserved custom domain"
            await base.pput(f"reg:{r.id}", meta)
        ctx.count("pending_registrations", len(regs))
        dstat = ["new"] * 8 + ["contacted"] * 6 + ["converted"] * 3 + ["dropped"] * 3
        for n in range(20):
            d = DemoRequest(
                name=f"Lead {n + 1}",
                institution_name=f"Lead Institution {n + 1}",
                email=f"lead{n + 1}@leads.example.in",
                phone=f"99000{n:05d}",
                institution_type=["university", "autonomous_college", "affiliated_college"][n % 3],
                message="Interested in exams and fees modules",
                status=dstat[n],
                created_at=now - timedelta(days=rng.randint(0, 45)),
            )
            db.add(d)
            await db.flush()
            if d.status != "new":
                await base.pput(
                    f"demo_req:{d.id}",
                    {
                        "owner": str(sa1.id) if sa1 else None,
                        "notes": [{"at": now.isoformat(), "status": d.status, "text": "Called; follow up next week"}],
                    },
                )
        ctx.count("demo_requests", 20)

        # ---- impersonation logs -------------------------------------------------------------------------------------------
        for n in range(12):
            inst, _ = tenants[n % len(tenants)]
            target = admins.get(inst.id)
            if target is None or sa1 is None:
                continue
            start = now - timedelta(days=n + 1, minutes=rng.randint(0, 300))
            db.add(
                ImpersonationLog(
                    institution_id=inst.id,
                    impersonator_id=(sa1.id if n % 3 else agent.id),
                    target_user_id=target,
                    reason=f"ticket SPT/{start.year}/{n + 1:04d}",
                    started_at=start,
                    ended_at=start + timedelta(minutes=rng.randint(3, 50)),
                )
            )
        ctx.count("impersonation_logs", 12)
        await db.flush()

        # ---- a platform alert (Phase 37 chain break) and the health rollup ---------------------------------------------
        await PlatformDashboardService(db, None).record_alert(
            "chain_broken",
            college.id,
            {
                "ok": False,
                "rows": 1200,
                "first_broken": "demo",
                "mismatches": ["digest " + str(today - timedelta(days=1))],
            },
        )
        from app.services.saas.health_service import HealthService

        await HealthService(db, None).rollup()
        await base.pput("seed:phase38", {"at": now.isoformat(), "tenants": len(tenants)})
        await db.commit()
