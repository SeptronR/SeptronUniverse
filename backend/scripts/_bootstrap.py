"""Shared bootstrap for scripts: put ``backend/`` on ``sys.path`` and supply harmless defaults for the required
settings when no ``.env`` exists (structural guards must run on a bare checkout; CI sets the real values)."""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SCHEMA_SQL = REPO_ROOT / "Database_Schema.sql"
DOCS_DIR = REPO_ROOT / "docs"
FRONTEND_DIR = REPO_ROOT / "frontend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_DEFAULTS = {
    "SECRET_KEY": "guard-only-secret-not-for-runtime",
    "DATABASE_URL": "postgresql+asyncpg://universe_app:pass@localhost:5432/universe",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/1",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
    "INTEGRATION_ENCRYPTION_KEY": "Z3VhcmQtb25seS1rZXktbm90LWZvci1ydW50aW1lLTAwMDA=",
    "INSTALL_SECRET_KEY": "guard-only",
}
if not (BACKEND_DIR / ".env").exists():
    for k, v in _DEFAULTS.items():
        os.environ.setdefault(k, v)
os.chdir(BACKEND_DIR)  # settings read ./.env; alembic.ini is relative
