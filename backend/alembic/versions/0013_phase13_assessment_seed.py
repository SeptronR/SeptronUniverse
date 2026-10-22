"""phase13 assessment — data only (grants, OBE templates, notification templates, settings)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-18

Prompts/13 §13.2. The section 14 tables (OBE definitions, offering assessments, internal marks, CIA, change requests,
projects, question bank / papers, LMS, lesson plans, course files) and ``college_data_submissions`` already exist from
``0001`` — expected delta migration: none. This revision:

* re-seeds the platform role templates and back-fills ``BACKFILL_GRANTS["0013"]`` (exam cell ``marks:lock``; HOD
  ``obe:manage|view`` + ``lms:view_all`` + ``projects:view_all`` + ``marks:correct``; dean ``obe:manage``; registrar
  ``marks:view_all``; parent ``lms:view`` + ``projects:view``);
* stores the OBE templates in ``platform_settings['obe_templates']`` (NBA 12 POs for engineering, generic 8 POs,
  Bloom levels) — copied per programme on demand by ``POST /programs/{id}/outcomes/import-template``;
* adds the notification templates (marks deadline, assignment published, course announcement) and the
  ``assessment.*`` settings rows. ``marks.change`` (HOD → COE) ships with Prompts/04.

Demo data: ``seed_demo_institution.py --only assessment``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.assessment.obe_service import template_json
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        _put_platform_setting,
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0013")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "obe_templates", template_json())
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings} obe_templates=1"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay."""
