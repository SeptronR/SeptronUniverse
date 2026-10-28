# Runbook — Deploy & rollback

**Normal path.** Merge to `main` (demo) or push `release/*` / tag `v*` (staging → prod with approval). `build.yml` builds `universe-api` / `universe-web`, runs guards + security, pushes `ghcr.io/septronr/universe-*:{env}-{sha}` and dispatches `universe-deploy` to orbit-infra, which runs `backend/scripts/ops/deploy.sh`:
1. Pre-checks: images pull; last backup < 6 h (`GET /platform/ops/overview` → `backups.age_min`); `RISKY=1` → open the read-only window first (`POST /platform/maintenance`).
2. `migrate` one-shot (advisory lock, `scripts/migrate_with_lock.py`), API replicas one at a time gated on `/ready`, workers (Celery warm shutdown, `stop_grace_period` 60 s), beat, web.
3. Smoke (`run_all.py --suite smoke`), deploy record → `GET /platform/ops/deploys`.

**Rollback.** Automatic when readiness fails: previous tags restored, `status=rolled_back`, `ops.rollback` notification. Manual: set `UNIVERSE_IMAGE` / `UNIVERSE_WEB_IMAGE` in `.env.prod` to the previous tag (deploy record `image_tags`) and `docker compose -f docker-compose.prod.yml up -d --no-deps api web worker-* beat`. Never roll the database back — migrations are expand-only within a release (see `migration_failure.md`).
