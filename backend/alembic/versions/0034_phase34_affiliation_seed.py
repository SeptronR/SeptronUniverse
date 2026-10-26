"""phase34 affiliation — data only (grants, settings, sequences, workflow variants, fee schedule templates, document /
notification templates, published metric definitions)

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-26

Prompts/34 §34.2. The section 31 tables (``affiliation_applications``, ``affiliation_program_approvals``,
``affiliation_fee_schedules``, ``college_data_submissions``, ``exam_centres``) exist from ``0001`` (Phase 13 / 14 wrote
``college_data_submissions`` / ``exam_centres`` rows through their stubs; the rows are used unchanged) — expected delta
migration: none. This revision re-seeds role templates (registrar ``affiliation:manage|verify_submission|view_all``, VC
``affiliation:decide|view_all``, COE ``affiliation:verify_submission|view_all`` + ``exams:configure``, college admin
``affiliation:apply|submit|view``, faculty / HOD / dean ``affiliation:inspect``, accountant ``affiliation:view``) and
back-fills ``BACKFILL_GRANTS["0034"]``; adds the ``affiliation.*`` settings (checklists per type, inspection age,
deficiency compliance days, order validity, submission windows / validation rules / result-gating types, centre
buffer, expiry reminder), the ``affil`` / ``order`` sequences, the workflow ``affiliation.submission_review`` (54
templates) and **version 2** of ``affiliation.application`` (registrar → inspection convenor ``skip_unless
inspection_required`` → Academic / Executive Council secretaries ``skip_unless council_required`` → VC) for tenants
that hold the Phase 04 version only; ``affiliation_fee_schedules`` template rows for the current academic year of
university tenants; platform document templates ``affiliation_order`` / ``inspection_report`` / ``deficiency_notice``
/ ``centre_appointment``; the Phase 34 notification templates; the published affiliation metric definitions (Phase 32
catalogue). Demo data: ``seed_demo_institution.py --type university --only affiliation``. ``downgrade()`` leaves the rows.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def seed_application_v2(conn: object, institution_id: object) -> int:
    from app.core.workflow.templates import AFFILIATION_APPLICATION_STEPS

    rows = conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT id, version, steps FROM workflow_definitions WHERE institution_id = :i "
            "AND key = 'affiliation.application' ORDER BY version DESC"
        ),
        {"i": institution_id},
    ).all()
    if not rows:
        return 0
    _, version, steps = rows[0]
    if (steps or []) == AFFILIATION_APPLICATION_STEPS:
        return 0
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO workflow_definitions (institution_id, module, key, name, description, steps, version, is_active) "
            "VALUES (:i, 'affiliation', 'affiliation.application', 'Affiliation application', :d, CAST(:s AS jsonb), :v, TRUE)"
        ),
        {
            "i": institution_id,
            "d": "Phase 34 type variants: inspection / council steps by context",
            "s": json.dumps(AFFILIATION_APPLICATION_STEPS),
            "v": int(version) + 1,
        },
    )
    return 1


def seed_fee_schedules(conn: object, institution_id: object) -> int:
    from app.enums.affiliation import FEE_SCHEDULE_TEMPLATE

    year = conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT id FROM academic_years WHERE institution_id = :i ORDER BY is_current DESC, start_date DESC LIMIT 1"
        ),
        {"i": institution_id},
    ).first()
    if year is None:
        return 0
    n = 0
    for fee_type, amount, per_unit in FEE_SCHEDULE_TEMPLATE:
        res = conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO affiliation_fee_schedules (institution_id, academic_year_id, fee_type, amount_paise, per_unit) "
                "VALUES (:i, :y, :t, :a, :u) ON CONFLICT (academic_year_id, fee_type) DO NOTHING"
            ),
            {"i": institution_id, "y": year[0], "t": fee_type, "a": amount, "u": per_unit},
        )
        n += res.rowcount or 0
    return n


def upgrade() -> None:
    from app.services.accreditation.catalogue import seed_accreditation_catalogue
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        backfill_role_grants,
        seed_document_templates,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    defs, _ = seed_accreditation_catalogue(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0034")
    platform = seed_phase04_platform(conn)
    templates = seed_document_templates(conn)
    settings = workflows = sequences = versions = fees = 0
    for iid, pack, itype in conn.execute(
        text("SELECT id, regulatory_pack, institution_type FROM institutions WHERE deleted_at IS NULL")
    ).all():
        out = seed_institution_defaults(conn, iid, pack)
        settings += out["settings"]
        workflows += out.get("workflow_definitions", 0)
        sequences += out.get("number_sequences", 0)
        versions += seed_application_v2(conn, iid)
        if itype == "university":
            fees += seed_fee_schedules(conn, iid)
    print(  # noqa: T201 - alembic log
        f"  seeded: metric_definitions+={defs} template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} document_templates+={templates} "
        f"workflow_definitions+={workflows} affiliation.application v2+={versions} settings+={settings} "
        f"number_sequences+={sequences} fee_schedules+={fees}"
    )


def downgrade() -> None:
    """Data-only: grants, templates, settings, sequences, workflows and fee schedules stay."""
