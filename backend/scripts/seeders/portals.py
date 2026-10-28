"""``portals`` demo seeder (Prompts/39 §39.2) — ``seed_demo_institution.py --only portals``.

Writes, for the profile tenant:

* web-push subscriptions (``device_tokens`` provider ``webpush``, mock endpoints ``https://mock.push/…``) for 200
  students, 50 parents and 40 faculty, with persona / role / college topics; two endpoints are ``…/gone`` so
  ``push.prune_expired`` has something to prune;
* 5 000 notifications across the notification-centre categories with deep-link routes (≈ 55 % read);
* preferences for 300 users (some quiet hours 22:00–07:00, daily / weekly digests, push off for events);
* tour completion / dismissal states for 150 users (``users.preferences['tours']``);
* 60 feedback entries from portal pages (page + persona in the audit row);
* announcement acknowledgements at ≈ 70 % for the requires-ack announcements (one is created when none exists).

Idempotent: the marker ``institution_settings`` (``portals_meta`` / ``seed:phase39``) skips the bulk rows on re-runs.
"""

import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text

CATEGORY_ROUTES: dict[str, tuple[str, list[str]]] = {
    "academics": ("/student/timetable", ["Timetable updated", "New study material", "Class rescheduled"]),
    "attendance": ("/student/attendance", ["Attendance below 75 %", "On-duty approved"]),
    "exams": ("/student/exams", ["Hall ticket ready", "Exam registration open", "Seating published"]),
    "fees": ("/student/fees", ["Invoice raised", "Payment received", "Fee due in 3 days"]),
    "hostel": ("/student/hostel", ["Out-pass approved", "Mess menu updated"]),
    "library": ("/student/library", ["Book due tomorrow", "Reservation available"]),
    "placement": ("/student/placement", ["New drive open", "Shortlisted for round 2"]),
    "approvals": ("/faculty/approvals", ["Approval pending", "Leave request awaiting you"]),
    "mentoring": ("/student/mentor", ["Mentor meeting booked", "Mentor note added"]),
    "events": ("/student/calendar", ["Event tomorrow", "Registration confirmed"]),
    "announcements": ("/student/notifications", ["New notice from the registrar", "Holiday notice"]),
    "security": ("/student/profile", ["New sign-in from Chrome", "Password changed"]),
    "system": ("/student", ["Welcome to your portal", "Push notifications are on"]),
}


