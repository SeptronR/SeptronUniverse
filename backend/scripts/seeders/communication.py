"""``communication`` demo seeder (Prompts/04 §04.2) — ``seed_demo_institution.py --type university --only communication``.

On top of ``institution`` (which also copies the 18 workflow templates through ``seed_institution_defaults``):
a registered DLT template (``1107000000000000001``) mapped by an institution override of ``fees.payment_received``,
an approved WhatsApp template, and a pinned welcome announcement published to the whole institution.
Idempotent.
"""

from datetime import UTC, datetime

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select

from app.models.communication import Announcement, DltTemplate, NotificationTemplate, WhatsappTemplate
from app.models.platform import Institution, User

DLT_ID = "1107000000000000001"


@seeder("communication", after=["institution"])
async def seed_communication(ctx: SeedContext) -> None:
    from app.db.session import bind_tenant, set_tenant
    from app.services.institution_defaults import seed_workflow_definitions

    inst = (await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)
    conn = await ctx.db.connection()
    created = await conn.run_sync(lambda c: seed_workflow_definitions(c, inst.id))
    if created:
        ctx.count("workflow_definitions", created)
    await ctx.get_or_create(
        DltTemplate,
        {
            "sender_id": "SEPTRN",
            "entity_id": "1101000000000000001",
            "template_text": "We received {#var#} (receipt {#var#}). Thank you. - Septron",
            "category": "transactional",
            "status": "approved",
        },
        institution_id=inst.id,
        template_id=DLT_ID,
    )
    await ctx.get_or_create(
        NotificationTemplate,
        {
            "name": "Payment received (DLT)",
            "channels": ["in_app", "sms", "email"],
            "subject_template": "Receipt {{ receipt_no }}",
            "body_template": "We received {{ amount }} (receipt {{ receipt_no }}). Thank you. - Septron",
            "variables": ["amount", "receipt_no"],
            "is_active": True,
            "dlt_template_id": DLT_ID,
        },
        institution_id=inst.id,
        event_trigger="fees.payment_received",
        language="en",
        version=2,
    )
    await ctx.get_or_create(
        WhatsappTemplate,
        {
            "category": "utility",
            "body": "Hello {{1}}, results of {{2}} are published.",
            "status": "approved",
            "meta_template_id": "mock-results_published",
        },
        institution_id=inst.id,
        name="results_published",
        language="en",
    )
    admin = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "inst.admin"))
    ).scalar_one_or_none()
    await ctx.get_or_create(
        Announcement,
        {
            "body": "Welcome to the new academic year. Please keep your profile and notification preferences up to date.",
            "category": "general",
            "audience_rules": {},
            "publish_at": datetime.now(UTC),
            "is_pinned": True,
            "created_by": admin.id if admin else None,
        },
        institution_id=inst.id,
        title="Welcome to SeptronUniverse",
    )
    await ctx.db.flush()
