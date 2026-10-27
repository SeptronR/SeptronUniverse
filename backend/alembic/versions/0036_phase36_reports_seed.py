"""phase36 reports seed — data only (no tables)

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-27

Prompts/36 §36.2. Report runs are ``background_jobs`` rows (``report.run`` …), schedules / saved builder reports /
statutory state live in ``institution_settings`` (category ``reports_meta``; the typed settings in ``reports``),
statutory files in ``issued_documents``. Data: platform ``document_templates`` for the report print layouts
(``report_portrait``, ``report_landscape``, ``register_ledger``, ``statutory_cover`` — letterhead / watermark
placeholders), role templates re-seeded with the Phase 36 ``reports:*`` grants + ``BACKFILL_GRANTS["0036"]``, the
``reports.*`` settings through the institution defaults (``max_inline_rows``, ``max_rows``, ``retention_days``,
``schedule_hours_allowed``, ``statutory_signoff_roles``, ``builder_pii_default_masked``) and the Phase 36 notification
templates (``reports.ready`` / ``failed`` / ``scheduled_delivery`` / ``statutory_review_requested`` /
``statutory_signed_off`` / ``statutory_due``). Demo data: ``seed_demo_institution.py --only reports``.
``downgrade()`` removes the platform report templates (other data rows stay).
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = ("report_portrait", "report_landscape", "register_ledger", "statutory_cover")


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform
    from app.services.reports.templates import template_rows

    conn = op.get_bind()
    templates = 0
    for t in template_rows():
        exists = conn.execute(
            text("SELECT 1 FROM document_templates WHERE institution_id IS NULL AND template_type = :t"),
            {"t": t["template_type"]},
        ).first()
        if exists is not None:
            continue
        conn.execute(
            text(
                "INSERT INTO document_templates (institution_id, template_type, name, layout, html_template, css, page_size, "
                "is_bilingual, variables, is_default, version, is_active) VALUES (NULL, :t, :n, CAST(:l AS jsonb), :h, :c, "
                ":p, FALSE, CAST(:v AS jsonb), TRUE, 1, TRUE)"
            ),
            {
                "t": t["template_type"],
                "n": t["name"],
                "l": json.dumps(t["layout"]),
                "h": t["html_template"],
                "c": t["css"],
                "p": t["page_size"],
                "v": json.dumps(t["variables"]),
            },
        )
        templates += 1
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0036")
    platform = seed_phase04_platform(conn)
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  report templates+={templates} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    op.get_bind().execute(
        text("DELETE FROM document_templates WHERE institution_id IS NULL AND template_type = ANY(:t)"),
        {"t": list(TYPES)},
    )
