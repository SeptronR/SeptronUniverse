"""Institution settings — Prompts/03 §03.6 ``institution_service`` rules 3–4 (settings, themes, provider tests).

Business rules
1. The key catalogue is ``app/core/settings_template.py`` (also stored in ``platform_settings['settings_template']``
   by revision 0003). ``get(category, college_id)`` merges template default → institution row → college override and
   flags ``is_default``; institution-level categories are cached in Redis ``settings:{institution}:{category}``.
2. ``bulk_update(items)`` validates every item against its definition before writing anything (unknown key or a value
   of the wrong type → ``422 VALIDATION`` naming the item index); theme keys additionally need ``institution.themes``
   (403 FEATURE_DISABLED); a college override needs that college in the caller's write scope. Rows are upserted on
   ``(institution_id, college_id, category, key)``, audited with the old/new values, the cache is dropped and
   ``settings.changed`` is emitted (consumer ``settings.invalidate_cache`` clears other processes' view).
3. ``public(institution)`` exposes only ``is_public`` keys plus the resolved theme; theme resolution order is
   user preference (``users.preferences.theme`` / ``table_style``) → institution (``general.theme``) → platform
   (``platform_settings['theme_default']``).
4. ``test_channel(channel, to)`` sends through the adapter registry (per-institution override in
   ``integrations.provider_overrides`` → platform default provider → ``mock``) and records a ``message_logs`` row
   (``event_type = settings.provider_test``) — 202 with the provider's reference.
"""

import json
import uuid
from collections.abc import Awaitable
from typing import Any, cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.config import settings as app_settings
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.settings_template import (
    BY_KEY,
    CATEGORIES,
    PLATFORM_THEME_DEFAULT,
    SETTINGS_TEMPLATE,
    THEME_TOKENS,
    SettingDef,
)
from app.db.session import redis_client
from app.repositories.institution_repository import InstitutionRepository, MessageLogRepository, SettingsRepository
from app.schemas.settings import (
    ProviderTestRequest,
    ProviderTestResponse,
    PublicSettingsResponse,
    SettingItem,
    SettingResponse,
    SettingsCategoryResponse,
)
from app.services.institution.context import check_college_writable, tenant_id

CACHE_TTL = 300


def cache_key(institution_id: Any, category: str) -> str:
    return f"settings:{institution_id}:{category}"


async def invalidate_settings_cache(institution_id: Any, categories: list[str] | None = None) -> None:
    keys = [cache_key(institution_id, c) for c in (categories or list(CATEGORIES))]
    await redis_client.delete(*keys)


def coerce(defn: SettingDef, value: Any) -> Any:
    """Validate/coerce one value against its definition; raises ``ValueError`` with a readable reason."""
    if value is None:
        return None
    t = defn.value_type
    if t == "str":
        if not isinstance(value, str):
            raise ValueError("must be a string")
        if len(value) > 500:
            raise ValueError("must be at most 500 characters")
        return value
    if t == "int":
        if isinstance(value, bool):
            raise ValueError("must be an integer")
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            value = int(value.strip())
        if not isinstance(value, int):
            raise ValueError("must be an integer")
        if defn.min is not None and value < defn.min:
            raise ValueError(f"must be ≥ {defn.min}")
        if defn.max is not None and value > defn.max:
            raise ValueError(f"must be ≤ {defn.max}")
        return value
    if t == "bool":
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
        return value
    if t == "list":
        if not isinstance(value, list):
            raise ValueError("must be a list")
        return value
    if t == "json":
        if not isinstance(value, dict | list):
            raise ValueError("must be a JSON object or array")
        return value
    if t == "enum":
        if value not in defn.choices:
            raise ValueError(f"must be one of {', '.join(defn.choices)}")
        return value
    raise ValueError(f"unsupported type {t}")


