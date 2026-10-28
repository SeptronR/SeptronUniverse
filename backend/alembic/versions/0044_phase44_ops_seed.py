"""phase44 deployment, CI/CD & operations seed — data only

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-28

Prompts/44 §44.2. ``platform_settings['ops']`` (environments, deploy strategy, backups, DR targets, alert channels,
status-page components, capacity, release policy) and ``features.env_defaults`` (demo: every feature on with sandbox
providers; production: registry defaults). Grafana dashboards / alert rules are files under ``ops/``. Notification
templates ``ops.*``. Demo data: ``seed_demo_institution.py --only ops``.
"""

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPS = {
    "environments": {
        "dev": {"url": "https://dev.septronuniverse.in", "auto_deploy": "develop"},
        "demo": {"url": "https://demo.septronuniverse.in", "auto_deploy": "main", "nightly_reset": True},
        "staging": {"url": "https://staging.septronuniverse.in", "auto_deploy": "release/*"},
        "prod": {"url": "https://app.septronuniverse.in", "approval": "required"},
    },
    "deploy": {
        "strategy": "rolling",
        "readiness_timeout_s": 120,
        "max_unavailable": 0,
        "readonly_window_for_risky_migrations": True,
    },
    "backups": {
        "tool": "pgbackrest",
        "schedule_full": "0 1 * * 0",
        "schedule_incr": "0 */6 * * *",
        "wal_archive": True,
        "retention_daily": 30,
        "retention_monthly": 12,
        "encryption": "aes-256",
        "bucket": "universe-backups",
        "region": "ap-south-1",
        "uploads_versioning": True,
        "restore_drill_cron": "0 3 1 */3 *",
    },
    "dr_targets": {"rpo_minutes": 15, "rto_hours": 4},
    "alerts": {"channels": {"email": [], "sms": [], "webhook": None}, "rules_version": "1"},
    "status_page": {
        "components": [
            "api",
            "web",
            "workers",
            "database",
            "redis",
            "storage",
            "payments",
            "sms",
            "whatsapp",
            "email",
            "push",
        ],
        "public_url": "https://status.septronuniverse.in",
        "announce_incidents": True,
    },
    "capacity": {
        "pool_size": 20,
        "max_overflow": 10,
        "pgbouncer_pool": 200,
        "celery_concurrency": {
            "notifications": 8,
            "emails": 4,
            "documents": 4,
            "reports": 4,
            "integrations": 4,
            "scheduled": 2,
        },
        "redis_maxmemory": "2gb",
        "redis_policy": "allkeys-lru",
    },
    "release": {"changelog_path": "CHANGELOG.md", "announce_to_institutions": True, "deprecation_notice_days": 90},
}
ENV_DEFAULTS = {
    "demo": {"all_features": True, "providers": "sandbox"},
    "staging": {"all_features": False, "providers": "sandbox"},
    "prod": {"all_features": False, "providers": "live"},
}


def upgrade() -> None:
    from app.services.institution_defaults import seed_phase04_platform

    conn = op.get_bind()
    for key, value in (("ops", OPS), ("features.env_defaults", ENV_DEFAULTS)):
        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "v": json.dumps(value)},
        )
    platform = seed_phase04_platform(conn)
    print(f"  notification_templates+={platform['notification_templates']}")  # noqa: T201


def downgrade() -> None:
    op.get_bind().execute(text("DELETE FROM platform_settings WHERE key IN ('ops', 'features.env_defaults')"))
