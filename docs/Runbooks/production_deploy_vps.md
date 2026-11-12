# Production deploy — Orbit VPS (orbit-infra)

Universe prod runs on the shared Orbit VPS. It is deployed the same way as Orbit:

```
push to main (this repo)
  → .github/workflows/build.yml
      → ghcr.io/septronr/universe-api:prod-<sha12>
      → ghcr.io/septronr/universe-web:prod-<sha12>
  → repository_dispatch "deploy" {env: universe, image, web_image}
  → orbit-infra .github/workflows/deploy.yml   (approval: `production` environment)
  → SSH deploy@VPS
  → /opt/orbit-server/orbit-infra/scripts/update.sh universe <api> <web>
  → docker compose -f compose/apps/universe-prod.yml pull && up -d
```

`docker-compose.prod.yml`, `nginx/nginx.conf` and `ops/orbit-infra/*` are Phase 44 references. The live definition is `orbit-infra/compose/apps/universe-prod.yml`.

## Topology

| Container | Image | What it does |
|---|---|---|
| `universe-migrate` | universe-api | One-shot: `scripts/migrate_with_lock.py`, which runs the Alembic upgrade and then the platform seed. Exits 0. |
| `universe-api` | universe-api | gunicorn + uvicorn, 2 workers, port 8000. Serves `/api`, `/ws`, `/uploads`, `/site`, `/.well-known`, `/health`, `/ready`. |
| `universe-worker` | universe-api | Celery worker on every queue, concurrency 3. |
| `universe-beat` | universe-api | Celery beat. Exactly one instance. |
| `universe-web` | universe-web | nginx serving the SPA build. |

**Shared services:**
- `orbit-postgres` holds database `universe`:
  - `universe_app` is the runtime role (RLS enforced).
  - `universe_platform` is the owner and migrator (BYPASSRLS).
- `orbit-redis` uses DB 13 (cache/pub-sub), 14 (broker) and 15 (results).

**Routing (Traefik):**

| Host | Routed to |
|---|---|
| `app.universe.septronr.com` | The API paths above go to `universe-api`; everything else goes to `universe-web`. Same-origin, so the SameSite=Strict refresh cookie works. |
| `api.universe.septronr.com` | `universe-api` only. Used by the mobile app and integrations. |

**Uploads:** `/opt/orbit-server/data/universe/uploads`, owned by uid 10002 (the `app` user in `backend/Dockerfile`).

**Tenants:** chosen with `?institution=<slug>` or at login. There are no wildcard tenant subdomains yet.

## Before the first deploy — what is needed

