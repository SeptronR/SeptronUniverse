"""phase18 degrees — data only (grants, platform degree templates, notification templates, settings)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-24

Prompts/18 §18.2. ``degree_eligibility_checks`` / ``convocations`` / ``convocation_registrations`` /
``degrees_awarded`` / ``digital_credentials`` (and ``abc_credit_ledger`` from Phase 15) already exist from ``0001`` —
expected delta migration: none. This revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0018"]`` (students / parents / alumni
  ``degrees:view`` — own / wards; registrar ``degrees:manage|view``; HOD ``degrees:view_all`` — department);
* stores the platform default templates (degree, diploma, certificate, provisional certificate, convocation
  invitation; bilingual EN / HI, IN pack) under ``platform_settings['degree_templates']`` — Phase 26 moves them into
  ``document_templates``;
* adds the notification templates ``degrees.eligible``, ``degrees.awarded``, ``convocation.registration_open``,
  ``credentials.pushed`` and the ``degrees.*`` settings to every tenant.

Demo data: ``seed_demo_institution.py --only degrees``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEGREE_TEMPLATES = {
    "pack": "IN",
    "languages": ["en", "hi"],
    "templates": {
        "degree": {
            "title": {"en": "DEGREE CERTIFICATE", "hi": "उपाधि प्रमाण-पत्र"},
            "seal": True,
            "signatures": ["registrar", "vice_chancellor"],
        },
        "diploma": {"title": {"en": "DIPLOMA", "hi": "डिप्लोमा"}, "seal": True, "signatures": ["registrar"]},
        "certificate": {"title": {"en": "CERTIFICATE", "hi": "प्रमाण-पत्र"}, "seal": True, "signatures": ["registrar"]},
        "provisional_certificate": {
            "title": {"en": "PROVISIONAL CERTIFICATE", "hi": "अनंतिम प्रमाण-पत्र"},
            "seal": False,
            "signatures": ["controller_of_examinations"],
        },
        "convocation_invitation": {"title": {"en": "CONVOCATION INVITATION", "hi": "दीक्षांत समारोह आमंत्रण"}, "qr": True},
    },
    "qr": True,
}


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        _put_platform_setting,
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0018")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "degree_templates", DEGREE_TEMPLATES)
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay."""
