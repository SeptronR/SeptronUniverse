"""Key rotation (four-eyes): ``--kind integration`` re-encrypts every provider secret with the current
``INTEGRATION_ENCRYPTION_KEY`` (Phase 41 job body); ``--kind jwt`` prints the deployment steps (keys are secrets in the
host vault, docs/Runbooks/jwt_key_rotation.md).

    python scripts/ops/key_rotation.py --kind integration|jwt
"""

import argparse

from _ops import run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("integration", "jwt"), required=True)
    ap.add_argument("--kid", default=None, help="new key id recorded on each re-encrypted connection")
    a = ap.parse_args()

    async def fn(db):  # type: ignore[no-untyped-def]
        if a.kind == "jwt":
            from app.core.config import settings
            from app.core.security import signing_algorithm

            return {
                "algorithm": signing_algorithm(),
                "current_kid": settings.JWT_KID,
                "runbook": "docs/Runbooks/jwt_key_rotation.md",
            }
        from datetime import UTC, datetime

        from app.services.integrations.connection_service import reencrypt_all

        kid = a.kid or datetime.now(UTC).strftime("k%Y%m%d")
        return {"reencrypted": await reencrypt_all(db, kid), "kid": kid}

    run(fn, platform=True)


if __name__ == "__main__":
    main()
