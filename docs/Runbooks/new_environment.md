# Runbook — Onboarding a new environment

1. Host from the orbit-infra playbook (Docker, Traefik, node exporter, firewall: 80/443 only).
2. Vault entry `/srv/vault/universe/.env.<env>` from `backend/.env.example` (unique `SECRET_KEY`, `INSTALL_SECRET_KEY`, `INTEGRATION_ENCRYPTION_KEY`, `INTERNAL_OPS_TOKEN`, `METRICS_TOKEN`, DB / Redis passwords, S3 + pgBackRest keys).
3. GitHub environment + orbit-infra runner label; `vars.UNIVERSE_API_URL`.
4. First deploy (`workflow_dispatch` on build.yml), `/install` wizard for the first super admin, `seed_platform.py`.
5. Prometheus / Alertmanager / Grafana provisioning from `ops/`; status page URL; first backup + restore drill before go-live.
