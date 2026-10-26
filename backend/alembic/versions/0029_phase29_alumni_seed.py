"""phase29 alumni, endowments & fundraising — data only (grants, settings, document templates, sequences,
notification templates)

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-26

Prompts/29 §29.2. The section 27 tables (``alumni_profiles`` … ``donations``) already exist from ``0001`` — expected
delta migration: none. This revision re-seeds role templates (``alumni_coordinator`` gains ``alumni:verify|campaign|
view_all|export`` and ``fundraising:receipt|view_all|export``; HODs read department alumni; the registrar reads
aggregates) and back-fills ``BACKFILL_GRANTS["0029"]``, adds the ``alumni.*`` / ``fundraising.*`` settings
(auto-create on graduation, claim verification, directory defaults / student access, jobs moderation, engagement
weights, 80G registration, ``80g:{fy}`` receipt sequence, minimum online amount, PAN threshold), the platform
``document_templates`` ``donation_receipt_80g`` (+ bilingual IN variant) and ``alumni_membership_card`` with their
``doc:*`` number sequences, and the Phase 29 notification templates (``alumni.profile_created`` / ``claim_link`` /
``verified``, ``alumni.event_invite``, ``alumni.job_approved``, ``donation.thank_you`` / ``receipt_ready``,
``campaign.milestone``, ``alumni.survey_invite`` …). Donation postings use the Phase 23 ``donations`` (general fund)
and ``3200`` (restricted fund) accounts; a campaign may name its own ledger account. Demo data:
``seed_demo_institution.py --only alumni``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
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
    backfilled = backfill_role_grants(conn, "0029")
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
    """Data-only: grants, settings, templates and sequences stay."""
