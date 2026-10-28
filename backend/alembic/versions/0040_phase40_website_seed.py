"""phase40 public website, catalogue, admission entry & marketing site seed — data only (tables exist since 0001)

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-28

Prompts/40 §40.2. A default ``institution_website_config`` per existing institution (sections template by
institution type, theme from ``general.theme``); ``platform_settings['website.sections']`` (the section catalogue) and
``['marketing.site']`` (published default marketing content); feature keys ``website.core|course_catalog|
custom_domain``; ``website:*`` grants for registrar / college admin / HOD / IQAC / admissions (``BACKFILL_GRANTS
["0040"]``); notification templates ``website.*``. The ``website.*`` settings come from the settings template.
Demo data: ``seed_demo_institution.py --only website``. ``downgrade()`` removes the platform keys only.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.enums.website import SECTION_TYPES
    from app.services.install_service import seed_features, seed_permissions, seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_phase04_platform
    from app.services.website.marketing_service import DEFAULT_MARKETING
    from app.services.website.site_service import default_config

    conn = op.get_bind()
    features = seed_features(conn)
    permissions = seed_permissions(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0040")
    for key, value in (
        ("website.sections", list(SECTION_TYPES)),
        ("marketing.site", {"draft": None, "published": DEFAULT_MARKETING, "published_at": None}),
    ):
        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "v": json.dumps(value)},
        )
    configs = 0
    for inst in conn.execute(
        text("SELECT id, name, institution_type FROM institutions WHERE deleted_at IS NULL")
    ).mappings():
        theme = conn.execute(
            text(
                "SELECT value FROM institution_settings WHERE institution_id = :i AND category = 'general' AND key = 'theme' AND college_id IS NULL"
            ),
            {"i": inst["id"]},
        ).scalar()
        cfg = default_config(type("I", (), dict(inst))())
        cfg["theme"] = {"name": theme or "indigo"}
        res = conn.execute(
            text(
                "INSERT INTO institution_website_config (institution_id, is_enabled, theme, hero, sections, seo, contact, social, "
                "show_catalog, show_apply) VALUES (:i, TRUE, CAST(:t AS jsonb), CAST(:h AS jsonb), CAST(:s AS jsonb), "
                "CAST(:seo AS jsonb), '{}'::jsonb, '{}'::jsonb, TRUE, TRUE) ON CONFLICT (institution_id) DO NOTHING"
            ),
            {
                "i": inst["id"],
                "t": json.dumps(cfg["theme"]),
                "h": json.dumps(cfg["hero"]),
                "s": json.dumps(cfg["sections"]),
                "seo": json.dumps(cfg["seo"]),
            },
        )
        configs += res.rowcount or 0
    platform = seed_phase04_platform(conn)
    print(  # noqa: T201 - alembic log
        f"  features={features} permissions={permissions} template_grants+={grants} tenant_grants+={backfilled} "
        f"website_configs+={configs} notification_templates+={platform['notification_templates']}"
    )


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM platform_settings WHERE key IN ('website.sections', 'marketing.site')"))
