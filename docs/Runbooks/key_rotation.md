# Runbook — Key rotation

| Key | Procedure |
|---|---|
| JWT signing | `jwt_key_rotation.md` (new `kid`, previous key kept for the grace window, JWKS lists both) |
| Integration encryption (`INTEGRATION_ENCRYPTION_KEY`) | deploy the new key, keep the old one as previous, run `ops scripts → key_rotation {kind: integration}` (re-encrypts every connection; four-eyes) and test connections |
| Webhook secrets | per webhook *Rotate secret* (tenant), receivers accept both signatures during their own switch |
| API keys | *Rotate* keeps the old key valid for the grace window |
| Backup encryption (`PGBACKREST_REPO1_CIPHER_PASS`) | new stanza / repo with the new pass; keep the old repo until its retention expires |
| Ops / metrics / edge tokens | change in the vault, redeploy, update Prometheus / Alertmanager / CI secrets |
