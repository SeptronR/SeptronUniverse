"""phase07 students, enrolment, holds & standing — data only (grants, workflow + notification templates, settings,
undertaking / ID-card document templates)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07

Prompts/07 §07.2. The section 8 tables (``students`` … ``credit_transfers``) already exist from ``0001`` — expected
delta migration: none. This revision:

* re-seeds the platform role templates (``students:view_pii`` for the institution admin, ``credit_transfers:verify`` /
  ``view_all`` for the HOD) and back-fills them into the tenant system roles (``BACKFILL_GRANTS["0007"]``);
* refreshes ``platform_settings['workflow_templates']`` (25 templates — ``students.transfer`` registrar → principal,
  ``students.credit_transfer`` HOD → registrar) and the platform notification templates (student / guardian welcome,
  hold placed / released, promotion, detention, standing, exit, transfer and credit-transfer decisions, undertaking
  reminders, document expiry), copying the missing workflow definitions and the new ``students.*`` settings rows into
  every institution;
* inserts the platform ``document_templates`` (``institution_id`` NULL): the undertaking texts of the IN and generic
  packs (``anti_ragging``, ``conduct``, ``data_consent``, ``photo_consent``, ``hostel_rules``; template_type
  ``undertaking``) and the CR80 student ``id_card`` layout.

Demo data: ``seed_demo_institution.py --only students``. ``downgrade()`` leaves the rows (students reference them).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
        seed_student_templates,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0007")
    platform = seed_phase04_platform(conn)
    templates = seed_student_templates(conn)
    workflows = settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} document_templates+={templates} "
        f"workflow_definitions+={workflows} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay (student undertakings reference the templates)."""
