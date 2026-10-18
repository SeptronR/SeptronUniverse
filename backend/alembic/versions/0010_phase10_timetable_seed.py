"""phase10 timetable — data only (grants, templates, settings, default slot group per college)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-16

Prompts/10 §10.2. The section 12 tables (``buildings`` … ``class_sessions``) and ``calendar_feed_tokens`` (§24)
already exist from ``0001`` — expected delta migration: none. This revision:

* re-seeds the platform role templates (registrar ``timetable:manage``; HOD create / update / publish / approve /
  substitute / export; estate officer ``timetable:update``; faculty ``timetable:substitute``) and back-fills them into
  the tenant system roles (``BACKFILL_GRANTS["0010"]``);
* adds the platform notification templates (timetable published, substitution requested / approved / rejected,
  session created / cancelled / rescheduled), the ``timetable.substitution`` workflow template (HOD) and the
  ``timetable.*`` settings rows (``default_slot_group`` P1–P8 with a break and lunch, ``mark_missed_sessions``);
* seeds the ``Default`` slot group into every college that has no time slots yet, from the settings template.

Demo data: ``seed_demo_institution.py --only timetable``. ``downgrade()`` leaves the rows.
"""

from collections.abc import Sequence
from datetime import time

from sqlalchemy import text

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def seed_default_slots(conn: object) -> int:
    from app.core.settings_template import SETTINGS_TEMPLATE

    default = next(d.default for d in SETTINGS_TEMPLATE if d.full_key == "timetable.default_slot_group")
    created = 0
    rows = conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT c.institution_id, c.id FROM colleges c WHERE c.deleted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM time_slots t WHERE t.college_id = c.id)"
        )
    ).all()
    for iid, cid in rows:
        for seq, slot in enumerate(default, start=1):
            conn.execute(  # type: ignore[attr-defined]
                text(
                    "INSERT INTO time_slots (institution_id, college_id, slot_group, name, sequence, start_time, "
                    "end_time, slot_type) VALUES (CAST(:i AS uuid), CAST(:c AS uuid), 'Default', :n, :s, "
                    ":st, :et, :t) ON CONFLICT DO NOTHING"
                ),
                {
                    "i": str(iid),
                    "c": str(cid),
                    "n": slot["name"],
                    "s": seq,
                    "st": time.fromisoformat(slot["start_time"]),
                    "et": time.fromisoformat(slot["end_time"]),
                    "t": slot["slot_type"],
                },
            )
            created += 1
    return created


def upgrade() -> None:
    from app.services.install_service import seed_role_templates
    from app.services.institution_defaults import (
        backfill_role_grants,
        seed_institution_defaults,
        seed_phase04_platform,
    )

    conn = op.get_bind()
    _, grants = seed_role_templates(conn)
    backfilled = backfill_role_grants(conn, "0010")
    platform = seed_phase04_platform(conn)
    workflows = settings = 0
    for iid, pack in conn.execute(text("SELECT id, regulatory_pack FROM institutions WHERE deleted_at IS NULL")).all():
        out = seed_institution_defaults(conn, iid, pack)
        workflows += out["workflow_definitions"]
        settings += out["settings"]
    slots = seed_default_slots(conn)
    print(  # noqa: T201 - alembic log
        f"  seeded: template_grants+={grants} tenant_grants+={backfilled} "
        f"notification_templates+={platform['notification_templates']} "
        f"workflow_definitions+={workflows} settings+={settings} time_slots+={slots}"
    )


def downgrade() -> None:
    """Data-only: grants, templates, settings and slots stay."""
