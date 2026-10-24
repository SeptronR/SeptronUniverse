"""phase23 accounting — data only (IN chart of accounts, grants, workflows, settings, notification templates)

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-24

Prompts/23 §23.2. The section 22 tables already exist from ``0001`` (``ledger_accounts`` with the Phase 12 minimal chart)
— expected delta migration: none. This revision:

* extends every tenant's chart with the IN pack template (``app/enums/accounting.IN_CHART``: assets incl. bank
  accounts / fixed-asset classes, liabilities incl. TDS / GST / PF payables and unspent grants, equity funds, other
  income, expense heads incl. salaries, consumables, depreciation, bank charges) — Phase 12 codes and the
  ``fee_heads.ledger_account_id`` links are kept, the fee-head accounts hang under 4000;
* re-seeds role templates and back-fills ``BACKFILL_GRANTS["0023"]`` (HOD ``accounting:view|post``, faculty
  ``accounting:view`` for their grants, accountant post / reconcile / approve / export, vice-chancellor approve, IQAC
  ``view_all``);
* adds the workflow templates ``accounting.expense`` and ``accounting.budget_allocation`` (accountant →
  vice-chancellor) — 38 templates — and the ``accounting.*`` settings / notification templates.

Demo data: ``seed_demo_institution.py --only accounting``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.accounting.chart_service import seed_chart_sql
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0023")
    platform = seed_phase04_platform(conn)
    accounts = workflows = settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        accounts += seed_chart_sql(conn, iid)
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} ledger_accounts+={accounts} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: accounts, grants, templates and settings stay."""
