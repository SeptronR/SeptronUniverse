"""institution_settings unique key NULLS NOT DISTINCT (QA-015)

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-01

``UNIQUE (institution_id, college_id, category, key)`` treated institution-wide rows (``college_id IS NULL``) as
distinct, so every ``INSERT … ON CONFLICT (institution_id, college_id, category, key) DO UPDATE`` (website meta,
integrations, imports, webhooks, hardening) inserted a duplicate instead of updating, and readers picked an arbitrary
copy (``40_website.ps1``: a publish never showed up in ``/website/config/versions``). Keep the newest row of each
duplicate group, then rebuild the constraint as ``NULLS NOT DISTINCT`` (PostgreSQL 15+) so the existing upserts work.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "institution_settings_institution_id_college_id_category_key_key"


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM institution_settings s USING (
            SELECT id, row_number() OVER (
                PARTITION BY institution_id, college_id, category, key ORDER BY updated_at DESC, created_at DESC, id
            ) AS rn
            FROM institution_settings
        ) d
        WHERE s.id = d.id AND d.rn > 1
        """
    )
    op.execute(f"ALTER TABLE institution_settings DROP CONSTRAINT {NAME}")
    op.execute(
        f"ALTER TABLE institution_settings ADD CONSTRAINT {NAME} "
        "UNIQUE NULLS NOT DISTINCT (institution_id, college_id, category, key)"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE institution_settings DROP CONSTRAINT {NAME}")
    op.execute(f"ALTER TABLE institution_settings ADD CONSTRAINT {NAME} UNIQUE (institution_id, college_id, category, key)")
