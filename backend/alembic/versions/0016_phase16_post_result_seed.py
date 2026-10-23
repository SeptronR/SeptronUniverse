"""phase16 post-result — data only (grants, malpractice scale, transcript template, notification / workflow templates)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-22

Prompts/16 §16.2. ``reval_requests`` / ``malpractice_cases`` / ``transcripts`` (and ``committees``,
``committee_members``, ``student_achievements`` used here) already exist from ``0001`` — expected delta migration: none.
This revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0016"]`` (registrar ``exams:view_all`` +
  ``results:approve``; discipline committee / committee secretary ``exams:view`` — committee cases only);
* stores the IN-pack malpractice punishment scale (warning / cancel paper / cancel session / debar 1–4 terms / expel)
  under ``platform_settings['malpractice_scale']`` and the platform default transcript template under
  ``platform_settings['transcript_template']`` (Phase 26 moves it into ``document_templates``);
* adds the notification templates ``results.reval_decided``, ``results.malpractice_notice``,
  ``results.transcript_ready``, the workflow templates ``transcripts.issue``, ``students.readmission`` and
  ``malpractice.appeal`` (32 templates) to every tenant, and the new ``exams.*`` settings (appeal window, transcript
  fees, public rank lists).

Demo data: ``seed_demo_institution.py --only post_result``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSCRIPT_TEMPLATE = {
    "type": "transcript",
    "version": 1,
    "languages": ["en", "hi"],
    "variants": {
        "provisional": "PROVISIONAL TRANSCRIPT",
        "consolidated": "CONSOLIDATED TRANSCRIPT",
        "final": "TRANSCRIPT OF RECORDS",
        "duplicate": "TRANSCRIPT (DUPLICATE)",
        "migration": "TRANSCRIPT (MIGRATION)",
    },
    "columns": ["code", "title", "credits", "grade", "grade_point"],
    "per_term": ["sgpa", "credits_earned"],
    "footer": ["cgpa", "credits", "class", "verification_qr"],
    "qr": True,
}


def upgrade() -> None:
    from app.enums.post_result import MALPRACTICE_SCALE
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        _put_platform_setting,
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0016")
    platform = seed_phase04_platform(conn)
    _put_platform_setting(conn, "malpractice_scale", {"pack": "IN", "scale": MALPRACTICE_SCALE})
    _put_platform_setting(conn, "transcript_template", TRANSCRIPT_TEMPLATE)
    workflows = settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings}"
    )


def downgrade() -> None:
    """Data-only: grants, templates and settings stay."""
