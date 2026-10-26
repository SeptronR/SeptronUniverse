"""phase33 governance — data only (statutory committees, grants, workflows, settings, sequences, document and
notification templates)

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-26

Prompts/33 §33.2. The section 30 tables (``committees`` … ``policies``) already exist from ``0001`` and Phases 16 / 27 /
30 / 31 / 32 created committee rows through the stub — expected delta migration: none; stub rows are left unchanged.
This revision adds the statutory committees of the institution type that are still missing (university: Academic
Council, Executive Council, Senate / Court, Finance, Research Board, IQAC, Anti-ragging, ICC, Grievance, Purchase,
Discipline; college: Governing Body, Academic Committee, IQAC, Anti-ragging, ICC, Grievance, Purchase, Discipline —
Boards of Studies are constituted per department from the template wizard) with their default ``quorum_rule``
(``{type: fraction, value: "1/2"}`` plus the resolution numbering ``code``), re-seeds role templates (new bespoke
actions ``governance:policies`` / ``governance:audit_paras``; staff ``governance:view`` + ``efile:create|view``, students
``governance:view``, registrar governance manage / legal / RTI readers / RTI appellate / e-file admin, principal
``governance:approve`` + ``efile:approve``, accountant ``governance:audit_paras``) and back-fills
``BACKFILL_GRANTS["0033"]``; adds the ``governance.* / rti.* / efile.* / legal.* / policies.*`` settings, the ``rti`` /
``efile`` / ``legal`` number sequences (resolutions are numbered ``<CODE>/<yyyy>/<n>`` under a committee row lock), the
workflows ``governance.minutes_approval`` / ``governance.policy_approval`` / ``efile.approval`` (53 templates), the
platform document templates ``meeting_notice`` / ``minutes`` / ``resolution_extract`` / ``rti_response`` /
``office_order`` and the Phase 33 notification templates. Demo data: ``seed_demo_institution.py --only governance``.
``downgrade()`` leaves the rows.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def seed_committees(conn: object, institution_id: object, institution_type: str | None) -> int:
    from app.enums.governance import committee_templates

    n = 0
    for key, name, ctype, code, quorum, per_dept in committee_templates(institution_type):
        if per_dept:
            continue
        exists = conn.execute(  # type: ignore[attr-defined]
            text("SELECT 1 FROM committees WHERE institution_id = :i AND committee_type = :t LIMIT 1"),
            {"i": institution_id, "t": ctype},
        ).first()
        if exists:
            continue
        conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO committees (institution_id, name, committee_type, quorum_rule, is_active) "
                "VALUES (:i, :n, :t, CAST(:q AS JSONB), TRUE)"
            ),
            {
                "i": institution_id,
                "n": name,
                "t": ctype,
                "q": json.dumps({**quorum, "code": code, "template_key": key}),
            },
        )
        n += 1
    return n


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        backfill_role_grants,
        seed_document_templates,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0033")
    platform = seed_phase04_platform(conn)
    templates = seed_document_templates(conn)
    settings = workflows = sequences = committees = 0
    for iid, pack, itype in conn.execute(
        text("SELECT id, regulatory_pack, institution_type FROM institutions WHERE deleted_at IS NULL")
    ).all():
        out = seed_institution_defaults(conn, iid, pack)
        settings += out["settings"]
        workflows += out.get("workflow_definitions", 0)
        sequences += out.get("number_sequences", 0)
        committees += seed_committees(conn, iid, itype)
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} document_templates+={templates} "
        f"workflow_definitions+={workflows} settings+={settings} number_sequences+={sequences} committees+={committees}"
    )


def downgrade() -> None:
    """Data-only: committees, grants, templates, settings, sequences and workflows stay."""
