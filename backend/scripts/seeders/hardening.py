"""``hardening`` demo seeder (Prompts/43 §43.2) — ``seed_demo_institution.py --only hardening``.

For the profile tenant: consent decisions for every active user (mandatory purposes granted; marketing / photo /
placement mixed deterministically), 40 students made minors (date of birth 17 years ago) with guardian-recorded
consents where a guardian account exists, 25 data-subject requests across types and states (timelines in
``privacy_meta``), and an initial posture check. ``privacy.off`` / ``security.off`` come from the base seeder.
Idempotent via the marker ``privacy_meta seed:phase43``. The large load fixtures are ``--load`` only (not created here).
"""

import json
import random
import uuid
from datetime import UTC, date, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text

OPTIONAL = ("communication_marketing", "photo_media", "third_party_placement", "location", "guardian_access")
MANDATORY = ("academic", "communication_transactional")
STATES = [
    "received",
    "received",
    "identity_pending",
    "in_progress",
    "in_progress",
    "extended",
    "completed",
    "completed",
    "rejected",
]
TYPES = ["access", "export", "correction", "erasure"]


@seeder("hardening", after=["base", "students"])
async def seed_hardening(ctx: SeedContext) -> None:  # noqa: C901, PLR0915 - one linear demo script
    from app.core.privacy_registry import PURPOSE_VERSION
    from app.db.session import bind_tenant, set_tenant
    from app.models.platform import Institution

    db = ctx.db
    rng = random.Random(43)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    iid = inst.id
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    done = (
        await db.execute(
            text(
                "SELECT 1 FROM institution_settings WHERE institution_id = :i AND category = 'privacy_meta' AND key = 'seed:phase43'"
            ),
            {"i": iid},
        )
    ).first()
    if done:
        print("   hardening: already seeded (marker privacy_meta/seed:phase43)")
        return

    async def meta(key: str, value: object) -> None:
        await db.execute(
            text(
                "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, is_public, "
                "created_at, updated_at) VALUES (:id, :i, NULL, 'privacy_meta', :k, CAST(:v AS jsonb), 'json', FALSE, NOW(), NOW()) "
                "ON CONFLICT (institution_id, college_id, category, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"id": uuid.uuid4(), "i": iid, "k": key, "v": json.dumps(value, default=str)},
        )

    users = [
        r[0]
        for r in (
            await db.execute(
                text(
                    "SELECT id FROM users WHERE institution_id = :i AND deleted_at IS NULL AND is_active ORDER BY id LIMIT 2000"
                ),
                {"i": iid},
            )
        ).all()
    ]
    consent_rows = 0
    for n, uid in enumerate(users):
        grants = dict.fromkeys(MANDATORY, True) | {
            p: rng.random() < (0.35 if p == "communication_marketing" else 0.7) for p in OPTIONAL
        }
        for purpose, granted in grants.items():
            await db.execute(
                text(
                    "INSERT INTO consent_records (id, institution_id, user_id, purpose, granted, text_version, granted_by_user_id, recorded_at) "
                    "VALUES (:id, :i, :u, :p, :g, :v, :u, NOW() - make_interval(days => :d))"
                ),
                {"id": uuid.uuid4(), "i": iid, "u": uid, "p": purpose, "g": granted, "v": PURPOSE_VERSION, "d": n % 60},
            )
            consent_rows += 1
        if n % 3:
            await db.execute(
                text(
                    'UPDATE users SET preferences = coalesce(preferences, \'{}\'::jsonb) || \'{"privacy": {"notice_version": "1.0"}}\'::jsonb WHERE id = :u'
                ),
                {"u": uid},
            )
    ctx.count("consent_records", consent_rows)

    # minors: 40 students born 17 years ago; guardians (with accounts) record the optional consents
    minors = (
        await db.execute(
            text(
                "SELECT s.id, s.user_id FROM students s WHERE s.institution_id = :i AND s.deleted_at IS NULL AND s.user_id IS NOT NULL "
                "ORDER BY EXISTS (SELECT 1 FROM student_guardians g WHERE g.student_id = s.id AND g.user_id IS NOT NULL) DESC, s.id DESC "
                "LIMIT 40"
            ),
            {"i": iid},
        )
    ).all()
    dob = date.today().replace(year=date.today().year - 17) - timedelta(days=30)
    guardian_consents = 0
    for sid, suid in minors:
        await db.execute(text("UPDATE students SET dob = :d WHERE id = :s"), {"d": dob, "s": sid})
        g = (
            await db.execute(
                text("SELECT user_id FROM student_guardians WHERE student_id = :s AND user_id IS NOT NULL LIMIT 1"),
                {"s": sid},
            )
        ).scalar_one_or_none()
        if g:
            for purpose in ("photo_media", "guardian_access"):
                await db.execute(
                    text(
                        "INSERT INTO consent_records (id, institution_id, user_id, purpose, granted, text_version, granted_by_user_id, recorded_at) "
                        "VALUES (:id, :i, :u, :p, TRUE, :v, :g, NOW())"
                    ),
                    {"id": uuid.uuid4(), "i": iid, "u": suid, "p": purpose, "v": PURPOSE_VERSION, "g": g},
                )
                guardian_consents += 1
    ctx.count("minor_students", len(minors))
    ctx.count("guardian_consents", guardian_consents)

    # 25 data-subject requests
    requesters = users[:: max(1, len(users) // 25)][:25]
    now = datetime.now(UTC)
    for n, uid in enumerate(requesters):
        status = STATES[n % len(STATES)]
        typ = TYPES[n % len(TYPES)]
        created = now - timedelta(days=rng.randint(1, 40))
        due = created + timedelta(days=30 + (30 if status == "extended" else 0))
        closed = created + timedelta(days=rng.randint(3, 25)) if status in ("completed", "rejected") else None
        rid = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO data_subject_requests (id, institution_id, user_id, request_type, details, status, due_at, created_at, closed_at) "
                "VALUES (:id, :i, :u, :t, :d, :s, :due, :c, :cl)"
            ),
            {
                "id": rid,
                "i": iid,
                "u": uid,
                "t": typ,
                "d": f"Demo {typ} request",
                "s": status,
                "due": due,
                "c": created,
                "cl": closed,
            },
        )
        timeline = [{"at": created.isoformat(), "event": "received"}]
        verified = status not in ("received", "identity_pending")
        if verified:
            timeline.append(
                {"at": (created + timedelta(days=1)).isoformat(), "event": "identity_verified", "method": "otp"}
            )
        if status in ("in_progress", "extended", "completed"):
            timeline.append({"at": (created + timedelta(days=2)).isoformat(), "event": "started"})
        if status == "extended":
            timeline.append(
                {
                    "at": (created + timedelta(days=20)).isoformat(),
                    "event": "extended",
                    "reason": "Records held at an affiliated college",
                }
            )
        if status in ("completed", "rejected"):
            timeline.append(
                {
                    "at": closed.isoformat() if closed else None,
                    "event": status,
                    **({"reason": "Outstanding fee dues"} if status == "rejected" else {}),
                }
            )
        work = []
        if typ == "correction" and status != "received":
            work = [
                {
                    "n": 1,
                    "table": "students",
                    "field": "phone",
                    "new_value": "+91 90000 00000",
                    "owner_role": "registrar",
                    "permission": "students:update",
                    "status": "done" if status == "completed" else "open",
                }
            ]
        await meta(
            f"dsr:{rid}",
            {
                "timeline": timeline,
                "identity_verified": verified,
                "extensions": 1 if status == "extended" else 0,
                "work_items": work,
                "filed_by": None,
            },
        )
    ctx.count("data_subject_requests", len(requesters))
    await meta("seed:phase43", True)
    await db.commit()
    print(
        f"   hardening: {consent_rows} consents, {len(minors)} minors ({guardian_consents} guardian consents), {len(requesters)} DSRs"
    )
