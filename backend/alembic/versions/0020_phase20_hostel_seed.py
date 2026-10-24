"""phase20 hostel — data only (grants, workflow templates, hostel fine, settings, notification / document templates)

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-24

Prompts/20 §20.2. The section 19 hostel tables (with the partial unique indexes ``one_active_bed``,
``one_active_resident``, ``one_active_quarter``) already exist from ``0001`` — expected delta migration: none. This
revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0020"]`` (registrar ``hostel:manage``; HOD
  ``hostel:view_all`` — department; class advisors ``hostel:view`` — advisees);
* adds the workflow templates ``hostel.leave`` / ``hostel.room_change`` (warden of the hostel via
  ``context.warden_user_id``) and ``hostel.eviction`` (warden → registrar) — 35 templates — to every tenant;
* inserts ``fine_configurations(applies_to='hostel', flat ₹100 per started hour, capped ₹1,000)`` per tenant;
* stores the platform default documents ``hostel_allotment`` (allotment letter) and ``hostel_rules`` under
  ``platform_settings['hostel_templates']`` (Phase 26 moves them into ``document_templates``);
* adds the hostel / mess notification templates and the ``hostel.*`` settings (consent, gate, roll-call, mess,
  allotment).

The Phase 02 development stub ``GET /hostels`` and ``app/features/dev_stubs.py`` are gone — ``hostel.core`` now lives in
``app/features/hostel.py`` behind the real router. Demo data: ``seed_demo_institution.py --only hostel``.
``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOSTEL_TEMPLATES = {
    "pack": "IN",
    "hostel_allotment": {
        "title": "HOSTEL ALLOTMENT LETTER",
        "fields": [
            "student",
            "registration_number",
            "hostel",
            "block",
            "room",
            "bed",
            "academic_year",
            "fee",
            "deposit",
        ],
        "footer": "Report to the warden with this letter and the fee receipt.",
    },
    "hostel_rules": {
        "title": "HOSTEL RULES",
        "sections": ["roll-call", "out-pass & leave", "visitors", "mess", "damages", "discipline"],
    },
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
    backfilled = backfill_role_grants(conn, "0020")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "hostel_templates", HOSTEL_TEMPLATES)
    workflows = settings = fines = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
        if not conn.execute(
            text("SELECT 1 FROM fine_configurations WHERE institution_id = :i AND applies_to = 'hostel'"), {"i": iid}
        ).first():
            conn.execute(
                text(
                    "INSERT INTO fine_configurations (institution_id, applies_to, calc_type, amount_paise, grace_days, max_paise) "
                    "VALUES (:i, 'hostel', 'flat', 10000, 0, 100000)"
                ),
                {"i": iid},
            )
            fines += 1
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings} fines+={fines}"
    )


def downgrade() -> None:
    """Data-only: grants, templates, fine rule and settings stay."""
