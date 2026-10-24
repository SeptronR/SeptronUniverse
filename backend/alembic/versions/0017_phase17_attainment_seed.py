"""phase17 OBE attainment — data only (grants, platform default config, notification templates, settings)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-24

Prompts/17 §17.2. ``attainment_configs`` / ``attainment_runs`` / ``co_attainments`` / ``po_attainments`` /
``cqi_actions`` (and ``feedback_surveys`` / ``feedback_responses`` read here) already exist from ``0001`` — expected
delta migration: none. This revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0017"]`` (faculty ``obe:view|compute`` — own
  offerings; dean ``obe:configure|compute|export``; IQAC ``obe:manage|compute|export``; students ``obe:view`` — own
  CO achievement only while ``obe.show_students`` is on);
* stores the platform default attainment config under ``platform_settings['attainment_defaults']`` (targets 60 / 60,
  levels 40 / 50 / 60, direct 80 / indirect 20, CIA 30 / ESE 70, CO / PO targets 2.0, question-wise ESE, survey
  thresholds 2 / 3 / 4) — copied per regulation / programme when an OBE coordinator saves a config;
* adds the notification templates ``obe.gap_detected``, ``cqi.action_assigned``, ``cqi.due_reminder``,
  ``cqi.action_verified``, ``obe.coverage_digest`` and the ``obe.*`` settings (student view, auto-run, strict
  prerequisites) to every tenant.

Demo data: ``seed_demo_institution.py --only attainment``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.enums.obe_attainment import ATTAINMENT_DEFAULTS
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        _put_platform_setting,
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0017")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "attainment_defaults", {"pack": "IN", "defaults": ATTAINMENT_DEFAULTS})
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay."""
