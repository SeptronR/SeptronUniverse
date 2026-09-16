#!/bin/sh
# Bring the database to head (only when RUN_MIGRATIONS=1 — the backend service; workers/beat/flower set 0 so a
# single container migrates), then hand off to the container command.
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    if ls alembic/versions/*.py >/dev/null 2>&1; then
        echo "-> applying migrations (alembic upgrade head)"
        alembic upgrade head
        echo "-> database at head"
    else
        echo "-> no Alembic revisions yet (Phase 01 adds 0001) - skipping migrations"
    fi
else
    echo "-> RUN_MIGRATIONS=${RUN_MIGRATIONS}, skipping migrations"
fi

exec "$@"
