"""phase14 exams — data only (grants, fee-rule template, remuneration defaults, notification templates, settings)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-18

Prompts/14 §14.2. The section 15 tables, ``exam_centres`` (§31), ``malpractice_cases`` and ``calendar_events`` already
exist from ``0001`` — expected delta migration: none. This revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0014"]`` (HOD ``exams:view|view_all``, faculty
  ``exams:qp`` — own setter assignments only, parent ``exams:view``);
* stores ``platform_settings['exam_fee_rules_template']`` (per course / per arrear / practical / cap / late fee, paise)
  and ``platform_settings['exam_duty_remuneration']`` (per invigilation role + QP setter);
* adds the date-sheet / duty-reminder notification templates and the ``exams.duty_remuneration`` setting row.
  Hall-ticket / date-sheet PDFs use the built-in renderer until Phase 26 document templates exist.

Demo data: ``seed_demo_institution.py --only exams``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.exams.common import DEFAULT_FEE_RULES
    from app.services.exams.duty_qp_service import DEFAULT_RATES
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        _put_platform_setting,
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0014")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "exam_fee_rules_template", DEFAULT_FEE_RULES)
    _put_platform_setting(conn, "exam_duty_remuneration", DEFAULT_RATES)
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay."""
