"""phase03 institution structure — data only (settings template, theme tokens, number-sequence patterns)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27

Prompts/03 §03.2. Sections 2 (tenancy) and 7 (``academic_years`` / ``academic_terms``) already exist from ``0001`` —
expected delta migration: none. This revision stores the Phase 03 templates in ``platform_settings``
(``settings_template``, ``theme_tokens``, ``theme_default``, ``number_sequence_template``) from
``app/core/settings_template.py``, re-runs the idempotent registry seed (the role templates gained
``institutions:view`` — Phase 03 visibility rule) and backfills that grant into the system roles already cloned into
tenants. Per-institution rows are written by ``seed_institution_defaults(pack)`` (onboarding / demo seeder), not here.

``downgrade()`` removes the four ``platform_settings`` keys; grants stay (tenant rows reference them).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = ("settings_template", "theme_tokens", "theme_default", "number_sequence_template")


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_phase03_platform

    conn = op.get_bind()
    counts = seed_phase03_platform(conn)
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0003")
    print(  # noqa: T201 - migration output belongs in the alembic log
        f"  seeded: settings_keys={counts['settings_keys']} themes={counts['themes']} "
        f"sequence_patterns={counts['sequence_patterns']} template_grants+={grants} tenant_grants+={backfilled}"
    )


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM platform_settings WHERE key = ANY(:k)"), {"k": list(KEYS)})
