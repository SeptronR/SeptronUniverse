"""exam_cell regains exams:moderate — data only

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-01

Phase 15 has the exam cell propose moderation (``exams:moderate``) and the COE approve it. The grant only ever reached
``exam_cell`` through ``ALL()``, which Phase 43 narrowed, so ``POST /exam-papers/{id}/moderation`` answered 403
(``15_results.ps1``). The template now lists it explicitly; ``BACKFILL_GRANTS["0047"]`` adds it to tenant roles.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0047")
    print(f"  template_grants+={grants} tenant_grants+={backfilled}")  # noqa: T201 - alembic log


def downgrade() -> None:
    pass  # grants stay: removing them would also strip any an administrator added by hand
