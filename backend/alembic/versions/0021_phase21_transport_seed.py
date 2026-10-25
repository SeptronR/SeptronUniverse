"""phase21 transport — data only (grants, settings, notification templates, trip sequence, GPS partitions)

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-24

Prompts/21 §21.2. The section 20 transport tables (with ``vehicle_gps_logs`` range-partitioned on ``recorded_at`` and
its DEFAULT partition) already exist from ``0001`` — expected delta migration: none. This revision:

* re-seeds the role templates and back-fills ``BACKFILL_GRANTS["0021"]`` (HOD ``transport:view_all`` — department;
  staff passengers ``transport:view``);
* adds the ``transport.*`` settings (trip schedule, GPS ping interval, ETA alert minutes, expiry alert days, hard
  capacity limit, …), the transport notification templates and the ``trip`` number sequence to every tenant;
* creates this and next month's ``vehicle_gps_logs_yYYYYmMM`` partitions (Beat keeps creating them monthly).

Demo data: ``seed_demo_institution.py --only transport``. ``downgrade()`` leaves the rows (and partitions).
"""

from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import text

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import backfill_role_grants, seed_institution_defaults, seed_phase04_platform

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0021")
    platform = seed_phase04_platform(conn)
    settings = sequences = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        settings += out["settings"]
        sequences += out.get("number_sequences", 0)
    partitions = 0
    first = date.today().replace(day=1)
    for m in (first, (first + timedelta(days=32)).replace(day=1)):
        nxt = (m + timedelta(days=32)).replace(day=1)
        name = f"vehicle_gps_logs_y{m.year}m{m.month:02d}"
        if conn.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar() is None:
            conn.execute(
                text(
                    f"CREATE TABLE {name} PARTITION OF vehicle_gps_logs "  # noqa: S608 - generated name
                    f"FOR VALUES FROM ('{m.isoformat()}') TO ('{nxt.isoformat()}')"
                )
            )
            partitions += 1
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} settings+={settings} "
        f"sequences+={sequences} gps_partitions+={partitions}"
    )


def downgrade() -> None:
    """Data-only: grants, templates, settings, sequences and partitions stay."""
