"""phase08 admissions — data only (form template, grants, refund workflow + notification templates, settings)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09

Prompts/08 §08.2. The section 10 tables (``admission_cycles`` … ``enquiries``) already exist from ``0001`` — expected
delta migration: none. This revision:

* writes ``platform_settings['admission_form_template']`` (steps, fields, required documents by level, refund policy);
  the IN pack's quota / category lists already live in the pack;
* re-seeds the platform role templates (``admissions:view`` for all staff, ``admissions:view_all`` for the HOD,
  ``admissions:view_pii`` for the admissions office / registrar / institution admin) and back-fills them into the
  tenant system roles (``BACKFILL_GRANTS["0008"]``);
* refreshes ``platform_settings['workflow_templates']`` (26 — ``admissions.refund`` admissions office → accounts) and
  the platform notification templates (enquiry assignment / follow-up), copying the missing workflow definitions and
  the new ``admissions.*`` settings rows into every institution.

Demo data: ``seed_demo_institution.py --only admissions``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        backfill_role_grants,
        seed_admission_form_template,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    seed_admission_form_template(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0008")
    platform = seed_phase04_platform(conn)
    workflows = settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} "
        f"workflow_definitions+={workflows} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay."""
