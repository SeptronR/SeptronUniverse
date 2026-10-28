# Runbook — JWT signing key rotation

`security.jwt_rotation_days` (default 90). `GET /api/v1/security/jwt` shows the algorithm, current `kid` and published keys.

**HS256 (default):** generate a new secret, set `JWT_PREVIOUS_KEYS={"<old kid>": "<old secret>"}`, `SECRET_KEY=<new>`,
`JWT_KID=<new kid>`; rolling restart; remove the previous key after `ACCESS_TOKEN_EXPIRE_MINUTES` +
`REFRESH_TOKEN_EXPIRE_DAYS`.

**RS256:**
1. `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt-<kid>.pem` (offline; store in the secret manager).
2. Move the current public key into `JWT_RSA_PREVIOUS_PUBLIC_KEYS` (`{"<old kid>": "<PEM>"}`).
3. Deploy `JWT_RSA_PRIVATE_KEY=<new PEM>` and `JWT_KID=<new kid>`; rolling restart — new tokens carry the new `kid`,
   existing tokens verify against the previous public key; `/.well-known/jwks.json` lists both.
4. After the grace window remove the previous key and redeploy.

Never commit keys; custody is recorded in the secret manager's access log.
