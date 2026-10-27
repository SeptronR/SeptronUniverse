"""phase35 analytics read models — 13 materialized views (no tables) + data (grants, settings, platform dashboard
defaults, notification templates)

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-26

Prompts/35 §35.2. Creates the materialized read models of ``app/services/analytics/read_models.py`` (``mv_enrolment_daily``,
``mv_attendance_term``, ``mv_fees_position``, ``mv_exam_progress``, ``mv_results_summary``, ``mv_hr_snapshot``,
``mv_admissions_funnel``, ``mv_placement_funnel``, ``mv_hostel_occupancy``, ``mv_research_counts``,
``mv_service_desk_sla``, ``mv_risk_cohort``, ``mv_kpi_daily`` — the last reads the others), each with ``institution_id``
+ scope dimensions, a ``UNIQUE`` index for ``REFRESH … CONCURRENTLY`` and a tenant index. The same statements are
``Database_Schema.sql`` section 37 (``IF NOT EXISTS``: a fresh ``0001`` already created them). Views are registered in
``scripts/phase_manifest.py`` ``VIEWS`` (drift guard skips them); no new tables. Data: re-seeds role templates
(``analytics:view|export|manage`` per Prompts/35 "Visibility rules") + ``BACKFILL_GRANTS["0035"]``; ``analytics.*`` /
``risk.*`` settings through the institution defaults; ``platform_settings['dashboards.defaults']`` (role → widget key
order of the registry compositions; operators may reorder); the Phase 35 notification templates. Demo data:
``seed_demo_institution.py --only analytics``. ``downgrade()`` drops the views (data rows stay).
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dashboard_defaults() -> dict[str, list[str]]:
    from app.core.dashboards import DASHBOARD_REGISTRY
    from app.services.analytics.chart_service import ensure_catalogue

    ensure_catalogue()
    return {role: [w.key for w in widgets] for role, widgets in DASHBOARD_REGISTRY.items()}


def upgrade() -> None:
    from app.services.analytics.read_models import READ_MODELS
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    for model in READ_MODELS:
        for stmt in model.statements():
            conn.exec_driver_sql(stmt)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0035")
    platform = seed_phase04_platform(conn)
    conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('dashboards.defaults', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"v": json.dumps(_dashboard_defaults())},
    )
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  read models={len(READ_MODELS)} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    from app.services.analytics.read_models import READ_MODELS

    for model in reversed(READ_MODELS):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {model.name} CASCADE")
