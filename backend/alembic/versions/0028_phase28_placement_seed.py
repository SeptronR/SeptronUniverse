"""phase28 placement, internships & training — data only (permissions, grants, settings, resume templates,
notification templates)

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-26

Prompts/28 §28.2. The section 27 tables (``companies`` … ``company_feedback``) already exist from ``0001`` — expected
delta migration: none. This revision adds the bespoke permissions ``placement:wards`` / ``placement:evaluate``,
re-seeds role templates (``recruiter`` keeps ``placement:recruiter`` — own company drives, consented profile fields) and
back-fills ``BACKFILL_GRANTS["0028"]``, adds the ``placement.*`` settings (eligibility / policy defaults, consented
fields, blacklist rules, internship minimum weeks, NIRF median basis), stores the three resume layouts under
``platform_settings['resume_templates']`` and adds the Phase 28 notification templates (``placement.shortlisted``,
``placement.round_scheduled``, ``placement.round_result``, ``placement.offer_reminder``, ``placement.blacklisted``,
``internship.noc_ready``, ``training.session_reminder``, ``recruiter.invited``). Demo data:
``seed_demo_institution.py --only placement``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.enums.placement import RESUME_TEMPLATES
    from app.services.install_service import seed_permissions, seed_role_templates
    from app.services.institution_defaults import (
        _put_platform_setting,
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    perms = seed_permissions(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0028")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "resume_templates", RESUME_TEMPLATES)
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: permissions+={perms} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: permissions, grants, templates and settings stay."""
