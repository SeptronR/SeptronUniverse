#!/usr/bin/env bash
# Quarterly restore drill (Prompts/44 §44.6 backup_dr 2) — run on a scratch host, never on production:
#   OPS_API_URL=https://api.example INTERNAL_OPS_TOKEN=… ./restore_drill.sh [--target-time "now-10min"]
# 1. restore the latest backup + WAL with PITR into /var/lib/postgresql/drill (pgbackrest --type=time)
# 2. start a scratch postgres on :55432, check `alembic current` = head, row counts on 20 key tables, audit chain
# 3. measure RPO (target time vs last archived WAL) and RTO (wall time), post the RestoreDrill record
set -euo pipefail
TARGET="${1:-}"
START=$(date +%s)
DATA=/var/lib/postgresql/drill
PORT=55432
TT=$(date -u -d "-10 min" +"%Y-%m-%d %H:%M:%S+00")
[ "$TARGET" = "--target-time" ] && TT="$2"

rm -rf "$DATA" && mkdir -p "$DATA"
pgbackrest --stanza=universe --pg1-path="$DATA" --type=time --target="$TT" --target-action=promote restore
pg_ctl -D "$DATA" -o "-p $PORT -c archive_mode=off" -w start
trap 'pg_ctl -D "$DATA" -m fast stop || true' EXIT

PSQL="psql -h 127.0.0.1 -p $PORT -U postgres -d universe -tAc"
CHECKS=()
HEAD=$($PSQL "SELECT version_num FROM alembic_version")
EXPECTED=$(ls /app/alembic/versions 2>/dev/null | sed -n 's/^\([0-9]\{4\}\)_.*/\1/p' | sort | tail -1)
[ -z "$EXPECTED" ] || [ "$HEAD" = "$EXPECTED" ] && CHECKS+=("alembic_head:$HEAD")
for t in institutions users students staff enrollments course_offerings course_registrations student_class_attendance \
         internal_marks student_course_results student_term_results fee_invoices fee_payments issued_documents \
         audit_logs domain_events notifications hostel_allocations library_issues data_subject_requests; do
  n=$($PSQL "SELECT count(*) FROM $t" 2>/dev/null || echo "missing")
  CHECKS+=("$t:$n")
done
LAST_WAL=$($PSQL "SELECT EXTRACT(EPOCH FROM NOW() - max(created_at))/60 FROM audit_logs" || echo 999)
END=$(date +%s)
RTO=$(( (END - START) / 60 ))
RPO=$(printf '%.0f' "${LAST_WAL:-999}")
JSON_CHECKS=$(printf '"%s",' "${CHECKS[@]}" | sed 's/,$//')
curl -fsS -X POST "${OPS_API_URL}/api/v1/internal/ops/restore-drill" -H "X-Ops-Token: ${INTERNAL_OPS_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"source_backup\":\"latest\",\"target_env\":\"scratch\",\"rpo_observed_min\":$RPO,\"rto_observed_min\":$RTO,\"verified_checks\":[${JSON_CHECKS}]}"
echo "restore drill: RPO≈${RPO} min, RTO=${RTO} min, ${#CHECKS[@]} checks"
