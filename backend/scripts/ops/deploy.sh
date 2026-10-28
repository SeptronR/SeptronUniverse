#!/usr/bin/env bash
# Rolling deploy with automatic rollback (Prompts/44 §44.6 deploy_service) — the orbit-infra dispatch receiver runs:
#   ENV=staging API_TAG=staging-<sha> WEB_TAG=staging-<sha> SHA=<sha> RISKY=0 ./deploy.sh
# Steps: pre-checks (images pull, backup < 6 h, risky → read-only window) → one-shot migrate → API replicas one at a
# time gated on /ready → workers (graceful drain) → beat → smoke → deploy record; on failure restore the previous tags.
set -euo pipefail
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
API="${OPS_API_URL:-http://localhost}/api/v1"
TOKEN="${INTERNAL_OPS_TOKEN:?}"
PREV_API=$(grep '^UNIVERSE_IMAGE=' .env.prod | cut -d= -f2- || true)
PREV_WEB=$(grep '^UNIVERSE_WEB_IMAGE=' .env.prod | cut -d= -f2- || true)
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
report() { curl -fsS -X POST "$API/internal/ops/deploy-report" -H "X-Ops-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"env\":\"$ENV\",\"sha\":\"$SHA\",\"status\":\"$1\",\"started_at\":\"$STARTED\",\"finished_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"image_tags\":{\"api\":\"$API_TAG\",\"web\":\"$WEB_TAG\"},\"rollback_to\":\"${2:-}\"}" >/dev/null || true; }
set_tags() { sed -i "s#^UNIVERSE_IMAGE=.*#UNIVERSE_IMAGE=$1#; s#^UNIVERSE_WEB_IMAGE=.*#UNIVERSE_WEB_IMAGE=$2#" .env.prod; }
wait_ready() { for _ in $(seq 1 "${READY_TIMEOUT:-120}"); do curl -fsS "${OPS_API_URL:-http://localhost}/ready" >/dev/null && return 0; sleep 1; done; return 1; }

rollback() {
  echo "!! deploy failed — rolling back to $PREV_API"
  set_tags "$PREV_API" "$PREV_WEB"
  $COMPOSE up -d --no-deps api web worker-notifications worker-emails worker-documents worker-reports worker-integrations worker-scheduled beat
  wait_ready && report rolled_back "$PREV_API" || report failed
  exit 1
}

report started
AGE=$(curl -fsS "$API/public/status" >/dev/null && echo ok || echo down)
[ "$AGE" = ok ] || echo "warning: status endpoint unreachable before deploy"
set_tags "ghcr.io/septronr/universe-api:$API_TAG" "ghcr.io/septronr/universe-web:$WEB_TAG"
$COMPOSE pull api web || rollback
if [ "${RISKY:-0}" = "1" ]; then
  echo "-> risky migration: the platform read-only window must be open (POST /platform/maintenance) before continuing"
fi
$COMPOSE run --rm migrate || rollback
for i in $(seq 1 "${API_REPLICAS:-2}"); do
  $COMPOSE up -d --no-deps --wait --scale api="$i" api || rollback
done
$COMPOSE up -d --no-deps --wait api || rollback
wait_ready || rollback
for w in worker-notifications worker-emails worker-documents worker-reports worker-integrations worker-scheduled; do
  $COMPOSE up -d --no-deps "$w" || rollback          # SIGTERM → Celery warm shutdown (stop_grace_period 60 s)
done
$COMPOSE up -d --no-deps beat web || rollback
curl -fsS "${OPS_API_URL:-http://localhost}/health" >/dev/null || rollback
report succeeded
echo "-> deployed $API_TAG"
