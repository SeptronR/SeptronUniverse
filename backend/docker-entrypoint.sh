#!/bin/sh
# SeptronUniverse container entrypoint (Prompts/44 §44.6 docker 1).
#   1. wait for PostgreSQL and Redis (DB_WAIT_SECONDS, default 60)
#   2. RUN_MIGRATIONS=1 (backend replicas / the one-shot `migrate` service): lock-protected `alembic upgrade head`,
#      drift check (warning) and the idempotent platform catalogue refresh — workers / beat / flower set 0
#   3. exec the container command (gunicorn, celery worker / beat, flower)
set -e

wait_for() {
    python - "$1" <<'PY'
import os, socket, sys, time
from urllib.parse import urlparse
url = os.environ.get(sys.argv[1], "")
u = urlparse(url.replace("postgresql+asyncpg", "postgresql"))
host, port = u.hostname, u.port or (5432 if u.scheme.startswith("postgres") else 6379)
deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
while host and time.time() < deadline:
    try:
        socket.create_connection((host, port), timeout=2).close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit(0 if not host else 1)
PY
}

wait_for DATABASE_URL || { echo "!! database not reachable"; exit 1; }
wait_for REDIS_URL || { echo "!! redis not reachable"; exit 1; }

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python scripts/migrate_with_lock.py
else
    echo "-> RUN_MIGRATIONS=${RUN_MIGRATIONS:-0}, skipping migrations"
fi

exec "$@"
