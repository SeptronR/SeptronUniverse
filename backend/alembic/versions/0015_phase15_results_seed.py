"""phase15 results — data only (grants, grade-card / tabulation templates, result notifications, settings)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-19

Prompts/15 §15.2. The section 15 / 16 tables, the ``answer_scripts_for_evaluation`` view and the
``trg_results_immutable`` / ``trg_term_results_immutable`` triggers already exist from ``0001`` — expected delta
migration: none. This revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0015"]`` (HOD ``results:view_all`` — department
  results, run rows after verification);
* stores the platform default grade-card template (bilingual labels) and the tabulation-register layout under
  ``platform_settings['grade_card_template']`` / ``['tabulation_template']`` (Phase 26 moves them into
  ``document_templates``), and the valuation remuneration defaults (paise per script per round);
* adds the result notification templates (``results.published`` — masked SMS with the SGPA only, push, e-mail —
  ``valuation.assigned``, ``valuation.due_reminder``) and the new ``exams.*`` setting rows (bundle size, teacher
  evaluation, script retention, valuation remuneration).

Demo data: ``seed_demo_institution.py --only results``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRADE_CARD_TEMPLATE = {
    "type": "grade_card",
    "version": 1,
    "languages": ["en", "hi"],
    "labels": {
        "title": {"en": "Grade Card", "hi": "ग्रेड कार्ड"},
        "sgpa": {"en": "SGPA", "hi": "एसजीपीए"},
        "cgpa": {"en": "CGPA", "hi": "सीजीपीए"},
        "credits": {"en": "Credits", "hi": "क्रेडिट"},
        "grace_note": {"en": "* grace marks awarded as per regulation", "hi": "* विनियम के अनुसार अनुग्रह अंक"},
    },
    "columns": ["code", "title", "credits", "grade", "grade_point"],
    "special_grades": {"W": "Withdrawn", "AB": "Absent", "WH": "Withheld", "MP": "Malpractice", "I": "Incomplete"},
    "qr": True,
}
TABULATION_TEMPLATE = {
    "type": "tabulation_register",
    "version": 1,
    "columns": [
        "registration_number",
        "student_name",
        "<course grades>",
        "sgpa",
        "cgpa",
        "credits",
        "backlogs",
        "class",
    ],
}


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        _put_platform_setting,
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )
    from app.tasks.results import DEFAULT_PER_SCRIPT

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0015")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "grade_card_template", GRADE_CARD_TEMPLATE)
    _put_platform_setting(conn, "tabulation_template", TABULATION_TEMPLATE)
    _put_platform_setting(conn, "valuation_remuneration", DEFAULT_PER_SCRIPT)
    settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        settings += seed_institution_defaults(conn, iid, pack)["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay."""
