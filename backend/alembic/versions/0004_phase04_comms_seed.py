"""phase04 communication core & workflow engine — data only (platform notification templates, workflow templates)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27

Prompts/04 §04.2. Section 23 (communication) and the section 6 workflow tables already exist from ``0001`` — expected
delta migration: none. This revision seeds the platform ``notification_templates`` (``institution_id`` NULL) for the
event catalogue (``app/core/notifications/catalogue.py``; en + hi where the IN pack supplies a body), stores the 18
shipped workflow templates in ``platform_settings['workflow_templates']`` and copies them into the
``workflow_definitions`` of every existing institution (new institutions get them from
``seed_institution_defaults``).

``downgrade()`` removes the platform templates that no tenant row references and the platform setting; tenant
workflow definitions stay (instances reference them).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.institution_defaults import seed_phase04_platform, seed_workflow_definitions

    conn = op.get_bind()
    counts = seed_phase04_platform(conn)
    definitions = 0
    for (iid,) in conn.execute(text("SELECT id FROM institutions WHERE deleted_at IS NULL")).all():
        definitions += seed_workflow_definitions(conn, iid)
    print(  # noqa: T201 - migration output belongs in the alembic log
        f"  seeded: notification_templates+={counts['notification_templates']} "
        f"workflow_templates={counts['workflow_templates']} tenant workflow_definitions+={definitions}"
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DELETE FROM notification_templates WHERE institution_id IS NULL"))
    conn.execute(text("DELETE FROM platform_settings WHERE key = 'workflow_templates'"))
