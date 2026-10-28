"""``integrations`` demo seeder (Prompts/41 §41.2) — ``seed_demo_institution.py --only integrations``.

For the profile tenant: one mock connection per hub capability (sandbox) with 7 days of health checks, 3 API keys
(the secrets are random and never printed), 4 webhooks with a mix of delivered / failed / dead deliveries, and 3 data
imports (applied, validated with errors, rolled back). Idempotent via the marker ``integrations_meta seed:phase41``.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text


@seeder("integrations", after=["base"])
async def seed_integrations(ctx: SeedContext) -> None:
    import app.features  # noqa: F401
    from app.core.security import encrypt_secret
    from app.db.session import bind_tenant, set_tenant
    from app.integrations.catalogue import CAPABILITY_INFO
    from app.integrations.hub import encrypt_config
    from app.models.platform import (
        ApiKey,
        DataImport,
        Institution,
        IntegrationConnection,
        IntegrationHealthCheck,
        Webhook,
        WebhookDelivery,
    )
    from app.services.integrations.api_key_service import hash_key

    db = ctx.db
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    iid = inst.id
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    marker = {"i": iid}
    done = (
        await db.execute(
            text(
                "SELECT 1 FROM institution_settings WHERE institution_id = :i AND category = 'integrations_meta' AND key = 'seed:phase41'"
            ),
            marker,
        )
    ).first()
    if done:
        print("   integrations: already seeded (marker integrations_meta/seed:phase41)")
        return
    now = datetime.now(UTC)
    conns = 0
    for cap in CAPABILITY_INFO:
        c = IntegrationConnection(
            institution_id=iid,
            capability=cap,
            provider="mock",
            label=f"Mock {cap}",
            config_encrypted=encrypt_config({}),
            public_config={},
            is_sandbox=True,
            status="active",
            last_health_at=now,
        )
        db.add(c)
        await db.flush()
        conns += 1
        for d in range(7):
            db.add(
                IntegrationHealthCheck(
                    institution_id=iid,
                    connection_id=c.id,
                    checked_at=now - timedelta(days=d),
                    ok=d != 3,
                    latency_ms=40 + d * 7,
                    detail=None if d != 3 else "timeout",
                )
            )
    for name, scopes in (
        ("ERP sync", ["students:read", "fees:read"]),
        ("Library kiosk", ["library:read"]),
        ("BI export", ["reports:read"]),
    ):
        secret = "su_" + secrets.token_urlsafe(32)
        db.add(
            ApiKey(
                institution_id=iid,
                name=name,
                key_prefix=secret[:12],
                hashed_key=hash_key(secret),
                scopes=scopes,
                rate_limit_per_minute=600,
                expires_at=now + timedelta(days=180),
            )
        )
    statuses = ["delivered", "delivered", "delivered", "failed", "dead"]
    for n, (name, events) in enumerate(
        (
            ("Admissions CRM", ["admission.application.submitted"]),
            ("Finance ledger", ["fees.payment.received"]),
            ("LMS sync", ["student.enrolled"]),
            ("Alumni portal", ["result.published"]),
        )
    ):
        w = Webhook(
            institution_id=iid,
            name=name,
            url=f"https://hooks.example.test/{n}",
            secret_encrypted=encrypt_secret(secrets.token_hex(24)),
            events=events,
            is_active=n != 3,
        )
        db.add(w)
        await db.flush()
        for k in range(10):
            st = statuses[(k + n) % len(statuses)]
            db.add(
                WebhookDelivery(
                    institution_id=iid,
                    webhook_id=w.id,
                    event_id=uuid.uuid4(),
                    event_type=events[0],
                    status=st,
                    attempts=1 if st == "delivered" else (5 if st == "dead" else 2),
                    response_code=200 if st == "delivered" else 500,
                    next_retry_at=now + timedelta(minutes=30) if st == "failed" else None,
                    delivered_at=now - timedelta(hours=k) if st == "delivered" else None,
                )
            )
    for entity, status, total, valid in (
        ("students", "applied", 250, 250),
        ("books", "validated", 120, 104),
        ("staff", "rolled_back", 40, 40),
    ):
        db.add(
            DataImport(
                institution_id=iid,
                entity=entity,
                file_url=f"seed/imports/{entity}.csv",
                mapping={},
                mode="apply" if status != "validated" else "dry_run",
                status=status,
                total_rows=total,
                valid_rows=valid,
                error_rows=total - valid,
                report={"seed": True},
                applied_at=now - timedelta(days=3) if status != "validated" else None,
                rolled_back_at=now - timedelta(days=1) if status == "rolled_back" else None,
            )
        )
    await db.execute(
        text(
            "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, is_public, created_at, updated_at) "
            "VALUES (:id, :i, NULL, 'integrations_meta', 'seed:phase41', 'true'::jsonb, 'json', FALSE, NOW(), NOW()) ON CONFLICT DO NOTHING"
        ),
        {"id": uuid.uuid4(), "i": iid},
    )
    await db.commit()
    print(f"   integrations: {conns} connections, 3 API keys, 4 webhooks, 3 imports")