class SettingsService:
    def __init__(self, db: AsyncSession, principal: Any = None):
        self.db, self.principal = db, principal
        self.repo = SettingsRepository(db)

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def get(
        self, request: Request | None, category: str | None = None, college_id: uuid.UUID | None = None
    ) -> list[SettingsCategoryResponse]:
        inst = tenant_id(self.principal, request)
        if category is not None and category not in CATEGORIES:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown settings category {category!r}", {"field": "category"})
        cats = [category] if category else list(CATEGORIES)
        out: list[SettingsCategoryResponse] = []
        for cat in cats:
            if college_id is None:
                cached = await cast(Awaitable[str | None], redis_client.get(cache_key(inst, cat)))
                if cached:
                    items = [SettingResponse(**i) for i in json.loads(cached)]
                    out.append(SettingsCategoryResponse(category=cat, items=items))
                    continue
            items = await self._merged(inst, cat, college_id)
            if college_id is None:
                await redis_client.set(
                    cache_key(inst, cat), json.dumps([i.model_dump(mode="json") for i in items]), ex=CACHE_TTL
                )
            out.append(SettingsCategoryResponse(category=cat, items=items))
        return out

    async def _merged(self, inst: uuid.UUID, category: str, college_id: uuid.UUID | None) -> list[SettingResponse]:
        rows = await self.repo.rows(inst, category, college_id)
        inst_rows = {r.key: r for r in rows if r.college_id is None}
        college_rows = {r.key: r for r in rows if r.college_id is not None}
        items = []
        for d in (x for x in SETTINGS_TEMPLATE if x.category == category):
            row = college_rows.get(d.key) or inst_rows.get(d.key)
            value = row.value if row is not None else d.default
            items.append(
                SettingResponse(
                    category=d.category,
                    key=d.key,
                    value=value,
                    value_type=d.value_type,
                    is_public=d.is_public,
                    default=d.default,
                    is_default=row is None or row.value == d.default,
                    choices=list(d.choices),
                    label=d.label or None,
                    feature=d.feature,
                    college_id=row.college_id if row is not None else None,
                )
            )
        return items

    async def value(
        self, institution_id: uuid.UUID, category: str, key: str, college_id: uuid.UUID | None = None
    ) -> Any:
        """Effective value for services / tasks (college override → institution → template default)."""
        defn = BY_KEY.get((category, key))
        if college_id is not None:
            row = await self.repo.get(institution_id, category, key, college_id)
            if row is not None:
                return row.value
        row = await self.repo.get(institution_id, category, key, None)
        if row is not None:
            return row.value
        return defn.default if defn else None

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def bulk_update(
        self,
        items: list[SettingItem],
        request: Request | None,
        *,
        reason: str | None = None,
        strict: bool = False,
        action: str = "update",
    ) -> list[SettingsCategoryResponse]:
        """``strict`` (the ``PUT /settings`` route — Phase 37 rule 2): college overrides only for college-scoped keys,
        institution rows only from an institution scope, dependency hints enforced, ``reason`` for sensitive
        categories. Locked keys (platform scope / env / plan) are refused for every caller (409 RULE_VIOLATION)."""
        from app.core.settings_catalogue import CATALOGUE

        inst = tenant_id(self.principal, request)
        validated: list[tuple[SettingItem, SettingDef, Any]] = []
        errors: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            defn = BY_KEY.get((item.category, item.key))
            if defn is None:
                errors.append({"index": idx, "field": f"{item.category}.{item.key}", "reason": "unknown setting"})
                continue
            try:
                validated.append((item, defn, coerce(defn, item.value)))
            except ValueError as exc:
                errors.append({"index": idx, "field": defn.full_key, "reason": str(exc)})
        if errors:
            raise APIError(422, ErrorCode.VALIDATION, "Invalid setting values", {"errors": errors})
        sensitive: list[str] = []
        for idx, (item, defn, value) in enumerate(validated):
            meta = CATALOGUE.get(defn.full_key)
            if meta is None:
                continue
            if meta.scope == "platform" or meta.locked_by != "none":
                raise APIError(
                    409,
                    ErrorCode.RULE_VIOLATION,
                    f"{defn.full_key} is locked ({meta.lock_reason or meta.locked_by})",
                    {"code": "SETTING_LOCKED", "key": defn.full_key, "locked_by": meta.locked_by},
                )
            if not strict:
                continue
            if item.college_id is not None and meta.scope != "college":
                errors.append({"index": idx, "field": defn.full_key, "reason": "not overridable per college"})
            if meta.depends_on and value:
                dep_cat, _, dep_key = meta.depends_on[0].partition(".")
                pending = next(
                    (
                        v
                        for it, d, v in validated
                        if d.category == dep_cat and d.key == dep_key and it.college_id is None
                    ),
                    None,
                )
                dep_value = pending if pending is not None else await self.value(inst, dep_cat, dep_key)
                if not dep_value:
                    errors.append(
                        {
                            "index": idx,
                            "field": defn.full_key,
                            "reason": meta.dependency_hint or "dependency unmet",
                            "depends_on": meta.depends_on,
                        }
                    )
            if meta.sensitive:
                sensitive.append(defn.full_key)
        if errors:
            raise APIError(422, ErrorCode.VALIDATION, "Invalid setting values", {"errors": errors})
        if strict and sensitive and not (reason or "").strip():
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "A reason is required for changes to sensitive settings",
                {"field": "reason", "keys": sensitive},
            )
        for item, defn, _ in validated:
            if defn.feature and not await is_enabled(inst, defn.feature):
                raise APIError(
                    403,
                    ErrorCode.FEATURE_DISABLED,
                    f"Feature '{defn.feature}' is not enabled",
                    {"feature": defn.feature},
                )
            if strict or item.college_id is not None:
                # strict: an institution row (college_id NULL) also needs an institution scope
                check_college_writable(self.principal, item.college_id)
        changed: dict[str, dict[str, Any]] = {}
        old_values: dict[str, Any] = {}
        for item, defn, value in validated:
            _, old = await self.repo.upsert(
                inst,
                defn.category,
                defn.key,
                value=value,
                value_type=defn.value_type,
                is_public=defn.is_public,
                college_id=item.college_id,
                updated_by=self.principal.id if self.principal else None,
            )
            label = defn.full_key + (f"@{item.college_id}" if item.college_id else "")
            changed[label] = value
            old_values[label] = old
        categories = sorted({d.category for _, d, _ in validated})
        await invalidate_settings_cache(inst, categories)
        await log_audit(
            self.db,
            principal=self.principal,
            module="settings",
            action=action,
            record_type="institution_settings",
            record_id=inst,
            old=old_values,
            new={**changed, **({"_reason": reason} if reason else {})},
            request=request,
        )
        if sensitive:
            await self._sensitive_changed(inst, sensitive, reason)
        await events.emit(
            self.db,
            institution_id=inst,
            event_type="settings.changed",
            payload={"institution_id": str(inst), "categories": categories, "keys": sorted(changed)},
            aggregate_type="institution",
            aggregate_id=inst,
            actor_user_id=self.principal.id if self.principal else None,
        )
        out = []
        for cat in categories:
            out.append(SettingsCategoryResponse(category=cat, items=await self._merged(inst, cat, None)))
        return out

    async def _sensitive_changed(self, inst: uuid.UUID, keys: list[str], reason: str | None) -> None:
        from app.core.notifications.notify import notify_event

        roles = await self.value(inst, "audit", "sensitive_change_notify") or ["vice_chancellor"]
        actor = (
            getattr(self.principal, "display_name", None)
            or getattr(self.principal, "username", None)
            or "An administrator"
        )
        await events.emit(
            self.db,
            institution_id=inst,
            event_type="settings.changed_sensitive",
            payload={"keys": keys, "reason": reason},
            aggregate_type="institution",
            aggregate_id=inst,
            actor_user_id=self.principal.id if self.principal else None,
        )
        await notify_event(
            self.db,
            inst,
            "settings.changed_sensitive",
            audience={"roles": list(roles)},
            context={"keys": ", ".join(keys), "actor": str(actor), "reason": reason or ""},
            actor_user_id=self.principal.id if self.principal else None,
        )

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def public(self, institution_id: uuid.UUID | None, user: Any = None) -> PublicSettingsResponse:
        platform_default = (
            await InstitutionRepository(self.db).platform_setting("theme_default") or PLATFORM_THEME_DEFAULT
        )
        values: dict[str, dict[str, Any]] = {}
        for d in SETTINGS_TEMPLATE:
            if d.is_public:
                values.setdefault(d.category, {})[d.key] = d.default
        if institution_id is not None:
            for row in await self.repo.public_rows(institution_id):
                defn = BY_KEY.get((row.category, row.key))
                if defn is not None and defn.is_public:
                    values.setdefault(row.category, {})[row.key] = row.value
        theme, table_style = self.resolve_theme(values.get("general", {}), platform_default, user)
        return PublicSettingsResponse(
            institution_id=institution_id,
            theme=theme,
            table_style=table_style,
            theme_tokens=THEME_TOKENS.get(theme, THEME_TOKENS["indigo"]),
            settings=values,
        )

    @staticmethod
    def resolve_theme(general: dict[str, Any], platform_default: dict[str, Any], user: Any = None) -> tuple[str, str]:
        prefs = (getattr(user, "preferences", None) or {}) if user is not None else {}
        theme = prefs.get("theme") or general.get("theme") or platform_default.get("theme") or "indigo"
        style = (
            prefs.get("table_style") or general.get("table_style") or platform_default.get("table_style") or "minimal"
        )
        return str(theme), str(style)

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def test_channel(self, body: ProviderTestRequest, request: Request | None) -> ProviderTestResponse:
        from app.integrations.registry import get_adapter

        inst = tenant_id(self.principal, request)
        overrides = await self.value(inst, "integrations", "provider_overrides") or {}
        defaults = {
            "sms": app_settings.SMS_PROVIDER,
            "email": app_settings.EMAIL_PROVIDER,
            "whatsapp": app_settings.WHATSAPP_PROVIDER,
            "push": app_settings.PUSH_PROVIDER,
        }
        provider = str(overrides.get(body.channel) or defaults.get(body.channel) or "mock")
        text_body = body.message or "SeptronUniverse provider test — if you received this, the channel works."
        status, reference, error = "sent", None, None
        try:
            adapter = get_adapter(body.channel, provider)
            result = await adapter.send(to=body.to, body=text_body, subject="Provider test")
            provider = getattr(adapter, "provider", provider)
            reference = (result or {}).get("reference") if isinstance(result, dict) else None
        except Exception as exc:  # noqa: BLE001 - a failing provider is the answer the admin asked for
            status, error = "failed", str(exc)[:500]
        log_id = await MessageLogRepository(self.db).add(
            institution_id=inst,
            user_id=self.principal.id if self.principal else None,
            recipient=body.to,
            channel=body.channel,
            event_type="settings.provider_test",
            subject="Provider test",
            body_preview=text_body,
            provider=provider,
            provider_message_id=reference,
            status=status,
            error=error,
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="settings",
            action="test_provider",
            record_type="message_log",
            record_id=log_id,
            new={"channel": body.channel, "provider": provider, "status": status},
            request=request,
        )
        if status == "failed":
            await self.db.commit()  # keep the failed message_logs row (the error response rolls back otherwise)
            raise APIError(
                503, ErrorCode.INTEGRATION_FAILED, f"{body.channel} provider {provider} failed", {"error": error}
            )
        return ProviderTestResponse(
            channel=body.channel, provider=provider, status=status, reference=reference, message_log_id=log_id
        )
