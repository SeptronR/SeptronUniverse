"""phase06 staff, faculty, HR, recruitment & CAS — data only (HR templates per institution, workflow templates, grants)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28

Prompts/06 §06.2. The section 9 tables (``designations`` … ``course_allocation_proposals``) already exist from ``0001``
— expected delta migration: none. This revision:

* re-seeds the platform registries (role templates gained ``leaves:encash`` for staff self-service and
  ``faculty:workload_manage`` for the dean) and back-fills them into the tenant system roles
  (``BACKFILL_GRANTS["0006"]``);
* refreshes ``platform_settings['workflow_templates']`` and the platform notification templates (5 HR workflow
  templates — ``attendance.regularise``, ``hr.loan``, ``hr.cas``, ``hr.leave_encashment``, ``hr.course_allocation`` —
  and the ``hr`` notification events), copying the missing workflow definitions into every institution;
* copies the pack's HR templates into every institution (``seed_hr_defaults``: designations by cadre, the leave-type
  template — CL 12, EL 30 accruing 2.5/month, ML 20, duty, study, sabbatical, maternity 182, paternity 15, LTC, LWP —
  and the payroll components with PF / ESI / PT / TDS / LWF) plus the new ``hr`` / ``payroll`` / ``attendance``
  settings rows (``seed_institution_defaults`` is idempotent).

Canonical DDL fix: ``payroll_components.component_type`` / ``staff_payroll_items.component_type`` were ``VARCHAR(20)``
although their own documented value ``employer_contribution`` has 21 characters — widened to ``VARCHAR(30)`` (here and
in ``Database_Schema.sql``; a widening is expand-safe).

Demo data: ``seed_demo_institution.py --only hr``. ``downgrade()`` leaves tenant rows in place (staff records and
payroll reference them).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0006"
down_revision: str | None = "0005"
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
    for table in ("payroll_components", "staff_payroll_items"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN component_type TYPE VARCHAR(30)")
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0006")
    platform = seed_phase04_platform(conn)
    totals = {"designations": 0, "leave_types": 0, "payroll_components": 0, "workflow_definitions": 0, "settings": 0}
    for iid, pack in conn.execute(
        text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")
    ).all():
        out = seed_institution_defaults(conn, iid, pack)
        for k in ("designations", "leave_types", "payroll_components"):
            totals[k] += out["hr"][k]
        totals["workflow_definitions"] += out["workflow_definitions"]
        totals["settings"] += out["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} "
        + " ".join(f"{k}+={v}" for k, v in totals.items())
    )


def downgrade() -> None:
    """Data-only: tenant HR rows stay (staff, payroll and leaves reference them)."""
