"""phase26 document templates, certificates & requests — data only (templates, grants, settings, sequences, notifications)

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-25

Prompts/26 §26.2. ``document_templates``, ``certificate_requests``, ``issued_documents`` and ``document_serials``
already exist from ``0001`` — expected delta migration: none. This revision seeds the platform default templates for
every ``template_type`` (IN-pack bilingual bonafide / degree / provisional / TC, staff / scholar ID cards), re-seeds
role templates and back-fills ``BACKFILL_GRANTS["0026"]``, adds the ``documents.*`` settings (signatories, request
rules, watermark, verification options), the ``doc:{type}`` / ``serial:{register}`` number sequences and the
``documents.*`` notification templates. The register back-fill of earlier-phase PDFs runs as the job
``documents.backfill_register`` (data, not DDL). Demo data: ``seed_demo_institution.py --only documents``.
``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        backfill_role_grants,
        seed_document_templates,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    templates = seed_document_templates(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0026")
    platform = seed_phase04_platform(conn)
    settings = sequences = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        settings += out["settings"]
        sequences += out["number_sequences"]
    print(  # noqa: T201 - alembic log
        f"  seeded: document_templates+={templates} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings} "
        f"number_sequences+={sequences}"
    )


def downgrade() -> None:
    """Data-only: templates, grants, settings and sequences stay."""
