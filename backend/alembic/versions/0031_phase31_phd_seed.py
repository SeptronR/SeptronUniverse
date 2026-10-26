"""phase31 PhD & research-scholar management — data only (grants, workflows, settings, document / notification
templates, sequences, publications.scholar_id FK)

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-26

Prompts/31 §31.2. The section 28 tables (``research_scholars`` … ``etd_uploads``) already exist from ``0001`` —
expected delta migration: none (``0001`` also created ``fk_publications_scholar``; it is re-asserted here only when
missing). This revision re-seeds role templates (faculty ``phd:guide|view``; HOD / dean ``phd:dc|view_all|approve``;
the research cell ``phd:fellowship|examine|etd|view_all|export|approve``; CoE ``phd:examine|view``; accountant
``phd:fellowship|view``) and back-fills ``BACKFILL_GRANTS["0031"]``; adds the ``phd.rules`` defaults from the IN pack
(guide load by cadre 8 / 6 / 4, coursework 12 credits incl. research methodology within 12 months, half-yearly
reports, unsatisfactory limit 2, durations 24 / 72 months, extension 24 (+ women / PwD relaxation 24), similarity 10 %,
AI declaration, examiners ≥ 2 external / 1 outside state, viva after accept | minor, ETD 30 days, JRF ₹37,000 / SRF
₹42,000 with HRA, yearly contingency) and the ``phd.*`` switches; the workflow templates ``phd.examiner_panel`` (dean
→ VC when ``phd.panel_vc_approval``), ``phd.thesis_dc_approval`` (DC members parallel → convenor) and ``phd.award``
(research cell → dean → council when ``governance.minutes``) next to the shipped ``phd.request``; the platform
``document_templates`` ``phd_registration_letter``, ``phd_synopsis_ack``, ``phd_provisional_certificate``,
``examiner_invitation`` with their ``doc:*`` sequences; the Phase 31 notification templates (``phd.guide_allocated``,
``phd.dc_meeting_scheduled``, ``phd.progress_report_due|reviewed``, ``phd.fellowship_disbursed``,
``phd.request_decided``, ``phd.thesis_similarity_result``, ``phd.examiner_invite``, ``phd.examiner_report_received``,
``phd.viva_scheduled``, ``phd.awarded``, ``phd.etd_uploaded``, ``phd.duration_warning``, ``phd.cancellation_review``).
Demo data: ``seed_demo_institution.py --only phd``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
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
    conn.execute(
        text(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_publications_scholar') THEN "
            "ALTER TABLE publications ADD CONSTRAINT fk_publications_scholar FOREIGN KEY (scholar_id) "
            "REFERENCES research_scholars(id) ON DELETE SET NULL; END IF; END $$;"
        )
    )
    templates = seed_document_templates(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0031")
    platform = seed_phase04_platform(conn)
    settings = workflows = sequences = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        settings += out["settings"]
        workflows += out.get("workflow_definitions", 0)
        sequences += out.get("number_sequences", 0)
    print(  # noqa: T201 - alembic log
        f"  seeded: document_templates+={templates} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings} number_sequences+={sequences}"
    )


def downgrade() -> None:
    """Data-only: grants, workflows, templates, settings and sequences stay."""
