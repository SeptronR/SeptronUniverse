"""phase11 attendance — data only (grants, notification templates, workflow template, settings)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18

Prompts/11 §11.2. The section 12 tables (``student_class_attendance`` + its default partition, ``on_duty_requests``,
``attendance_summaries``, ``attendance_condonations``, ``term_eligibility``) already exist from ``0001`` — expected
delta migration: none (monthly partitions of ``student_class_attendance`` come from the Phase 01 Beat
``partitions.ensure_next_month``). This revision:

* re-seeds the platform role templates (registrar ``attendance:mark|edit_finalized|condone`` + ``exams:eligibility``;
  HOD ``attendance:edit_finalized``; controller of examinations ``exams:eligibility``; vice-chancellor
  ``attendance:condone``) and back-fills them into the tenant system roles (``BACKFILL_GRANTS["0011"]``);
* adds the platform notification templates (on duty requested / approved / rejected, condonation requested /
  approved / rejected, detention notice, missing-attendance digest), the ``attendance.on_duty`` workflow template
  (HOD) and the ``attendance.*`` / ``exams.eligibility_requires_fee_clear`` settings rows.

Demo data: ``seed_demo_institution.py --only attendance``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0011")
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
