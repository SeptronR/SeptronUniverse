"""phase32 accreditation & compliance (IQAC) — data only (criteria trees, metric definitions, grants, workflow,
settings, notification templates)

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-26

Prompts/32 §32.2. The section 29 tables (``accreditation_frameworks`` … ``audit_registers``) already exist from
``0001`` together with the §36 seed (six frameworks, the top-level NAAC / NBA criteria and 30 metric definitions) —
expected delta migration: none. This revision completes the ``framework_criteria`` trees from
``app/enums/accreditation.py:FRAMEWORK_TREES`` (NAAC 2024 key indicators / metrics with ``metric_type``,
``max_score``, ``metric_key``; NBA GAPC v4 sub-criteria with marks; NIRF TLR / RP / GO / OI / PR parameters; AISHE DCF
sections; AICTE / UGC data packs; parents resolved by dotted code, upserted on ``(framework_id, code)``), inserts the
remaining ``metric_definitions`` (``METRIC_DEFINITIONS`` with ``computation_key``, ``params_schema``, ``depends_on``,
``is_derived``), re-seeds role templates (faculty ``accreditation:view|evidence``; HOD ``view|override|evidence``;
principal / dean ``approve|override``; registrar / CoE / OBE coordinator / accountant / placement officer / librarian
``view``) and back-fills ``BACKFILL_GRANTS["0032"]``; adds the ``accreditation.*`` settings (period type, weekly
compute, override verification, evidence size, disclosure items, custom criteria), the workflow
``accreditation.response_review`` (owner's HOD → IQAC → principal) and the Phase 32 notification templates. Demo data:
``seed_demo_institution.py --only accreditation``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.accreditation.catalogue import seed_accreditation_catalogue
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    defs, crits = seed_accreditation_catalogue(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0032")
    platform = seed_phase04_platform(conn)
    settings = workflows = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        settings += out["settings"]
        workflows += out.get("workflow_definitions", 0)
    print(  # noqa: T201 - alembic log
        f"  seeded: metric_definitions+={defs} framework_criteria+={crits} template_grants+={grants} "
        f"tenant_grants+={backfilled} notification_templates+={platform['notification_templates']} "
        f"workflow_definitions+={workflows} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: criteria, definitions, grants, workflows, templates and settings stay."""
