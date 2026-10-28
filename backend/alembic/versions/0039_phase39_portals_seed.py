"""phase39 portals, PWA, notification centre & guided help seed — data only (no tables)

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-28

Prompts/39 §39.2. ``platform_settings``: ``push.vapid`` placeholder (keys generated on first deploy by
``scripts/gen_vapid.py``, never committed), ``tours`` = the tour registry snapshot (``app/core/tours_snapshot.json``,
written by ``npm run tours:export``), ``mobile.app_ids`` (association files) — existing values are kept. The
``portals.*`` / ``notifications.*`` / ``i18n.*`` / ``pwa.*`` / ``tours.*`` settings come from the settings template
(defaults apply until a tenant saves one). Feature keys ``portals.faculty|evaluator|recruiter|pwa_push`` and
``i18n.web`` are registered; notification templates ``portal.welcome|push_enabled|test``,
``notifications.unread_digest``, ``tour.completed``; one platform help article per portal page (``help:/<persona>/…``).
Demo data: ``seed_demo_institution.py --only portals``. ``downgrade()`` removes the seeded articles and keys.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = ("push.vapid", "tours", "mobile.app_ids")


def _put(conn, key: str, value) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text("INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) ON CONFLICT (key) DO NOTHING"),
        {"k": key, "v": json.dumps(value)},
    )


def upgrade() -> None:
    from app.enums.portals import DEFAULT_APP_IDS
    from app.services.install_service import seed_features
    from app.services.institution_defaults import seed_phase04_platform
    from app.services.portals.help_seed import portal_articles

    conn = op.get_bind()
    features = seed_features(conn)
    _put(conn, "push.vapid", {"public_key": None, "subject": "mailto:support@septron.in", "generated_at": None})
    snapshot = Path(__file__).resolve().parents[2] / "app" / "core" / "tours_snapshot.json"
    tours = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.exists() else []
    conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('tours', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"v": json.dumps(tours)},
    )
    _put(conn, "mobile.app_ids", DEFAULT_APP_IDS)
    articles = 0
    for a in portal_articles():
        res = conn.execute(
            text(
                "INSERT INTO help_articles (institution_id, slug, title, body, module, audience, is_published) "
                "SELECT NULL, CAST(:slug AS varchar), :title, :body, :module, CAST(:aud AS jsonb), :pub "
                "WHERE NOT EXISTS (SELECT 1 FROM help_articles WHERE institution_id IS NULL AND slug = CAST(:slug AS varchar))"
            ),
            {
                "slug": a["slug"],
                "title": a["title"],
                "body": a["body"],
                "module": a["module"],
                "aud": json.dumps(a["audience"]),
                "pub": a["is_published"],
            },
        )
        articles += res.rowcount or 0
    platform = seed_phase04_platform(conn)
    print(  # noqa: T201 - alembic log
        f"  features={features} tours={len(tours)} help_articles+={articles} "
        f"notification_templates+={platform['notification_templates']}"
    )


def downgrade() -> None:
    from app.services.portals.help_seed import portal_articles

    conn = op.get_bind()
    conn.execute(
        text("DELETE FROM help_articles WHERE institution_id IS NULL AND slug = ANY(:s) AND title LIKE '% portal — %'"),
        {"s": [a["slug"] for a in portal_articles()]},
    )
    conn.execute(text("DELETE FROM platform_settings WHERE key = ANY(:k)"), {"k": list(KEYS)})