@seeder("portals", after=["students", "hr", "student_support"])
async def seed_portals(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.db.session import bind_tenant, set_tenant
    from app.models.platform import Institution

    db = ctx.db
    rng = random.Random(39)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    inst_id = inst.id
    bind_tenant(db, inst_id)
    await set_tenant(db, inst_id)
    marker = (
        await db.execute(
            text(
                "SELECT 1 FROM institution_settings WHERE institution_id = :i AND category = 'portals_meta' "
                "AND key = 'seed:phase39'"
            ),
            {"i": inst_id},
        )
    ).first()
    if marker:
        print("   portals: already seeded (marker portals_meta/seed:phase39)")
        return

    async def users_with(slugs: tuple[str, ...], limit: int) -> list[tuple[uuid.UUID, str]]:
        rows = await db.execute(
            text(
                "SELECT DISTINCT ON (u.id) u.id, r.slug FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                "JOIN roles r ON r.id = ur.role_id WHERE u.institution_id = :i AND r.slug = ANY(:s) "
                "AND u.deleted_at IS NULL ORDER BY u.id LIMIT :n"
            ),
            {"i": inst_id, "s": list(slugs), "n": limit},
        )
        return [(r[0], r[1]) for r in rows.all()]

    students = await users_with(("student", "learner"), 200)
    parents = await users_with(("parent",), 50)
    faculty = await users_with(("faculty", "guest_faculty"), 40)
    persona = {
        "student": "student",
        "learner": "student",
        "parent": "parent",
        "faculty": "faculty",
        "guest_faculty": "faculty",
    }

    # ---- web push subscriptions ---------------------------------------------------------------------------------
    subs = 0
    for n, (uid, slug) in enumerate([*students, *parents, *faculty]):
        gone = n in (3, 7)
        token = json.dumps(
            {
                "endpoint": f"https://mock.push/{'gone/' if gone else ''}{uid}",
                "keys": {"p256dh": "BMockKey" + uid.hex[:24], "auth": uid.hex[:16]},
            },
            sort_keys=True,
        )
        res = await db.execute(
            text(
                "INSERT INTO device_tokens (id, institution_id, user_id, provider, platform, token, topics, is_active, "
                "last_seen_at, created_at, updated_at) VALUES (:id, :i, :u, 'webpush', 'web', :t, CAST(:tp AS jsonb), TRUE, "
                "NOW(), NOW(), NOW()) ON CONFLICT (provider, token) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "i": inst_id,
                "u": uid,
                "t": token,
                "tp": json.dumps([f"role:{slug}", f"persona:{persona[slug]}"]),
            },
        )
        subs += res.rowcount or 0
    ctx.count("webpush_subscriptions", subs)

    # ---- notifications ------------------------------------------------------------------------------------------
    everyone = [u for u, _ in [*students, *parents, *faculty]]
    if everyone:
        cats = list(CATEGORY_ROUTES)
        now = datetime.now(UTC)
        batch: list[dict[str, Any]] = []
        for _ in range(5000):
            cat = rng.choice(cats)
            route, titles = CATEGORY_ROUTES[cat]
            read = rng.random() < 0.55
            at = now - timedelta(minutes=rng.randint(5, 60 * 24 * 60))
            batch.append(
                {
                    "id": uuid.uuid4(),
                    "i": inst_id,
                    "u": rng.choice(everyone),
                    "t": rng.choice(titles),
                    "b": f"Demo {cat} notification.",
                    "c": cat,
                    "e": f"demo.{cat}",
                    "l": json.dumps({"route": route}),
                    "r": read,
                    "ra": at + timedelta(hours=2) if read else None,
                    "at": at,
                }
            )
        await db.execute(
            text(
                "INSERT INTO notifications (id, institution_id, user_id, title, body, category, event_type, link, is_read, "
                "read_at, created_at) VALUES (:id, :i, :u, :t, :b, :c, :e, CAST(:l AS jsonb), :r, :ra, :at)"
            ),
            batch,
        )
        ctx.count("notifications", len(batch))

    # ---- preferences (300 users) ---------------------------------------------------------------------------------
    pref_users = everyone[:300]
    for n, uid in enumerate(pref_users):
        quiet = {"from": "22:00", "to": "07:00"} if n % 3 == 0 else None
        digest = "daily" if n % 7 == 0 else ("weekly" if n % 11 == 0 else "none")
        general: dict[str, Any] = {"digest": digest}
        if quiet:
            general["quiet_hours"] = quiet
        tours = (
            {"completed": {"student.first_login": 1}, "dismissed": []}
            if n % 2 == 0
            else {"completed": {}, "dismissed": ["student.first_login"]}
        )
        await db.execute(
            text(
                "UPDATE users SET preferences = coalesce(preferences, '{}'::jsonb) || CAST(:p AS jsonb) WHERE id = :u"
            ),
            {"p": json.dumps({"notifications": general, **({"tours": tours} if n < 150 else {})}), "u": uid},
        )
        await db.execute(
            text(
                "INSERT INTO notification_preferences (id, institution_id, user_id, category, channels, quiet_hours, digest, "
                "updated_at) VALUES (:id, :i, :u, 'events', CAST(:ch AS jsonb), CAST(:q AS jsonb), :d, NOW()) "
                "ON CONFLICT (user_id, category) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "i": inst_id,
                "u": uid,
                "ch": json.dumps(["in_app", "email"]),
                "q": json.dumps(quiet) if quiet else None,
                "d": digest,
            },
        )
    ctx.count("preference_users", len(pref_users))
    ctx.count("tour_states", min(150, len(pref_users)))

    # ---- feedback from portal pages ----------------------------------------------------------------------------
    pages = [
        "/student",
        "/student/fees",
        "/student/exams",
        "/student/requests",
        "/parent",
        "/parent/fees",
        "/faculty/attendance",
        "/faculty/approvals",
    ]
    fb = 0
    for n in range(60 if everyone else 0):
        page = rng.choice(pages)
        await db.execute(
            text(
                "INSERT INTO feedback_entries (id, institution_id, user_id, page, category, rating, message, client, status, "
                "created_at) VALUES (:id, :i, :u, :p, :c, :r, :m, 'pwa', :s, NOW() - make_interval(days => :d))"
            ),
            {
                "id": uuid.uuid4(),
                "i": inst_id,
                "u": rng.choice(everyone),
                "p": page,
                "c": rng.choice(["bug", "idea", "question", "praise"]),
                "r": rng.randint(1, 5),
                "m": f"Portal feedback #{n + 1} on {page}",
                "s": rng.choice(["new", "new", "triaged", "resolved"]),
                "d": rng.randint(0, 40),
            },
        )
        fb += 1
    ctx.count("feedback_entries", fb)

    # ---- announcement acknowledgements (~70 %) ------------------------------------------------------------------
    ann = (
        await db.execute(
            text(
                "SELECT id FROM announcements WHERE institution_id = :i AND requires_ack AND deleted_at IS NULL LIMIT 3"
            ),
            {"i": inst_id},
        )
    ).all()
    ann_ids = [a[0] for a in ann]
    if not ann_ids:
        aid = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO announcements (id, institution_id, title, body, category, audience_rules, publish_at, "
                "requires_ack, is_pinned, is_active, created_at, updated_at) VALUES (:id, :i, 'Anti-ragging undertaking', "
                "'Please read and acknowledge the anti-ragging policy.', 'academics', CAST(:a AS jsonb), NOW(), TRUE, TRUE, "
                "TRUE, NOW(), NOW())"
            ),
            {"id": aid, "i": inst_id, "a": json.dumps({"roles": ["student", "parent"]})},
        )
        ann_ids = [aid]
        ctx.count("announcements")
    acks = 0
    for aid in ann_ids:
        for uid, _ in [*students, *parents]:
            if rng.random() > 0.7:
                continue
            res = await db.execute(
                text(
                    "INSERT INTO announcement_acknowledgements (id, institution_id, announcement_id, user_id, read_at, "
                    "acknowledged_at) VALUES (:id, :i, :a, :u, NOW(), NOW()) ON CONFLICT (announcement_id, user_id) DO NOTHING"
                ),
                {"id": uuid.uuid4(), "i": inst_id, "a": aid, "u": uid},
            )
            acks += res.rowcount or 0
    ctx.count("announcement_acks", acks)

    await db.execute(
        text(
            "INSERT INTO institution_settings (id, institution_id, category, key, value, value_type, is_public, created_at, "
            "updated_at) VALUES (:id, :i, 'portals_meta', 'seed:phase39', CAST(:v AS jsonb), 'json', FALSE, NOW(), NOW())"
        ),
        {"id": uuid.uuid4(), "i": inst_id, "v": json.dumps({"at": datetime.now(UTC).isoformat()})},
    )
    await db.commit()
