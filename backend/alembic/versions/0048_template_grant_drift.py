"""tenant system roles catch up with their templates — data only

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-05

Earlier ``BACKFILL_GRANTS`` entries left out five template grants, so tenants created before those phases lacked them
while new tenants had them (HOD audit department tab empty, ``37_audit_settings.ps1``): ``audit_logs:view_all``,
``audit_logs:verify_chain``, ``support:view_all``, ``facilities:counsel``, ``settings:manage``. Only roles whose
template carries a grant receive it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.institution_defaults import backfill_role_grants

    print(f"  tenant_grants+={backfill_role_grants(op.get_bind(), '0048')}")  # noqa: T201 - alembic log


def downgrade() -> None:
    pass  # grants stay: removing them would also strip any an administrator added by hand
