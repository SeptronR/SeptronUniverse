"""phase30 research & faculty development — data only (permission, grants, workflows, settings, notification
templates)

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-26

Prompts/30 §30.2. The section 28 tables (``publications`` … ``incubation_startups``) already exist from ``0001`` —
expected delta migration: none. This revision adds the bespoke permission ``research:verify``, re-seeds role templates
(the research cell gains ``research:verify|view_all|export|ethics|incentives|mous|incubation``; HODs verify their
department's records first and read department research; IQAC reads aggregates) and back-fills
``BACKFILL_GRANTS["0030"]``; adds the workflow templates ``research.incentive`` (HOD recommend → research cell → dean
above ``research.incentive_dean_threshold_paise``), ``research.project_sanction`` (research cell → principal),
``research.ethics_review`` (member review → chair decide) and ``research.mou`` (research cell → legal officer when
``governance.legal`` is on → principal) to every tenant's ``workflow_definitions``; the ``research.*`` settings
(``api_score_scheme`` UGC_CAS_2018 tables, ``publication_incentive_slabs``, seed / travel grant caps, consultancy
share 30 / 70, ``duplicate_doi_policy`` block, ``mou_expiry_alert_days`` 90, ``import_sources``, FDP hours target,
ethics categories) and the Phase 30 notification templates (``research.publication_verified|rejected``,
``research.project_sanctioned|report_due|closing``, ``research.incentive_status``, ``research.ethics_decision``,
``research.mou_expiring``, ``research.fdp_recorded``, ``research.api_updated``, ``research.patent_renewal``). Demo
data: ``seed_demo_institution.py --only research``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_permissions, seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    perms = seed_permissions(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0030")
    platform = seed_phase04_platform(conn)
    settings = workflows = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        settings += out["settings"]
        workflows += out.get("workflow_definitions", 0)
    print(  # noqa: T201 - alembic log
        f"  seeded: permissions+={perms} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: permissions, grants, workflows, templates and settings stay."""
