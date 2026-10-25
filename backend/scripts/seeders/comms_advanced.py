"""``comms_advanced`` demo seeder (Prompts/24 §24.2) — ``seed_demo_institution.py --only comms_advanced``.

Enables the Phase 24 features, saves 3 segments (final-year students, students with dues, low-attendance guardians),
creates 6 campaigns across statuses (draft, pending approval, scheduled, sent with ~40 delivery logs, failed, one past
emergency with an all-clear) and the default bot flows for the tenant. Idempotent: skipped when campaigns exist.
"""

import random
from datetime import timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("comms_advanced", after=["base", "fees", "attendance"])
async def seed_comms_advanced(ctx: SeedContext) -> None:  # noqa: C901, PLR0915 - one linear demo script
    import json
    import uuid

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.db.session import bind_tenant, set_tenant
    from app.enums.comms_advanced import BOT_FLOWS
    from app.models.comms_advanced import BulkCampaign
    from app.models.communication import MessageLog
    from app.models.platform import Institution, InstitutionSetting, User
    from app.services.comms_advanced.common import now_utc
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(24)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(BulkCampaign).where(BulkCampaign.institution_id == inst.id))
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "comms.bulk_campaigns",
        "comms.scheduled_sends",
        "comms.emergency_broadcast",
        "comms.whatsapp_bot",
        "comms.ai_assistant",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 24)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   comms_advanced: {key} not enabled ({exc})")

    registrar = (await db.execute(select(User).where(User.username == "registrar"))).scalar_one_or_none()
    actor = registrar.id if registrar else None

    def setting(category: str, key: str, value: object) -> None:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category=category,
                key=key,
                value=value,
                value_type="json",
                updated_by=actor,
            )
        )

    stamp = now_utc().isoformat()
    segments = [
        {
            "id": str(uuid.uuid4()),
            "name": "Final-year students",
            "rules": {"person_types": ["student"], "all": [{"field": "term_number", "op": "gte", "value": 7}]},
            "shared": True,
            "owner_user_id": str(actor) if actor else None,
            "updated_at": stamp,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Students with overdue dues",
            "rules": {"person_types": ["student"], "dues": {"min_paise": 100, "overdue_only": True}},
            "shared": True,
            "owner_user_id": str(actor) if actor else None,
            "updated_at": stamp,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Guardians — attendance below 75%",
            "rules": {"person_types": ["guardian"], "attendance": {"below_pct": 75}},
            "shared": False,
            "owner_user_id": str(actor) if actor else None,
            "updated_at": stamp,
        },
    ]
    setting("comms", "segments", segments)
    setting("comms", "bot_flows", {"flows": BOT_FLOWS, "greeting": "Hello! Reply with a number:"})
    ctx.count("saved_segments", len(segments))

    now = now_utc()
    plan = [
        ("Fee reminder — semester 2", ["sms", "whatsapp"], "draft", None, False),
        ("Convocation invitation", ["email", "push", "in_app"], "pending_approval", None, False),
        ("Exam timetable published", ["push", "in_app"], "scheduled", now + timedelta(days=2), False),
        ("Holiday notice — Diwali", ["sms", "email", "in_app"], "sent", now - timedelta(days=6), False),
        ("Hostel maintenance window", ["sms"], "failed", now - timedelta(days=3), False),
        ("Campus security alert (drill)", ["sms", "push", "in_app"], "sent", now - timedelta(days=10), True),
    ]
    users = list(
        (
            await db.execute(select(User).where(User.institution_id == inst.id).order_by(User.username).limit(40))
        ).scalars()
    )
    for name, channels, status, at, emergency in plan:
        c = BulkCampaign(
            institution_id=inst.id,
            name=name,
            channels=channels,
            audience_rules=segments[0]["rules"] if not emergency else {"person_types": ["student", "staff"]},
            body_override=json.dumps(
                {"sms": f"{name}. Details on the portal.", "in_app": f"{name}. Details on the portal."}
            ),
            scheduled_at=at,
            status=status,
            is_emergency=emergency,
            created_by=actor,
        )
        db.add(c)
        await db.flush()
        ctx.count("bulk_campaigns")
        if status not in ("sent", "failed"):
            continue
        sent = failed = 0
        for u in users:
            for ch in channels:
                ok = status == "sent" and rng.random() > 0.08  # noqa: PLR2004
                db.add(
                    MessageLog(
                        institution_id=inst.id,
                        user_id=u.id,
                        recipient=(u.email if ch == "email" else getattr(u, "phone", None)) or str(u.id),
                        channel=ch,
                        event_type="campaign.message",
                        campaign_id=c.id,
                        body_preview=name[:255],
                        provider="console",
                        status="delivered" if ok else "failed",
                        error=None if ok else "demo: provider rejected",
                        cost_paise={"sms": 18, "whatsapp": 45, "email": 2}.get(ch, 0),
                        sent_at=at,
                        delivered_at=at + timedelta(minutes=1) if ok and at else None,
                    )
                )
                sent += ok
                failed += not ok
        c.total_recipients, c.sent_count, c.failed_count = len(users), sent, failed
        ctx.count("message_logs", sent + failed)
        if emergency:
            setting(
                "comms_meta",
                f"emergency:{c.id}",
                {"alert_type": "security", "raised_by": str(actor) if actor else None, "all_clear_at": stamp},
            )
    await db.flush()
