"""phase02 auth/rbac/features seed — data only (no schema delta)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22

Prompts/02 §02.2: upserts the permission catalogue (``app/core/rbac/registry.py`` — the same 916 rows as
``Database_Schema.sql`` §36.1), the 51 role templates **with their default grants** (docs/Roles_and_Permissions.md §3),
``platform_features`` from ``FEATURE_REGISTRY`` ∪ ``docs/Feature_Flags.md`` and the four subscription plans with their
per-tier ``enabled_features``. Every statement is idempotent (``ON CONFLICT DO NOTHING / DO UPDATE``), so the revision
is safe to re-run after the registries grow. The shared implementation lives in
``app/services/install_service.py`` (also used by ``scripts/seed_platform.py`` and ``POST /install``).

``downgrade()`` is a no-op: the seed rows are referenced by ``role_permissions`` / ``institution_feature_flags`` and
deleting them would cascade into tenant data.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_registries

    counts = seed_registries(op.get_bind())
    print(  # noqa: T201 - migration output belongs in the alembic log
        f"  seeded: permissions={counts['permissions']} role_templates+={counts['role_templates_created']} "
        f"grants+={counts['role_template_grants_added']} features={counts['features']} plans={counts['plans']}"
    )


def downgrade() -> None:
    """Data-only revision: the registries stay (tenant rows reference them)."""
