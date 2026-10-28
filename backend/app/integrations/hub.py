"""Tenant connection resolution — Prompts/41 §41.3 ``get(capability, institution_id, label=None)``.

Order: the tenant's connection for the capability (a ``college:{code}`` label first when a college is given, then
the default — ``public_config.is_default`` — then any enabled one) → the platform default
(``platform_settings['integrations.platform_defaults'][capability]`` = ``{provider, config}``; platform billing / SaaS
messaging) → the mock in non-production. In production without any connection the call raises
``INTEGRATION_FAILED {code: NOT_CONFIGURED}``. Secrets are decrypted only here (AES-GCM, ``INTEGRATION_ENCRYPTION_KEY``)
and merged with ``public_config``; the instance carries the breaker / timeout / rate-limit settings.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.integrations.base import DEFAULT_BREAKER, DEFAULT_TIMEOUTS, IntegrationFailed
from app.integrations.catalogue import CAPABILITY_INFO
from app.integrations.registry import get_adapter


def decrypt_config(blob: bytes | None) -> dict[str, Any]:
    if not blob:
        return {}
    from app.core.security import decrypt_secret

    try:
        return dict(json.loads(decrypt_secret(bytes(blob))))
    except Exception:  # noqa: BLE001 - a key rotation in progress / corrupt blob → no secrets (health shows it)
        return {}


def encrypt_config(cfg: dict[str, Any]) -> bytes:
    from app.core.security import encrypt_secret

    return encrypt_secret(json.dumps(cfg))


def build_adapter(
    capability: str, provider: str, config: dict[str, Any], *, connection_id: Any = None, sandbox: bool = False
) -> Any:
    info = CAPABILITY_INFO.get(capability)
    extra = {
        "_connection_id": str(connection_id or ""),
        "_sandbox": sandbox,
        "_timeout": DEFAULT_TIMEOUTS.get(info.timeout if info else "lookup", 15),
        "_breaker": DEFAULT_BREAKER,
    }
    try:
        return get_adapter(capability, provider, **{**config, **extra})
    except TypeError:  # pre-Phase 41 adapters (Phase 12 / 02 / 30 mocks) take only their own config
        return get_adapter(capability, provider, **config)


async def resolve(
    db: Any,
    capability: str,
    institution_id: uuid.UUID | None,
    *,
    college_code: str | None = None,
    label: str | None = None,
    fallback: bool = True,
) -> Any:
    rows: list[Any] = []
    if institution_id is not None:
        rows = list(
            (
                await db.execute(
                    text(
                        "SELECT id, provider, label, config_encrypted, public_config, is_sandbox FROM integration_connections "
                        "WHERE institution_id = :i AND capability = :c AND status <> 'disabled' ORDER BY created_at"
                    ),
                    {"i": institution_id, "c": capability},
                )
            ).mappings()
        )
    pick = None
    for want in (label, f"college:{college_code}" if college_code else None):
        if want:
            pick = next((r for r in rows if r["label"] == want), None) or pick
            if pick:
                break
    if pick is None:
        pick = next(
            (
                r
                for r in rows
                if (r["public_config"] or {}).get("is_default") and not str(r["label"] or "").startswith("college:")
            ),
            None,
        )
    if pick is None:
        pick = next((r for r in rows if not str(r["label"] or "").startswith("college:")), None)
    if pick is not None:
        cfg = {
            **{k: v for k, v in (pick["public_config"] or {}).items() if k != "is_default"},
            **decrypt_config(pick["config_encrypted"]),
        }
        return build_adapter(
            capability, pick["provider"], cfg, connection_id=pick["id"], sandbox=bool(pick["is_sandbox"])
        )
    if not fallback:
        return None
    platform = await platform_default(capability)
    if platform:
        return build_adapter(
            capability, str(platform.get("provider")), dict(platform.get("config") or {}), connection_id="platform"
        )
    if settings.APP_ENV == "production":
        raise IntegrationFailed(capability, "NOT_CONFIGURED", f"No {capability} provider is configured", status=503)
    return build_adapter(capability, "mock", {})


async def platform_default(capability: str) -> dict[str, Any] | None:
    from app.db.session import PlatformSessionLocal

    try:
        async with PlatformSessionLocal() as pdb:
            r = (
                await pdb.execute(
                    text("SELECT value FROM platform_settings WHERE key = 'integrations.platform_defaults'")
                )
            ).first()
    except Exception:  # noqa: BLE001
        return None
    value = r[0] if r and isinstance(r[0], dict) else {}
    d = value.get(capability)
    return d if isinstance(d, dict) and d.get("provider") else None
