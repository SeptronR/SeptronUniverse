#!/bin/sh
# Backup sidecar loop (Prompts/44 §44.6 backup_dr 1): pgBackRest full on Sunday 01:00, incremental every 6 h, verify
# daily; each run is reported to POST /api/v1/internal/ops/backup-report (X-Ops-Token). WAL archiving is continuous
# (postgresql.conf archive_command). Requires PGBACKREST_REPO1_S3_KEY / _KEY_SECRET / PGBACKREST_REPO1_CIPHER_PASS,
# INTERNAL_OPS_TOKEN and OPS_API_URL (default http://api:8000) in the environment.
set -u
API="${OPS_API_URL:-http://api:8000}/api/v1/internal/ops/backup-report"
STANZA=universe

report() { # kind status started size
  curl -fsS -X POST "$API" -H "X-Ops-Token: ${INTERNAL_OPS_TOKEN}" -H 'Content-Type: application/json' \
    -d "{\"kind\":\"$1\",\"status\":\"$2\",\"started_at\":\"$3\",\"size_bytes\":${4:-null},\"location\":\"s3://universe-backups/pgbackrest\"}" \
    >/dev/null || echo "backup report failed"
}

run() { # kind type
  start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if pgbackrest --stanza=$STANZA --type="$2" backup; then
    size=$(pgbackrest --stanza=$STANZA info --output=json | sed -n 's/.*"repo-size":\([0-9]*\).*/\1/p' | tail -1)
    report "$1" succeeded "$start" "${size:-null}"
  else
    report "$1" failed "$start"
  fi
}

pgbackrest --stanza=$STANZA stanza-create 2>/dev/null || true
while true; do
  now_dow=$(date -u +%u); now_h=$(date -u +%H); now_m=$(date -u +%M)
  if [ "$now_m" = "00" ]; then
    if [ "$now_dow" = "7" ] && [ "$now_h" = "01" ]; then run full full
    elif [ $(( $(echo "$now_h" | sed 's/^0//;s/^$/0/') % 6 )) -eq 0 ]; then run incr incr
    fi
    if [ "$now_h" = "04" ]; then
      start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      if pgbackrest --stanza=$STANZA verify; then report verify succeeded "$start"; else report verify failed "$start"; fi
    fi
  fi
  sleep 60
done
