"""phase24 communication advanced — data only (grants, settings, bot flows, notification templates)

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-24

Prompts/24 §24.2. ``bulk_campaigns`` already exists from ``0001`` and ``message_logs.campaign_id`` /
``conversation_sessions`` / ``ai_conversations`` are Phase 01 tables — expected delta migration: none. This revision:

* re-seeds role templates and back-fills ``BACKFILL_GRANTS["0024"]`` (registrar / vice-chancellor
  ``communication:bulk|approve``, HOD department-scoped ``communication:send``);
* adds the ``comms.*`` institution settings (quiet hours, per-day caps, approval threshold, assistant limits) and the
  ``campaign.*`` / ``emergency.*`` notification templates;
* sets the platform default ``platform_settings['bot_flows']`` (``app.enums.comms_advanced.BOT_FLOWS``) when absent.

Demo data: ``seed_demo_institution.py --only comms_advanced``. ``downgrade()`` leaves the rows.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.enums.comms_advanced import BOT_FLOWS
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0024")
    platform = seed_phase04_platform(conn)
    conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('bot_flows', CAST(:v AS JSONB)) ON CONFLICT (key) DO NOTHING"
        ),
        {"v": json.dumps({"flows": BOT_FLOWS, "greeting": "Hello! Reply with a number:"})},
    )
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings} bot_flows=default"
    )


def downgrade() -> None:
    """Data-only: grants, templates, settings and bot flows stay."""
