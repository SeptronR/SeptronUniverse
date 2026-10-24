"""phase22 inventory — data only (vendor / store-keeper roles, grants, procurement.bill workflow, categories, settings)

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-24

Prompts/22 §22.2. The section 21 tables already exist from ``0001`` — expected delta migration: none. This revision:

* re-seeds the role templates — now 53 with ``vendor`` (portal: ``procurement:quote``, ``inventory:view``) and
  ``store_keeper`` (``inventory:receive|issue|indent|view``; stores owned through ``stores.keeper_staff_id``) — clones
  the two new roles into every tenant and back-fills ``BACKFILL_GRANTS["0022"]`` (inventory manager receive / issue /
  audit, accountant + vice-chancellor PO / bill approval);
* adds the workflow template ``procurement.bill`` (accountant → vice-chancellor, above
  ``inventory.bill_approval_threshold_paise``) — 36 templates;
* inserts the default ``inventory_categories`` (stationery, lab consumables, chemicals, IT hardware, furniture,
  electrical, cleaning, sports, library) per tenant;
* adds the ``inventory.*`` settings, the ``indent`` / ``po`` / ``grn`` / ``asset`` / ``item`` number sequences and the
  inventory / vendor notification templates.

Demo data: ``seed_demo_institution.py --only inventory``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.enums.inventory import DEFAULT_CATEGORIES
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    platform = seed_phase04_platform(conn)
    roles = cats = workflows = settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        for slug in ("vendor", "store_keeper"):
            # clone the template role (and its grants) into the tenant
            tpl = conn.execute(
                text(
                    "SELECT id, name, description, default_scope_type, portal FROM roles WHERE institution_id IS NULL AND slug = :s"
                ),
                {"s": slug},
            ).first()
            if (
                tpl is None
                or conn.execute(
                    text("SELECT 1 FROM roles WHERE institution_id = :i AND slug = :s"), {"i": iid, "s": slug}
                ).first()
            ):
                continue
            rid = conn.execute(
                text(
                    "INSERT INTO roles (institution_id, name, slug, description, is_system, default_scope_type, portal) "
                    "VALUES (:i, :n, :s, :d, TRUE, :sc, :p) RETURNING id"
                ),
                {
                    "i": iid,
                    "n": tpl.name,
                    "s": slug,
                    "d": tpl.description,
                    "sc": tpl.default_scope_type,
                    "p": tpl.portal,
                },
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id) SELECT :r, permission_id FROM role_permissions WHERE role_id = :t ON CONFLICT DO NOTHING"
                ),
                {"r": rid, "t": tpl.id},
            )
            roles += 1
        for name, consumable in DEFAULT_CATEGORIES:
            res = conn.execute(
                text(
                    "INSERT INTO inventory_categories (institution_id, name, is_consumable) VALUES (:i, :n, :c) "
                    "ON CONFLICT (institution_id, name) DO NOTHING"
                ),
                {"i": iid, "n": name, "c": consumable},
            )
            cats += res.rowcount or 0
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
    backfilled = backfill_role_grants(conn, "0022")
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_roles+={roles} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} workflow_definitions+={workflows} "
        f"settings+={settings} categories+={cats}"
    )


def downgrade() -> None:
    """Data-only: roles, grants, templates, categories and settings stay."""
