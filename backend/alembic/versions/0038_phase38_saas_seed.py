"""phase38 super admin & SaaS operations seed — data only (no tables)

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-27

Prompts/38 §38.2. The four ``subscription_plans`` get their prices (``PLAN_DEFAULTS``) and ``enabled_features`` from
the feature registry tiers (``data.export_portability`` registered); ``platform_settings`` receives the typed platform
keys (``billing``, ``usage.rates``, ``usage.caps_default``, ``usage.overage_alert_pct``, ``support.sla_hours``,
``support.categories``, ``demo.*``, ``registration.expiry_hours``, ``announcements.default_channels``,
``mobile.min_versions``, ``platform.status_page_url``, captcha, sales inbox, danger flags) without overwriting values an
operator already changed, plus ``plan:<code>`` plan-locked settings; ≈ 60 platform help articles with contextual slugs
``help:<route>`` (``app/services/saas/help_seed.py``); the permission catalogue gains the ``platform`` / ``support``
modules (role templates re-seeded + ``BACKFILL_GRANTS["0038"]``); notification templates ``saas.*``, ``support.*``,
``platform.announcement|impersonation_started|alert|outage_detected|connection_disabled``, ``feedback.responded``.
Demo data: ``seed_demo_institution.py --only saas``. ``downgrade()`` removes the seeded help articles and the typed
platform keys (plans / grants stay).
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.enums.saas import PLAN_DEFAULTS, PLATFORM_DEFAULTS
    from app.services.install_service import seed_features, seed_permissions, seed_plans, seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_phase04_platform
    from app.services.saas.help_seed import platform_articles

    conn = op.get_bind()
    features = seed_features(conn)
    permissions = seed_permissions(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0038")
    plans, _ = seed_plans(conn)
    for code, values in PLAN_DEFAULTS.items():
        conn.execute(
            text(
                "UPDATE subscription_plans SET price_paise_monthly = COALESCE(price_paise_monthly, :m), "
                "price_paise_yearly = COALESCE(price_paise_yearly, :y), updated_at = NOW() WHERE code = :c"
            ),
            {"m": values["price_paise_monthly"], "y": values["price_paise_yearly"], "c": code},
        )
        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) ON CONFLICT (key) DO NOTHING"
            ),
            {
                "k": f"plan:{code}",
                "v": json.dumps({"locked_settings": {"reports.max_rows": values["reports.max_rows"]}}),
            },
        )
    for key, value in PLATFORM_DEFAULTS.items():
        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "v": json.dumps(value)},
        )
    articles = 0
    for a in platform_articles():
        res = conn.execute(
            text(
                "INSERT INTO help_articles (institution_id, slug, title, body, module, audience, is_published) "
                "SELECT NULL, CAST(:slug AS varchar), :title, :body, :module, CAST(:aud AS jsonb), :pub "
                "WHERE NOT EXISTS (SELECT 1 FROM help_articles WHERE institution_id IS NULL AND slug = CAST(:slug AS varchar))"
            ),
            {
                "slug": a["slug"],
                "title": a["title"],
                "body": a["body"],
                "module": a["module"],
                "aud": json.dumps(a["audience"]),
                "pub": a["is_published"],
            },
        )
        articles += res.rowcount or 0
    platform = seed_phase04_platform(conn)
    print(  # noqa: T201 - alembic log
        f"  features={features} permissions={permissions} template_grants+={grants} tenant_grants+={backfilled} "
        f"plans={plans} help_articles+={articles} notification_templates+={platform['notification_templates']}"
    )


def downgrade() -> None:
    from app.enums.saas import PLATFORM_DEFAULTS
    from app.services.saas.help_seed import platform_articles

    conn = op.get_bind()
    conn.execute(
        text("DELETE FROM help_articles WHERE institution_id IS NULL AND slug = ANY(:s)"),
        {"s": [a["slug"] for a in platform_articles()]},
    )
    conn.execute(text("DELETE FROM platform_settings WHERE key = ANY(:k)"), {"k": list(PLATFORM_DEFAULTS)})
