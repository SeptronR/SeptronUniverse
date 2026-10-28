"""phase42 flutter mobile app seed — data only

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-28

Prompts/42 §42.2. ``platform_settings['mobile']`` gains the app-engine keys (write queue limits, biometric timeout,
screenshot-blocked routes) merged into whatever the operator stored; ``platform_settings['push.topics']`` is the
topic registry the app subscribes to. Feature keys ``mobile.*``. Demo data: ``seed_demo_institution.py --only mobile``.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOBILE = {
    "min_versions": {"android": "1.0.0", "ios": "1.0.0"},
    "force_update_below": {"android": "0.0.0", "ios": "0.0.0"},
    "maintenance_banner": None,
    "feature_hints": {},
    "cache_ttl": 300,
    "write_queue": {"max_items": 5000, "max_age_hours": 72, "flush_batch": 50},
    "biometric_timeout_minutes": 5,
    "screenshot_block_routes": ["marks", "valuation", "pii"],
}
TOPICS = ["role:{slug}", "college:{id}", "department:{id}", "batch:{id}", "hostel:{id}", "institution:{id}"]


def upgrade() -> None:
    from app.services.install_service import seed_features

    conn = op.get_bind()
    features = seed_features(conn)
    # stored keys win over the defaults (an operator may already have set store URLs / versions)
    conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('mobile', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = CAST(:v AS jsonb) || platform_settings.value, updated_at = NOW()"
        ),
        {"v": json.dumps(MOBILE)},
    )
    conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('push.topics', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"v": json.dumps(TOPICS)},
    )
    print(f"  features={features}")  # noqa: T201


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM platform_settings WHERE key = 'push.topics'"))
