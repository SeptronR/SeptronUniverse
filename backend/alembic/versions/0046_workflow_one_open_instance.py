"""workflow_instances: one OPEN instance per record (partial unique index)

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-01

``UNIQUE (entity_type, entity_id, definition_id)`` allowed one instance per record forever, while the engine
(``WorkflowEngine.start``) deliberately lets a closed (approved / rejected / cancelled) instance be followed by a new
one (Phase 09 resubmission). Any restart therefore failed with a unique violation — e.g. ``substitution.auto_request``
on a second ``leave.approved`` for a class whose earlier substitution was withdrawn, leaving the event pending
(``06_hr.ps1``). Keep the guarantee where it matters: at most one ``pending`` / ``escalated`` instance per record.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "workflow_instances_entity_type_entity_id_definition_id_key"
NEW = "workflow_instances_one_open"


def upgrade() -> None:
    # IF [NOT] EXISTS: a fresh database gets Database_Schema.sql (revision 0001) in its current shape, which already has
    # the partial index and no longer has the old constraint
    op.execute(f"ALTER TABLE workflow_instances DROP CONSTRAINT IF EXISTS {OLD}")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {NEW} ON workflow_instances (entity_type, entity_id, definition_id) "
        "WHERE status IN ('pending', 'escalated')"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX {NEW}")
    op.execute(f"ALTER TABLE workflow_instances ADD CONSTRAINT {OLD} UNIQUE (entity_type, entity_id, definition_id)")
