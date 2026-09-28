"""phase05 programmes, regulations & curriculum — role grants (+ Phase 04 fix: no bump_version on workflow_definitions)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28

Prompts/05 §05.2. The section 7 tables (``grading_scales`` … ``batch_sections``) already exist from ``0001`` —
expected delta migration: none, and no academic rows (pack grading scales were copied at onboarding; assessment
schemes are copied from the pack when a regulation is created). This revision re-runs the idempotent registry seed —
the role templates gained the Phase 05 grants (``programs|regulations|curriculum|courses|batches:view`` for every
staff role, the registrar's academic management, ``hod`` @department course/curriculum/batch drafting, ``dean``
``courses:approve``) — and back-fills them into the system roles already cloned into tenants
(``BACKFILL_GRANTS["0005"]``). Demo data: ``seed_demo_institution.py --only academics``.

Phase 04 fix found by the first live ``04_comms_workflow.ps1`` run: ``workflow_definitions.version`` is the
definition version (immutable rows, ``UNIQUE (institution_id, key, version)``), but the canonical DDL attached the
optimistic-lock trigger ``bump_version`` to the table — deactivating version *n* renumbered it to *n+1* and the new
version collided (409). The trigger is dropped here and removed from ``Database_Schema.sql``.

``downgrade()`` restores the trigger; grants stay (tenant rows reference them, and an administrator may rely on them).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants

    conn = op.get_bind()
    op.execute("DROP TRIGGER IF EXISTS bump_version ON workflow_definitions")
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0005")
    print(f"  seeded: template_grants+={grants} tenant_grants+={backfilled}")  # noqa: T201 - alembic log


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS bump_version ON workflow_definitions")
    op.execute(
        "CREATE TRIGGER bump_version BEFORE UPDATE ON workflow_definitions FOR EACH ROW "
        "WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION trigger_bump_version()"
    )
