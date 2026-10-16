"""phase09 registration — data only (grants, notification templates, registration settings)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15

Prompts/09 §09.2. The section 11 tables (``course_offerings`` … ``student_arrears``) and ``faculty_workloads`` /
``course_allocation_proposals`` (§9) already exist from ``0001`` — expected delta migration: none. This revision:

* re-seeds the platform role templates (registrar: offerings create / bulk / allocate + registration manage /
  override / bulk / allocate; dean: offerings create / bulk) and back-fills them into the tenant system roles
  (``BACKFILL_GRANTS["0009"]``);
* adds the platform notification templates of the registration events (submitted / returned / locked / withdrawn /
  window open, waitlist offered / expired, elective allocated, arrear waived) and copies the new ``registration.*`` /
  ``hr.workload_enforce`` settings rows into every institution. The ``registration.advisor`` workflow template ships
  with Phase 04 (class advisor, escalation to the HOD).

Demo data: ``seed_demo_institution.py --only offerings``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0009"
down_revision: str | None = "0008"
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
    backfilled = backfill_role_grants(conn, "0009")
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
