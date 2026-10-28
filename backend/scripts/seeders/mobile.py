"""``mobile`` demo seeder (Prompts/42 §42.2) — ``seed_demo_institution.py --only mobile``.

Mock FCM device tokens (``provider='fcm'``, ``mock-fcm-…``) for up to 300 users across roles, android / ios mixed,
with topics ``role:<slug>`` and ``institution:<id>``. Nothing else —
the app reads the data of earlier seeds. Idempotent via ``ON CONFLICT (provider, token)``.
"""

import json
import uuid

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text


@seeder("mobile", after=["base"])
async def seed_mobile(ctx: SeedContext) -> None:
    from app.db.session import bind_tenant, set_tenant
    from app.models.platform import Institution

    db = ctx.db
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    iid = inst.id
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    rows = (
        await db.execute(
            text(
                "SELECT DISTINCT ON (u.id) u.id, r.slug FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                "JOIN roles r ON r.id = ur.role_id WHERE u.institution_id = :i AND u.deleted_at IS NULL ORDER BY u.id LIMIT 300"
            ),
            {"i": iid},
        )
    ).all()
    made = 0
    for n, (uid, slug) in enumerate(rows):
        topics = [f"role:{slug}", f"institution:{iid}"]
        res = await db.execute(
            text(
                "INSERT INTO device_tokens (id, institution_id, user_id, provider, platform, token, topics, is_active, "
                "last_seen_at, created_at, updated_at) VALUES (:id, :i, :u, 'fcm', :p, :t, CAST(:tp AS jsonb), TRUE, "
                "NOW(), NOW(), NOW()) ON CONFLICT (provider, token) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "i": iid,
                "u": uid,
                "p": "ios" if n % 4 == 0 else "android",
                "t": f"mock-fcm-{uid.hex}",
                "tp": json.dumps(topics),
            },
        )
        made += res.rowcount or 0
    await db.commit()
    print(f"   mobile: {made} FCM device tokens ({len(rows)} users)")