| # | Item | Where |
|---|---|---|
| 1 | DNS A records `app.universe` and `api.universe` pointing to the VPS IP | septronr.com DNS panel |
| 2 | Secret `INFRA_DISPATCH_TOKEN` (classic PAT, `repo` scope on orbit-infra; Orbit's can be reused) | SeptronUniverse → Settings → Secrets → Actions |
| 3 | Actions workflow permissions set to *Read and write* (needed for the GHCR push) | SeptronUniverse → Settings → Actions → General |
| 4 | The VPS can pull `ghcr.io/septronr/universe-*`: make the packages public, or `docker login ghcr.io` with a `read:packages` PAT | VPS / GitHub Packages |
| 5 | Free capacity: about 2 GB RAM and 10 GB disk (`free -h; df -h /`); `show max_connections` on orbit-postgres has 40 or more spare | VPS |
| 6 | Super-admin email | `.env` |
| 7 | SMTP / SendGrid / MSG91 credentials for OTP, password reset and notifications | entered in the UI after install |

## First-time setup (VPS)

1. **Merge the orbit-infra PR (`universe-prod`).** The push to its `main` runs `update.sh all`. Universe is skipped while `UNIVERSE_API_IMAGE` is still `CHANGE_ME`.

2. **Connect and update the checkout.**
   ```bash
   ssh deploy@<vps>
   cd /opt/orbit-server/orbit-infra
   git fetch origin main
   git checkout --force --detach origin/main
   ```

3. **Add the `UNIVERSE_*` block from `.env.example` to `.env`, and fill it in.**
   - The `UNIVERSE_*_IMAGE` lines must exist, because `update.sh` rewrites them in place.
   - Generate the secrets:
     ```bash
     openssl rand -hex 24      # UNIVERSE_DB_APP_PASSWORD, UNIVERSE_DB_PLATFORM_PASSWORD, UNIVERSE_INSTALL_SECRET_KEY
     openssl rand -hex 48      # UNIVERSE_SECRET_KEY
     openssl rand -hex 32      # UNIVERSE_INTERNAL_OPS_TOKEN, UNIVERSE_METRICS_TOKEN
     openssl rand -base64 32   # UNIVERSE_INTEGRATION_ENCRYPTION_KEY  (store an offline copy)
     ```
   - Set `chmod 600 .env`.

4. **Create the folders.**
   ```bash
   sudo ./scripts/bootstrap-folders.sh     # creates data/universe/uploads, chown 10002
   ```

5. **Create the database and roles.** Run once; it is safe to re-run, and doing so rotates the passwords.
   ```bash
   set -a; source .env; set +a
   docker exec -i orbit-postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
     -v app_pw="$UNIVERSE_DB_APP_PASSWORD" -v platform_pw="$UNIVERSE_DB_PLATFORM_PASSWORD" \
     < compose/postgres/manual/universe-init.sql
   ```

6. **Build and deploy.**
   - Merge `verify/stage2` → `main` in SeptronUniverse. *Build & Push* runs (about 10 min), then orbit-infra *Deploy Orbit* waits for `production` approval.
   - Manual fallback, with the tags from the build run:
     ```bash
     ./scripts/update.sh universe ghcr.io/septronr/universe-api:prod-<sha12> ghcr.io/septronr/universe-web:prod-<sha12>
     ```

7. **Watch the first start.**
   ```bash
   docker logs -f universe-migrate        # 0001 … 0048, seed counts, "migrations done", exit 0
   docker ps --filter name=universe       # api / worker / beat / web healthy
   curl -fsS https://api.universe.septronr.com/ready
   ```

8. **Install the platform.** This happens once. In production the seed does not create a super admin; `/install` does.
   ```bash
   curl -fsS -X POST https://app.universe.septronr.com/api/v1/install \
     -H 'Content-Type: application/json' \
     -d '{"install_key":"<UNIVERSE_INSTALL_SECRET_KEY>","super_admin_email":"<email>","super_admin_username":"superadmin","super_admin_password":"<strong password>"}'
   ```
   Any later call returns 409.

9. **Configure in the UI.**
   - Log in at `https://app.universe.septronr.com` and set up MFA.
   - Go to Platform → Integrations and enter the email and SMS providers.
   - Create the first institution.

10. **Web push (optional).**
    - Run `docker run --rm "$UNIVERSE_API_IMAGE" python scripts/gen_vapid.py`.
    - Put the keys in `UNIVERSE_VAPID_*` and run `./scripts/update.sh universe`.
    - Put the public key in `frontend/.env.production` (`VITE_VAPID_PUBLIC_KEY`) and push.

11. **Ops.**
    - Add Uptime Kuma monitors for `https://api.universe.septronr.com/ready` and `https://app.universe.septronr.com/`.
    - Make sure the nightly `scripts/backup.sh` cron is enabled. It now dumps `universe` and tars the uploads.
    - Restore the dump once into a scratch database to prove the backup works.

## Every later deploy

Push or merge to `main`, then approve the orbit-infra run.
- `universe-migrate` re-runs on the new image before api, worker and beat are recreated.
- Expect a few seconds of API downtime per deploy, because there is a single api container.
- Migrations must stay expand-only (`deploy_and_rollback.md`).

**Rollback:** run `./scripts/update.sh universe <previous api tag> <previous web tag>`. The previous tags are in the orbit-infra run log and `.env` history.

## Verify after deploy

`run_all.py` refuses production. Check by hand.

**API checks:**
```bash
curl -fsS https://api.universe.septronr.com/health
curl -fsS https://api.universe.septronr.com/ready              # db, redis, storage, migration head, outbox lag
curl -fsS https://api.universe.septronr.com/.well-known/jwks.json
curl -s -o /dev/null -w '%{http_code}\n' https://api.universe.septronr.com/metrics   # 401/403 without METRICS_TOKEN
```

**UI checks:**
- Log in, reload the page, and confirm you are still logged in (refresh cookie).
- Open `?institution=<slug>`.
- Upload a file, then download it through the signed `/uploads` link.
- Generate a PDF document (WeasyPrint plus the documents queue).
- Confirm an in-app notification arrives (worker plus outbox relay).

**Infra checks:**
- `./scripts/healthcheck.sh`
- `docker stats --no-stream | grep universe` is within the memory limits.
- Orbit `https://api.orbit.septronr.com/health` is still OK.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `universe-migrate` exits 1, `Database_Schema.sql not found` | The image was built without the CI copy step. Rebuild through `build.yml`, not a bare `docker build backend/`. |
| migrate fails with `permission denied for schema public` | `universe-init.sql` was not run, or was run against the wrong database. |
| `!! database not reachable` | orbit-postgres is not on the `proxy` network or is down: `docker ps --filter name=orbit-postgres`. |
| Login says *Unknown institution* for the platform host | A host is missing from `PLATFORM_HOSTS`, or `UNIVERSE_*_HOST` is wrong in `.env`. |
| `app.` serves the SPA but `/api` returns 404 | The `universe-api` container is unhealthy, so Traefik dropped it: `docker inspect --format '{{json .State.Health}}' universe-api`. |
| Upload fails with `PermissionError` | `data/universe/uploads` is not owned by 10002. Re-run `bootstrap-folders.sh`. |
| OTP / password reset returns 503 | No email or SMS provider configured. Set them in Platform → Integrations. |
| `too many connections` | Lower `UNIVERSE_DB_POOL_SIZE` / `UNIVERSE_WORKER_CONCURRENCY`, or raise orbit-postgres `max_connections`. |
