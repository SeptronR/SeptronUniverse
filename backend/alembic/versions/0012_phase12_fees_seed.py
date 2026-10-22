"""phase12 fees — data only (grants, notification / workflow templates, settings, sequences, fee defaults)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18

Prompts/12 §12.2. The section 13 tables and ``ledger_accounts`` (§22) already exist from ``0001`` — expected delta
migration: none. This revision:

* re-seeds the platform role templates and back-fills ``BACKFILL_GRANTS["0012"]`` into tenant system roles
  (registrar refunds / scholarship sanction / no-dues, vice-chancellor receipt cancellation + sanction, HOD
  department dues + scholarship recommendation + department / lab no-dues, class-advisor dues, accountant
  scholarship verification, warden / sports / transport / placement no-dues sign-off, parent scholarship / no-dues
  reads);
* adds the platform notification templates (bounce, refund processed, day-book open, scholarship sanctioned, no-dues
  blocked / cleared) and the ``fees.concession`` workflow template (29 templates);
* per institution: the ``fees.*`` settings rows, the ``fee_invoice_no`` sequence and the fee defaults
  (``services/fees/defaults.py``: ledger chart, IN fee-head template with GST flags, late-fee / library fines,
  ``SIBLING`` / ``STAFFWARD`` discounts).

The earlier phases' fee stubs (Phase 08 applicant payments, Phase 09 / 11 audit ``fee_order`` rows) are turned into
invoices by ``POST /fees/backfill-stubs`` / the ``--only fees`` demo seed (they need the async invoice service and
number sequences). ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
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
    backfilled = backfill_role_grants(conn, "0012")
    platform = seed_phase04_platform(conn)
    workflows = settings = sequences = heads = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
        sequences += out["number_sequences"]
        heads += out["fees"]["fee_heads"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings} sequences+={sequences} fee_heads+={heads}"
    )


def downgrade() -> None:
    """Data-only: grants, templates, settings and fee masters stay."""
