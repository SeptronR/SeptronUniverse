"""Platform settings — Prompts/38 §38.6 ``platform_settings_service``.

Business rules
1. Typed keys of :data:`~app.enums.saas.PLATFORM_KEYS` (``scope=platform`` — the Phase 37 catalogue renders them
   read-only for tenants); values merge over :data:`PLATFORM_DEFAULTS`.
2. Secret sub-keys (``captcha.secret``) are never returned (``***``); sending ``***`` back keeps the stored value.
3. Validation by type (int with min / max, bool, list, json object, string); unknown keys → 422.
4. ``mobile.min_versions`` feeds ``/mobile/config`` and ``/public/config`` (Phase 01 ``PlatformService`` reads the
   same row); every change is audited (``platform:settings_update`` with the changed keys, secrets redacted) and
   emits ``platform.settings_changed``. Super admin only for writes; support agents read.
"""

from typing import Any

from sqlalchemy import select

from app.enums.saas import PLATFORM_DEFAULTS, PLATFORM_KEYS, SECRET_MASK
from app.models.saas import PlatformSetting
from app.schemas.saas import PlatformSettingOut, PlatformSettingsIn
from app.services.saas.common import PlatformBase, unprocessable


class PlatformSettingsService(PlatformBase):
    async def items(self) -> list[PlatformSettingOut]:
        self.require_platform("platform", "view")
        rows = {
            r.key: r
            for r in (
                await self.db.execute(select(PlatformSetting).where(PlatformSetting.key.in_(list(PLATFORM_KEYS))))
            ).scalars()
        }
        out = []
        for key, meta in PLATFORM_KEYS.items():
            row = rows.get(key)
            default = PLATFORM_DEFAULTS.get(key)
            value = row.value if row is not None and row.value is not None else default
            if isinstance(default, dict) and isinstance(value, dict):
                value = {**default, **value}
            out.append(
                PlatformSettingOut(
                    key=key,
                    group=meta["group"],
                    label=meta["label"],
                    type=meta["type"],
                    value=_masked(value, meta.get("secret") or []),
                    default=_masked(default, meta.get("secret") or []),
                    secret_keys=list(meta.get("secret") or []),
                    updated_at=row.updated_at if row is not None else None,
                    updated_by=row.updated_by if row is not None else None,
                )
            )
        return out

    async def update(self, body: PlatformSettingsIn) -> list[PlatformSettingOut]:
        self.require_super("Changing platform settings")
        changed: dict[str, Any] = {}
        for key, raw in _expand(body.values).items():
            meta = PLATFORM_KEYS.get(key)
            if meta is None:
                raise unprocessable(f"Unknown platform setting {key!r}", field=key)
            current = await self.setting(key)
            value = _validate(key, meta, raw)
            secrets = list(meta.get("secret") or [])
            if secrets and isinstance(value, dict):
                for s in secrets:
                    if value.get(s) == SECRET_MASK or s not in value:
                        value[s] = (current or {}).get(s) if isinstance(current, dict) else None
            if isinstance(PLATFORM_DEFAULTS.get(key), dict) and isinstance(value, dict):
                value = {**(current or {}), **value}
            if value == current:
                continue
            await self.pput(key, value)
            changed[key] = _masked(value, secrets)
        if changed:
            await self.audit(
                "settings_update",
                "platform_settings",
                None,
                {"keys": sorted(changed), "values": changed, "reason": body.reason},
            )
            await self.emit("platform.settings_changed", {"keys": sorted(changed)}, aggregate_type="platform_settings")
        return await self.items()


def _expand(values: dict[str, Any]) -> dict[str, Any]:
    """``{"mobile.min_versions.android": "2.3.0"}`` → ``{"mobile.min_versions": {"android": "2.3.0"}}``."""
    out: dict[str, Any] = {}
    for key, raw in values.items():
        parent, _, sub = key.rpartition(".")
        if key not in PLATFORM_KEYS and parent in PLATFORM_KEYS and PLATFORM_KEYS[parent]["type"] == "json":
            merged = dict(out.get(parent) or {})
            merged[sub] = raw
            out[parent] = merged
        else:
            out[key] = raw
    return out


def _masked(value: Any, secrets: list[str]) -> Any:
    if not secrets or not isinstance(value, dict):
        return value
    return {k: (SECRET_MASK if k in secrets and v else v) for k, v in value.items()}


def _validate(key: str, meta: dict[str, Any], raw: Any) -> Any:
    kind = meta["type"]
    if kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, int | str):
            raise unprocessable(f"{key} must be an integer", field=key)
        try:
            value = int(raw)
        except ValueError as exc:
            raise unprocessable(f"{key} must be an integer", field=key) from exc
        if "min" in meta and value < meta["min"] or "max" in meta and value > meta["max"]:
            raise unprocessable(f"{key} must be between {meta.get('min')} and {meta.get('max')}", field=key)
        return value
    if kind == "bool":
        if not isinstance(raw, bool):
            raise unprocessable(f"{key} must be true or false", field=key)
        return raw
    if kind == "list":
        if not isinstance(raw, list):
            raise unprocessable(f"{key} must be a list", field=key)
        return raw
    if kind == "json":
        if not isinstance(raw, dict):
            raise unprocessable(f"{key} must be an object", field=key)
        if key == "mobile.min_versions":
            import re

            for platform in ("android", "ios"):
                v = raw.get(platform)
                if v is not None and not re.fullmatch(r"\d+(\.\d+){0,3}", str(v)):
                    raise unprocessable(f"{key}.{platform} must look like 2.3.0", field=f"{key}.{platform}")
        return dict(raw)
    if not isinstance(raw, str) or len(raw) > 500:
        raise unprocessable(f"{key} must be a string", field=key)
    return raw
