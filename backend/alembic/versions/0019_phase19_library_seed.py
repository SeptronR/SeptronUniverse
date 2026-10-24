"""phase19 library — data only (grants, DDC categories, member rules, number sequences, notification templates, settings)

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-24

Prompts/19 §19.2. The section 18 library tables already exist from ``0001`` — expected delta migration: none. This
revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0019"]`` (parents ``library:self`` — wards; HOD
  ``library:view_all`` — department);
* inserts the Dewey top classes as ``book_categories`` and the default member rules (student 3 / 14 days, faculty
  10 / 30, scholar 6 / 30, staff 3 / 14, alumni 2 / 14 + deposit, external 1 / 7) into ``institution_settings``
  (``library.member_rules``) for every tenant that has none;
* makes sure ``fine_configurations(applies_to='library_overdue')`` exists (₹2 / day, no grace, ₹500 cap — Phase 12 seeds
  it for new tenants);
* adds the number sequences ``lib:acc`` (``ACC{seq:6}``) and ``lib:member`` (``LM{yy}{seq:5}``) — and the Phase 18
  ``degree`` / ``degree_serial`` patterns — through ``seed_institution_defaults``, the notification templates
  ``library.issued``, ``library.overdue``, ``library.reservation_available``, ``library.fine_created``,
  ``library.eresource_expiring`` (``library.due_reminder`` exists) and the ``library.*`` settings.

Demo data: ``seed_demo_institution.py --only library``. ``downgrade()`` leaves the rows.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.enums.library import DDC_CLASSES, MEMBER_RULES
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0019")
    platform = seed_phase04_platform(conn)
    cats = settings = fines = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
        for code, name in DDC_CLASSES:
            cats += conn.execute(
                text(
                    "INSERT INTO book_categories (institution_id, name, ddc_code) VALUES (:i, :n, :c) "
                    "ON CONFLICT (institution_id, name) DO NOTHING"
                ),
                {"i": iid, "n": name, "c": code},
            ).rowcount
        if not conn.execute(
            text(
                "SELECT 1 FROM institution_settings WHERE institution_id = :i AND college_id IS NULL AND category = 'library' AND key = 'member_rules'"
            ),
            {"i": iid},
        ).first():
            conn.execute(
                text(
                    "INSERT INTO institution_settings (institution_id, category, key, value, value_type) "
                    "VALUES (:i, 'library', 'member_rules', CAST(:v AS jsonb), 'json')"
                ),
                {"i": iid, "v": json.dumps(MEMBER_RULES)},
            )
        if not conn.execute(
            text("SELECT 1 FROM fine_configurations WHERE institution_id = :i AND applies_to = 'library_overdue'"),
            {"i": iid},
        ).first():
            conn.execute(
                text(
                    "INSERT INTO fine_configurations (institution_id, applies_to, calc_type, amount_paise, grace_days, max_paise) "
                    "VALUES (:i, 'library_overdue', 'per_day', 200, 0, 50000)"
                ),
                {"i": iid},
            )
            fines += 1
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings} categories+={cats} fines+={fines}"
    )


def downgrade() -> None:
    """Data-only: grants, categories, rules, sequences and templates stay."""
