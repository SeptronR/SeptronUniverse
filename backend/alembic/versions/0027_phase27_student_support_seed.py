"""phase27 mentoring, grievances, discipline, surveys & clubs — data only (grants, settings, workflows, sequences,
notification templates, default committees)

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-26

Prompts/27 §27.2. The section 26 tables (``mentor_assignments`` … ``student_achievements``) and ``committees`` /
``committee_members`` already exist from ``0001`` — expected delta migration: none. This revision re-seeds role
templates and back-fills ``BACKFILL_GRANTS["0027"]``, adds the ``mentoring.*`` / ``risk.*`` / ``grievances.*`` /
``discipline.*`` / ``surveys.*`` / ``clubs.*`` settings, the ``discipline.case`` / ``discipline.appeal`` workflow
templates (``grievance.escalation`` ships with Phase 04), the ``grievance`` / ``disc_case`` number sequences, the
Phase 27 notification templates and one stub committee per type ``grievance | icc | anti_ragging | sc_st_cell |
obc_cell | discipline`` for every institution (members are added later; Phase 33 replaces the stub CRUD on the same
tables). Demo data: ``seed_demo_institution.py --only student_support``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMMITTEES = (
    ("grievance", "Grievance Redressal Cell"),
    ("icc", "Internal Complaints Committee"),
    ("anti_ragging", "Anti-Ragging Committee"),
    ("sc_st_cell", "SC/ST Cell"),
    ("obc_cell", "OBC Cell"),
    ("discipline", "Discipline Committee"),
)


def seed_committees(conn: object, institution_id: object) -> int:
    n = 0
    for ctype, name in COMMITTEES:
        exists = conn.execute(  # type: ignore[attr-defined]
            text("SELECT 1 FROM committees WHERE institution_id = :i AND committee_type = :t LIMIT 1"),
            {"i": institution_id, "t": ctype},
        ).first()
        if exists:
            continue
        conn.execute(  # type: ignore[attr-defined]
            text("INSERT INTO committees (institution_id, name, committee_type, is_active) VALUES (:i, :n, :t, TRUE)"),
            {"i": institution_id, "n": name, "t": ctype},
        )
        n += 1
    return n


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0027")
    platform = seed_phase04_platform(conn)
    workflows = settings = sequences = committees = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
        sequences += out["number_sequences"]
        committees += seed_committees(conn, iid)
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings} number_sequences+={sequences} committees+={committees}"
    )


def downgrade() -> None:
    """Data-only: grants, templates, settings, sequences and committees stay."""
