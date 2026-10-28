# Runbook — Certificates & custom domains

* Platform hosts: Traefik ACME (`letsencrypt` resolver) renews automatically; alert `CertificateExpiringSoon` < 14 days means renewal is failing — check the Traefik log and DNS / HTTP challenge reachability.
* Custom institution domains: tenants verify via TXT (`_universe-verify.<host>`); `gen_traefik_domains.py` (cron, 5 min) writes one router per verified host; the edge reports SSL state to `POST /internal/domains/{id}/ssl-status`.
* Removing a domain: delete it on `/admin/website/domains`; the router disappears on the next generator run.
