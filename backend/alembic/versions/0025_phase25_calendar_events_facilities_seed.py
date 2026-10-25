"""phase25 calendar, events & facilities — data only (grants, workflows, settings, sequences, notification templates)

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-25

Prompts/25 §25.2. The section 24 tables, ``amc_contracts`` (§21) and ``emergency_alerts`` (§23) already exist from
``0001`` — expected delta migration: none. This revision re-seeds role templates and back-fills
``BACKFILL_GRANTS["0025"]`` (``facilities:counsel`` is new), adds the workflow templates ``facilities.equipment_booking``
and ``event.budget`` (40 templates), the ``facilities.*`` / ``wallet.*`` settings, the ``sr`` / ``visitor`` number
sequences and the calendar / event / booking / service-desk / visitor / SOS / health / sports / wallet notification
templates. Demo data: ``seed_demo_institution.py --only facilities``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0025")
    platform = seed_phase04_platform(conn)
    workflows = settings = sequences = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
        sequences += out["number_sequences"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings} number_sequences+={sequences}"
    )


def downgrade() -> None:
    """Data-only: grants, templates, settings and sequences stay."""
